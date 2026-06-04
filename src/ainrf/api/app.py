from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from anyio import to_thread
from fastapi import APIRouter, FastAPI

from ainrf.api.config import ApiConfig
from ainrf.api.middleware import build_jwt_auth_middleware
from ainrf.api.routes.admin import router as admin_router
from ainrf.api.routes.auth import router as auth_router
from ainrf.api.routes.code import router as code_router
from ainrf.api.routes.environments import router as environments_router
from ainrf.api.routes.files import router as files_router
from ainrf.api.routes.health import router as health_router
from ainrf.api.routes.literature import router as literature_router
from ainrf.api.routes.projects import router as projects_router, task_edges_router
from ainrf.api.routes.resources import router as resources_router
from ainrf.api.routes.sessions import router as sessions_router
from ainrf.api.routes.settings import router as settings_router
from ainrf.api.routes.skill_registries import router as skill_registries_router
from ainrf.api.routes.skills import router as skills_router
from ainrf.api.routes.tasks import router as tasks_router
from ainrf.api.routes.terminal import router as terminal_router
from ainrf.api.routes.workspaces import router as workspaces_router
from ainrf.auth import AuthService
from ainrf.code_server import CodeServerSupervisor
from ainrf.environments import InMemoryEnvironmentService
from ainrf.files import FileBrowserService
from ainrf.literature.scheduler import LiteratureScheduler
from ainrf.literature.service import LiteratureService
from ainrf.monitor.service import ResourceMonitorService
from ainrf.projects import ProjectRegistryService
from ainrf.runtime.readiness import check_runtime_readiness
from ainrf.sessions import SessionService
from ainrf.skills import SkillsDiscoveryService
from ainrf.agentic_researcher import AgenticResearcherService
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter
from ainrf.workspaces import WorkspaceRegistryService


def _run_sync_in_lifespan(callback: Callable[[], None]) -> Awaitable[None]:
    # Startup services do filesystem/tmux work; run them off the event loop during lifespan.
    return to_thread.run_sync(callback)


ROUTERS: tuple[APIRouter, ...] = (
    admin_router,
    auth_router,
    health_router,
    environments_router,
    files_router,
    projects_router,
    task_edges_router,
    skills_router,
    skill_registries_router,
    workspaces_router,
    terminal_router,
    tasks_router,
    sessions_router,
    code_router,
    literature_router,
    resources_router,
    settings_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    environment_service = app.state.environment_service
    workspace_service = app.state.workspace_service
    terminal_session_manager = app.state.terminal_session_manager
    terminal_attachment_broker = app.state.terminal_attachment_broker
    project_service = app.state.project_service
    manager = CodeServerSupervisor(
        state_root=app.state.api_config.state_root,
        environment_service=environment_service,
        local_host=app.state.api_config.code_server_host,
        local_port=app.state.api_config.code_server_port,
    )
    app.state.code_server_manager = manager
    app.state.code_server_supervisor = manager
    resource_monitor_service = ResourceMonitorService(environment_service)
    app.state.resource_monitor_service = resource_monitor_service
    await resource_monitor_service.start()
    try:
        await _run_sync_in_lifespan(project_service.initialize)
        await _run_sync_in_lifespan(workspace_service.initialize)
        localhost = environment_service.get_environment("env-localhost")
        app.state.runtime_readiness = check_runtime_readiness(
            localhost.code_server_path
        ).as_public_payload()
        await _run_sync_in_lifespan(terminal_session_manager.reconcile)
        session_service = app.state.session_service
        await _run_sync_in_lifespan(session_service.initialize)
        auth_service = app.state.auth_service
        await _run_sync_in_lifespan(auth_service.initialize)
        await _run_sync_in_lifespan(app.state.literature_service.initialize)
        literature_scheduler = LiteratureScheduler(app.state.literature_service)
        literature_scheduler.start()
        app.state.literature_scheduler = literature_scheduler
        # Create initial admin if no users exist
        try:
            with auth_service._connect() as conn:
                count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                # Generate secure random password
                import secrets
                import string

                alphabet = string.ascii_letters + string.digits + string.punctuation
                initial_password = "".join(secrets.choice(alphabet) for _ in range(24))

                admin_user = auth_service.register(
                    username="admin",
                    display_name="Administrator",
                    password=initial_password,
                    must_change_password=True,
                )
                with auth_service._connect() as conn:
                    conn.execute(
                        "UPDATE users SET status = 'active', role = 'admin', activated_at = ? WHERE username = 'admin'",
                        (datetime.now(timezone.utc).isoformat(),),
                    )
                    conn.commit()
                # Auto-grant seed environments to initial admin
                auth_service._grant_seed_environments(admin_user.id)

                # Write password to protected file instead of stdout
                password_file = app.state.api_config.state_root / "admin_initial_password.txt"
                password_file.write_text(f"Initial admin password: {initial_password}\n")
                password_file.chmod(0o600)

                print(
                    "\n" + "=" * 60 + "\n"
                    "Initial admin created!\n"
                    "Username: admin\n"
                    f"Password: (saved to {password_file})\n"
                    "You will be prompted to change the password on first login.\n"
                    + "=" * 60
                    + "\n"
                )
            # Fix existing admin users with wrong role (migration from bug)
            with auth_service._connect() as conn:
                conn.execute(
                    "UPDATE users SET role = 'admin' WHERE username = 'admin' AND role != 'admin'"
                )
                conn.commit()
        except Exception:
            pass
        yield
    finally:
        await _run_sync_in_lifespan(terminal_attachment_broker.shutdown)
        await manager.stop()
        await resource_monitor_service.stop()
        if hasattr(app.state, "literature_scheduler"):
            await app.state.literature_scheduler.shutdown()


def create_app(
    config: ApiConfig | None = None,
    *,
    max_file_size_bytes: int | None = None,
) -> FastAPI:
    api_config = config or ApiConfig.from_env()
    runtime_paths = api_config.runtime_paths
    default_workspace_dir = runtime_paths.ensure_default_workspace_dir()
    project_service = ProjectRegistryService(api_config.state_root)
    environment_service = InMemoryEnvironmentService(
        str(default_workspace_dir),
        project_service=project_service,
    )
    app = FastAPI(title="AINRF API", version="0.1.0", lifespan=lifespan)
    app.state.api_config = api_config
    # Service initialization order:
    # 1. project/workspace (no deps)
    # 2. terminal (no deps)
    # 3. session_service (standalone)
    # 4. auth_service (standalone; middleware consumer)
    auth_service = AuthService(state_root=api_config.state_root)
    app.state.auth_service = auth_service
    app.state.project_service = project_service
    app.state.environment_service = environment_service
    app.state.workspace_service = WorkspaceRegistryService(
        api_config.state_root,
        default_workspace_dir=default_workspace_dir,
    )
    app.state.terminal_session_manager = SessionManager(
        state_root=api_config.state_root,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(api_config.state_root),
        default_shell=api_config.terminal_command[0] if api_config.terminal_command else None,
    )
    app.state.terminal_attachment_broker = TerminalAttachmentBroker()
    file_browser_kwargs: dict = dict(
        environment_service=environment_service,
        workspace_service=app.state.workspace_service,
    )
    if max_file_size_bytes is not None:
        file_browser_kwargs["max_file_size_bytes"] = max_file_size_bytes
    app.state.file_browser_service = FileBrowserService(**file_browser_kwargs)
    app.state.skills_discovery_service = SkillsDiscoveryService(
        scan_roots=[default_workspace_dir],
    )
    app.state.session_service = SessionService(
        state_root=api_config.state_root,
    )
    agentic_researcher_service = AgenticResearcherService(
        state_root=api_config.state_root,
        workspace_service=app.state.workspace_service,
    )
    agentic_researcher_service.initialize()
    app.state.agentic_researcher_service = agentic_researcher_service
    app.state.literature_service = LiteratureService(state_root=api_config.state_root)
    app.middleware("http")(build_jwt_auth_middleware(auth_service, api_config))
    for router in ROUTERS:
        app.include_router(router)
        app.include_router(router, prefix="/v1")
    return app

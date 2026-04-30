from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import APIRouter, FastAPI

from ainrf.api.config import ApiConfig
from ainrf.api.middleware import build_api_key_middleware
from ainrf.api.routes.code import router as code_router
from ainrf.api.routes.environments import router as environments_router
from ainrf.api.routes.files import router as files_router
from ainrf.api.routes.health import router as health_router
from ainrf.api.routes.projects import router as projects_router
from ainrf.api.routes.skills import router as skills_router
from ainrf.api.routes.tasks import router as tasks_router
from ainrf.api.routes.terminal import router as terminal_router
from ainrf.api.routes.workspaces import router as workspaces_router
from ainrf.code_server import CodeServerSupervisor
from ainrf.files import FileBrowserService
from ainrf.environments import InMemoryEnvironmentService
from ainrf.runtime.readiness import check_runtime_readiness
from ainrf.skills import SkillsDiscoveryService
from ainrf.task_harness import TaskHarnessService
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter
from ainrf.workspaces import WorkspaceRegistryService


def _run_sync_in_lifespan(callback: Callable[[], None]) -> Awaitable[None]:
    # Startup services do filesystem/tmux work; run them off the event loop during lifespan.
    return to_thread.run_sync(callback)


ROUTERS: tuple[APIRouter, ...] = (
    health_router,
    environments_router,
    files_router,
    projects_router,
    skills_router,
    workspaces_router,
    terminal_router,
    tasks_router,
    code_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    environment_service = app.state.environment_service
    workspace_service = app.state.workspace_service
    terminal_session_manager = app.state.terminal_session_manager
    terminal_attachment_broker = app.state.terminal_attachment_broker
    task_harness_service = app.state.task_harness_service
    manager = CodeServerSupervisor(
        state_root=app.state.api_config.state_root,
        environment_service=environment_service,
        local_host=app.state.api_config.code_server_host,
        local_port=app.state.api_config.code_server_port,
    )
    app.state.code_server_manager = manager
    app.state.code_server_supervisor = manager
    try:
        await _run_sync_in_lifespan(workspace_service.initialize)
        localhost = environment_service.get_environment("env-localhost")
        app.state.runtime_readiness = check_runtime_readiness(
            localhost.code_server_path
        ).as_public_payload()
        await _run_sync_in_lifespan(terminal_session_manager.reconcile)
        await _run_sync_in_lifespan(task_harness_service.initialize)
        yield
    finally:
        await _run_sync_in_lifespan(terminal_attachment_broker.shutdown)
        await manager.stop()


def create_app(config: ApiConfig | None = None) -> FastAPI:
    api_config = config or ApiConfig.from_env()
    runtime_paths = api_config.runtime_paths
    default_workspace_dir = runtime_paths.ensure_default_workspace_dir()
    environment_service = InMemoryEnvironmentService(str(default_workspace_dir))
    app = FastAPI(title="AINRF API", version="0.1.0", lifespan=lifespan)
    app.state.api_config = api_config
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
    app.state.file_browser_service = FileBrowserService(
        environment_service=environment_service,
        workspace_service=app.state.workspace_service,
    )
    app.state.skills_discovery_service = SkillsDiscoveryService(
        scan_roots=[default_workspace_dir],
    )
    app.state.task_harness_service = TaskHarnessService(
        state_root=api_config.state_root,
        environment_service=environment_service,
        workspace_service=app.state.workspace_service,
    )
    app.middleware("http")(build_api_key_middleware(api_config))
    for router in ROUTERS:
        app.include_router(router)
        app.include_router(router, prefix="/v1")
    return app

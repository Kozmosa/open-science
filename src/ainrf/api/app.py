from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from anyio import to_thread
from fastapi import APIRouter, FastAPI
from starlette.responses import Response

from ainrf.api.config import ApiConfig
from ainrf.api.middleware import (
    build_concurrency_limit_middleware,
    build_ip_allowlist_middleware,
    build_jwt_auth_middleware,
    build_request_size_middleware,
)
from ainrf.api.middleware.request_context import build_request_context_middleware
from ainrf.api.middleware.request_logging import build_request_logging_middleware
from ainrf.api.routes.admin import router as admin_router
from ainrf.api.routes.auth import router as auth_router
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
from ainrf.api.routes.client_logs import router as client_logs_router
from ainrf.api.routes.client_metrics import router as client_metrics_router
from ainrf.auth import AuthService
from ainrf.environments import InMemoryEnvironmentService
from ainrf.files import FileBrowserService
from ainrf.literature.scheduler import LiteratureScheduler
from ainrf.literature.service import LiteratureService
from ainrf.monitor.service import ResourceMonitorService
from ainrf.projects import ProjectRegistryService
from ainrf.runtime.readiness import check_runtime_readiness
from ainrf.sessions import SessionService
from ainrf.skills import SkillsDiscoveryService
from ainrf.skills.registry_config_service import SkillRegistryConfigService
from ainrf.agentic_researcher import AgenticResearcherService
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter
from ainrf.workspaces import WorkspaceRegistryService


T = TypeVar("T")


def _run_sync_in_lifespan(callback: Callable[[], T]) -> Awaitable[T]:
    # Startup services do filesystem/tmux work; run them off the event loop during lifespan.
    return to_thread.run_sync(callback)


_LOG = logging.getLogger(__name__)


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
    literature_router,
    resources_router,
    settings_router,
    client_logs_router,
    client_metrics_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    environment_service = app.state.environment_service
    workspace_service = app.state.workspace_service
    terminal_session_manager = app.state.terminal_session_manager
    terminal_attachment_broker = app.state.terminal_attachment_broker
    project_service = app.state.project_service
    resource_monitor_service = ResourceMonitorService(environment_service)
    app.state.resource_monitor_service = resource_monitor_service
    await resource_monitor_service.start()
    try:
        await _run_sync_in_lifespan(project_service.initialize)
        await _run_sync_in_lifespan(workspace_service.initialize)
        app.state.runtime_readiness = check_runtime_readiness().as_public_payload()
        await _run_sync_in_lifespan(terminal_session_manager.reconcile)
        session_service = app.state.session_service
        await _run_sync_in_lifespan(session_service.initialize)
        auth_service = app.state.auth_service
        await _run_sync_in_lifespan(auth_service.initialize)
        await _run_sync_in_lifespan(app.state.literature_service.initialize)
        literature_scheduler = LiteratureScheduler(
            app.state.literature_service,
            reporter=app.state.observability_reporter,
        )
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
                _LOG.info("initial_admin_created", username="admin", password_file=str(password_file))
            # Admin role fix is handled by auth migration_003_admin_role_fix
        except Exception:
            _LOG.exception("Failed to create initial admin user")
        # Backfill per-user default projects for any user lacking one (idempotent).
        # Covers pre-existing users and the bootstrap admin created directly above,
        # which bypasses the HTTP registration hook that normally provisions it.
        try:
            from ainrf.projects.backfill import backfill_user_default_projects

            created, _skipped = await _run_sync_in_lifespan(
                lambda: backfill_user_default_projects(
                    project_service=project_service,
                    users=auth_service.list_users(),
                )
            )
            if created:
                _LOG.info("Backfilled %d per-user default project(s)", created)
        except Exception:
            _LOG.exception("Failed to backfill per-user default projects")
        yield
    finally:
        await _run_sync_in_lifespan(terminal_attachment_broker.shutdown)
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
    # Disable interactive API docs in production.
    docs_url = None if api_config.production else "/docs"
    redoc_url = None if api_config.production else "/redoc"
    openapi_url = None if api_config.production else "/openapi.json"
    app = FastAPI(
        title="OpenScience API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.api_config = api_config
    # Service initialization order:
    # 1. project/workspace (no deps)
    # 2. terminal (no deps)
    # 3. session_service (standalone)
    # 4. auth_service (standalone; middleware consumer)
    auth_service = AuthService(
        state_root=api_config.state_root,
        login_max_failures=api_config.login_max_failures,
        login_lockout_hours=api_config.login_lockout_hours,
    )
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
        auth_service=auth_service,
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
    app.state.skill_registry_config_service = SkillRegistryConfigService(
        state_root=api_config.state_root,
    )
    app.state.skill_registry_config_service.initialize()
    app.state.session_service = SessionService(
        state_root=api_config.state_root,
    )
    # Initialize LLM observability reporter (singleton).
    from ainrf.observability.factory import get_reporter
    from ainrf.observability.protocol import ObservabilityConfig

    obs_config = ObservabilityConfig(
        enabled=api_config.observability_enabled,
        base_url=api_config.observability_base_url,
        secret_key=api_config.observability_secret_key,
        public_key=api_config.observability_public_key,
    )
    reporter = get_reporter(obs_config)
    app.state.observability_reporter = reporter

    agentic_researcher_service = AgenticResearcherService(
        state_root=api_config.state_root,
        workspace_service=app.state.workspace_service,
        auth_service=auth_service,
        observability_reporter=reporter,
    )
    agentic_researcher_service.initialize()
    app.state.agentic_researcher_service = agentic_researcher_service
    app.state.literature_service = LiteratureService(state_root=api_config.state_root)

    # Initialize OpenTelemetry auto-instrumentation (disabled by default).
    from ainrf.telemetry import init_telemetry
    init_telemetry(app)

    # Middleware order (outermost first):
    #   1. Request context — attach request_id + structlog binding
    #   2. Request logging — log method/path/status/duration with request_id
    #   3. IP allowlist — reject unknown networks before anything else
    #   4. Request body size limit
    #   5. Concurrency guard (optional)
    #   6. JWT / API-key authentication
    #   7. Rate limiting (per-user/IP, optional, after auth so we can key by user)
    #   8. Exception handler — catch unhandled exceptions, return structured 500
    app.middleware("http")(build_request_context_middleware())
    app.middleware("http")(build_request_logging_middleware(api_config))
    app.middleware("http")(build_ip_allowlist_middleware(api_config.allowed_cidrs))
    app.middleware("http")(build_request_size_middleware(api_config.max_request_body_bytes))
    if api_config.max_concurrent_requests > 0:
        app.middleware("http")(
            build_concurrency_limit_middleware(api_config.max_concurrent_requests)
        )
    app.middleware("http")(build_jwt_auth_middleware(auth_service, api_config))
    from ainrf.api.middleware.rate_limit import build_rate_limit_middleware
    app.middleware("http")(build_rate_limit_middleware())
    # Innermost: exception handler must be registered after other middleware
    # so it can catch exceptions from route handlers (and from upstream
    # middleware that re-raises).
    from ainrf.api.middleware.exception_handler import build_exception_handler_middleware
    app.middleware("http")(build_exception_handler_middleware())
    for router in ROUTERS:
        app.include_router(router)
        app.include_router(router, prefix="/v1")
        app.include_router(router, prefix="/api")
    # Metrics endpoint (gated by config)
    if api_config.metrics_enabled:
        from ainrf.api.routes.metrics import build_http_metrics_middleware, create_metrics_router

        app.middleware("http")(build_http_metrics_middleware())
        app.include_router(create_metrics_router(api_config))

    # ── Serve frontend static files ───────────────────────────────
    frontend_dist = Path(os.environ.get("AINRF_FRONTEND_DIR", "/opt/ainrf/frontend/dist"))
    if frontend_dist.is_dir():
        from starlette.staticfiles import StaticFiles
        from starlette.responses import FileResponse

        class _SPAStaticFiles(StaticFiles):
            """StaticFiles that returns index.html for non-file paths (SPA fallback)."""

            async def get_response(self, path: str, scope) -> Response:
                try:
                    response = await super().get_response(path, scope)
                    if response.status_code == 404:
                        return FileResponse(frontend_dist / "index.html", media_type="text/html")
                    return response
                except Exception:
                    return FileResponse(frontend_dist / "index.html", media_type="text/html")

        app.mount("/", _SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app

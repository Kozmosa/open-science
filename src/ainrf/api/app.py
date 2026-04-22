from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI

from ainrf.api.config import ApiConfig
from ainrf.api.middleware import build_api_key_middleware
from ainrf.api.routes.code import router as code_router
from ainrf.api.routes.environments import router as environments_router
from ainrf.api.routes.health import router as health_router
from ainrf.api.routes.projects import router as projects_router
from ainrf.api.routes.tasks import router as tasks_router
from ainrf.api.routes.terminal import router as terminal_router
from ainrf.code_server import CodeServerSupervisor
from ainrf.environments import InMemoryEnvironmentService
from ainrf.tasks.service import TaskManager
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter


def _run_sync_in_lifespan(callback: Callable[[], None]) -> Awaitable[None]:
    return to_thread.run_sync(callback)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    environment_service = app.state.environment_service
    terminal_session_manager = app.state.terminal_session_manager
    terminal_attachment_broker = app.state.terminal_attachment_broker
    task_manager = app.state.task_manager
    manager = CodeServerSupervisor(
        state_root=app.state.api_config.state_root,
        environment_service=environment_service,
        local_host=app.state.api_config.code_server_host,
        local_port=app.state.api_config.code_server_port,
    )
    app.state.code_server_manager = manager
    app.state.code_server_supervisor = manager
    try:
        await _run_sync_in_lifespan(terminal_session_manager.reconcile)
        await _run_sync_in_lifespan(task_manager.reconcile)
        yield
    finally:
        await _run_sync_in_lifespan(terminal_attachment_broker.shutdown)
        await manager.stop()


def create_app(config: ApiConfig | None = None) -> FastAPI:
    api_config = config or ApiConfig.from_env()
    environment_service = InMemoryEnvironmentService()
    app = FastAPI(title="AINRF API", version="0.1.0", lifespan=lifespan)
    app.state.api_config = api_config
    app.state.environment_service = environment_service
    app.state.terminal_session_manager = SessionManager(
        state_root=api_config.state_root,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(api_config.state_root),
        default_shell=api_config.terminal_command[0] if api_config.terminal_command else None,
    )
    app.state.terminal_attachment_broker = TerminalAttachmentBroker()
    app.state.task_manager = TaskManager(
        state_root=api_config.state_root,
        environment_service=environment_service,
        session_manager=app.state.terminal_session_manager,
        tmux_adapter=app.state.terminal_session_manager.tmux_adapter,
    )
    app.middleware("http")(build_api_key_middleware(api_config))
    app.include_router(health_router)
    app.include_router(environments_router)
    app.include_router(projects_router)
    app.include_router(terminal_router)
    app.include_router(tasks_router)
    app.include_router(code_router)
    app.include_router(health_router, prefix="/v1")
    app.include_router(environments_router, prefix="/v1")
    app.include_router(projects_router, prefix="/v1")
    app.include_router(terminal_router, prefix="/v1")
    app.include_router(tasks_router, prefix="/v1")
    app.include_router(code_router, prefix="/v1")
    return app

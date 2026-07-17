from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar
from anyio import to_thread
from fastapi import APIRouter, FastAPI
from starlette.responses import Response

from ainrf.api.config import ApiConfig
from ainrf.api.middleware import (
    build_concurrency_limit_middleware,
    build_domain_maintenance_middleware,
    build_ip_allowlist_middleware,
    build_jwt_auth_middleware,
    build_maintenance_startup_read_only_middleware,
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
from ainrf.api.routes.domain import router as domain_router
from ainrf.auth import AuthService
from ainrf.environments import InMemoryEnvironmentService
from ainrf.files import FileBrowserService
from ainrf.literature.service import LiteratureService
from ainrf.literature.tracking import LiteratureTrackingService
from ainrf.literature.task_saga import LiteratureTaskSagaService
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
from ainrf.domain_control import (
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    DomainModelMode,
    DomainWriteParticipant,
    MaintenanceModeError,
)
from ainrf.domain import (
    AttemptProjectionService,
    DomainService,
    OverviewSnapshotService,
    PersistentEnvironmentFacade,
    PersistentWorkspaceFacade,
    ProjectContextService,
    SessionProjectionService,
    TaskApplicationService,
    TaskProjectionService,
)
from ainrf.domain.environment_observations import PersistentEnvironmentObservationService


T = TypeVar("T")


def _run_sync_in_lifespan(callback: Callable[[], T]) -> Awaitable[T]:
    # Startup services do filesystem/tmux work; run them off the event loop during lifespan.
    return to_thread.run_sync(callback)


_LOG = logging.getLogger(__name__)


def _maintenance_is_active_read_only(state_root: Path) -> bool:
    """Inspect an existing maintenance flag without creating any state.

    ``create_app`` normally builds several services whose constructors create
    directories or run migrations.  During a staged restore/cutover, that is
    already too late: the process must decide whether it may assemble its
    writable service graph before it instantiates any of those services.

    A missing control database or pre-maintenance schema is a normal fresh
    install and therefore does not imply maintenance.  A present but unreadable
    or malformed maintenance table is fail-closed: starting the writable graph
    without a trustworthy answer would violate the maintenance epoch.
    """

    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    if not database_path.is_file():
        return False
    # A live WAL contains uncheckpointed state which immutable reads cannot
    # observe.  A lone ``-shm`` is only SQLite's lock/cache artifact: without
    # a WAL the main database remains complete and immutable mode is safe.
    # Treat the former as indeterminate/fail-closed without penalising normal
    # process restarts that merely left a shared-memory file behind.
    if database_path.with_name(f"{database_path.name}-wal").exists():
        return True
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(database_uri, uri=True, isolation_level=None) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'domain_maintenance_state'"
            ).fetchone()
            if table is None:
                return False
            row = connection.execute(
                "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "cannot read persisted domain maintenance state; refusing writable API startup"
        ) from exc
    if row is None:
        raise RuntimeError(
            "persisted domain maintenance state is malformed; refusing writable API startup"
        )
    return bool(row[0])


def _assert_domain_runtime_fuse(config: ApiConfig, controller: DomainCutoverController) -> None:
    """Reject binaries whose configured mode disagrees with the DB fuse.

    This deliberately runs before construction of legacy registries.  A
    legacy/validate process must never reach a previously committed v2 state,
    and a v2 process needs the exact immutable artifact it was prepared for.
    """

    status = controller.status()
    if config.domain_model_mode is DomainModelMode.V2:
        artifact_sha = config.domain_artifact_sha
        if not artifact_sha:
            raise ValueError("OPENSCIENCE_DOMAIN_ARTIFACT_SHA is required in v2 mode")
        controller.assert_v2_writable(artifact_sha=artifact_sha)
        return
    if status.state != "legacy":
        raise DomainCutoverError(
            "legacy/validate binary cannot open a prepared or committed domain cutover database"
        )


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
    domain_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    workspace_service = app.state.workspace_service
    terminal_session_manager = app.state.terminal_session_manager
    terminal_attachment_broker = app.state.terminal_attachment_broker
    project_service = app.state.project_service
    is_v2 = app.state.api_config.domain_model_mode is DomainModelMode.V2
    runtime_reconciliation_enabled = app.state.api_config.runtime_reconciliation_enabled
    resource_monitor_service: ResourceMonitorService | None = app.state.resource_monitor_service
    api_participant = DomainWriteParticipant(
        app.state.domain_maintenance_service,
        "api",
        details={"component": "fastapi"},
    )
    api_participant.start()
    app.state.domain_api_participant_id = api_participant.participant_id
    legacy_task_service = app.state.agentic_researcher_service
    if legacy_task_service is not None:
        legacy_task_service.bind_maintenance_participant(api_participant.participant_id)
    terminal_reconciler_participant: DomainWriteParticipant | None = None
    if runtime_reconciliation_enabled:
        terminal_reconciler_participant = DomainWriteParticipant(
            app.state.domain_maintenance_service,
            "terminal-session-reconciler",
            details={"component": "api-lifespan"},
        )
        terminal_reconciler_participant.start()
        app.state.domain_terminal_reconciler_participant_id = (
            terminal_reconciler_participant.participant_id
        )
    else:
        app.state.domain_terminal_reconciler_participant_id = None

    # A process joining an existing maintenance epoch is a known drained
    # participant, not a permission to repair legacy registries or bootstrap
    # auth/domain state.  Register the writer identities first so cutover
    # preflight can see them, then keep every startup write path dormant until
    # maintenance exits and the service is restarted.
    # A process that was assembled while maintenance was active deliberately
    # remains read-only even if an operator exits maintenance before this
    # lifespan starts.  It has no writable service graph; require a clean
    # restart instead of accidentally reviving only part of one.
    startup_writes_paused = (
        bool(getattr(app.state, "maintenance_startup_read_only", False))
        or app.state.domain_maintenance_service.status().is_active
    )
    if startup_writes_paused:
        _LOG.info(
            "startup_writes_skipped_for_domain_maintenance",
            extra={"component": "api-lifespan"},
        )

    # Resource collection is observation-only.  In v2 it receives the
    # persistent facade, so it never reaches the retired process-local
    # Environment registry or triggers detection writes.  It is still not
    # started while maintenance is active: a restart must remain quiescent.
    if runtime_reconciliation_enabled and not startup_writes_paused:
        if resource_monitor_service is None:
            raise RuntimeError("writable API startup is missing its resource monitor service")
        await resource_monitor_service.start()
    elif runtime_reconciliation_enabled:
        _LOG.info(
            "runtime_reconciliation_skipped_for_domain_maintenance",
            extra={"component": "resource-monitor"},
        )
    else:
        _LOG.info("runtime_reconciliation_disabled", extra={"component": "resource-monitor"})

    async def heartbeat_api_participant() -> None:
        while True:
            await _run_sync_in_lifespan(api_participant.heartbeat)
            if terminal_reconciler_participant is not None:
                await _run_sync_in_lifespan(terminal_reconciler_participant.heartbeat)
            await asyncio.sleep(5)

    heartbeat_task: asyncio.Task[None] | None = None
    try:
        app.state.runtime_readiness = check_runtime_readiness().as_public_payload()
        if startup_writes_paused:
            # Do not initialize legacy JSON registries, Session/Literature
            # databases, bootstrap an administrator, or reconcile v2 default
            # Projects.  Each of those paths can create durable source state.
            yield
            return
        heartbeat_task = asyncio.create_task(heartbeat_api_participant())
        if project_service is not None:
            await _run_sync_in_lifespan(project_service.initialize)
        await _run_sync_in_lifespan(workspace_service.initialize)
        if not is_v2 and terminal_reconciler_participant is not None:
            try:
                terminal_lease = terminal_reconciler_participant.begin_mutation(
                    source="terminal-reconcile"
                )
            except MaintenanceModeError:
                terminal_reconciler_participant.drain()
                _LOG.info("terminal_reconcile_skipped_for_domain_maintenance")
            else:
                try:
                    await _run_sync_in_lifespan(terminal_session_manager.reconcile)
                    app.state.domain_maintenance_service.check_lease(terminal_lease)
                finally:
                    terminal_reconciler_participant.finish_mutation(terminal_lease)
        session_service = app.state.session_service
        if session_service is not None:
            await _run_sync_in_lifespan(session_service.initialize)
        auth_service = app.state.auth_service
        await _run_sync_in_lifespan(auth_service.initialize)
        await _run_sync_in_lifespan(app.state.literature_service.initialize)
        await _run_sync_in_lifespan(app.state.literature_tracking_service.initialize)
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
                _LOG.info(
                    "initial_admin_created",
                    extra={"username": "admin", "password_file": str(password_file)},
                )
            # Admin role fix is handled by auth migration_003_admin_role_fix
        except Exception:
            _LOG.exception("Failed to create initial admin user")
        # v2 registration records an auth-local provisioning intent rather
        # than claiming an impossible cross-database transaction.  Reconcile
        # every known user at startup: a retry after either database commits is
        # harmless because the domain default-Project write is idempotent.
        if is_v2:

            def reconcile_v2_default_projects() -> None:
                domain_service: DomainService = app.state.domain_service
                for account in auth_service.list_users():
                    auth_service.ensure_domain_default_project_provisioning(
                        account.id, account.username
                    )
                for user_id, username in auth_service.pending_domain_default_project_provisioning():
                    try:
                        domain_service.provision_default_project(user_id=user_id, username=username)
                    except Exception as exc:
                        _LOG.exception(
                            "v2_default_project_provisioning_failed",
                            extra={"user_id": user_id},
                        )
                        auth_service.record_domain_default_project_provisioning_failure(
                            user_id, exc
                        )
                    else:
                        auth_service.mark_domain_default_project_provisioned(user_id)

            try:
                await _run_sync_in_lifespan(reconcile_v2_default_projects)
            except Exception:
                _LOG.exception("v2_default_project_provisioning_reconcile_failed")
        # Legacy mode continues its historical JSON registry backfill.
        # Covers pre-existing users and the bootstrap admin created directly above,
        # which bypasses the HTTP registration hook that normally provisions it.
        elif project_service is not None:
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
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        if terminal_reconciler_participant is not None:
            terminal_reconciler_participant.stop()
        api_participant.stop()
        # A maintenance-mode restart never opens terminal attachments.  Avoid
        # allocating a worker solely to tear down the empty in-memory broker:
        # the process may otherwise wait on executor shutdown while it is
        # deliberately quiescent for restore/cutover.
        if startup_writes_paused:
            terminal_attachment_broker.shutdown()
        else:
            await _run_sync_in_lifespan(terminal_attachment_broker.shutdown)
        if resource_monitor_service is not None:
            await resource_monitor_service.stop()


def create_app(
    config: ApiConfig | None = None,
    *,
    max_file_size_bytes: int | None = None,
) -> FastAPI:
    api_config = config or ApiConfig.from_env()
    is_v2 = api_config.domain_model_mode is DomainModelMode.V2
    runtime_paths = api_config.runtime_paths
    # This must happen before DomainCutoverController, v2 facades, the legacy
    # default Workspace helper, or the saga.  Several of those constructors
    # otherwise create directories or run migrations as a side effect.
    maintenance_startup_read_only = _maintenance_is_active_read_only(api_config.state_root)
    default_workspace_dir = runtime_paths.default_workspace_dir
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
    maintenance_service = DomainMaintenanceService(api_config.state_root)
    app.state.domain_maintenance_service = maintenance_service
    if maintenance_startup_read_only:
        # The read-only probe above established that a persisted maintenance
        # epoch exists.  Adopt its already-complete control schema instead of
        # rerunning pending migrations while the staged state is quiescent.
        # Lifespan may still register this process as a drained participant;
        # that explicit control-plane record is not an application bootstrap.
        maintenance_service.adopt_existing_maintenance_schema()
    else:
        # A transition which starts after the read-only probe must still stop
        # assembly before any constructor with a durable side effect runs.
        maintenance_service.initialize()
        maintenance_startup_read_only = maintenance_service.status().is_active
    app.state.maintenance_startup_read_only = maintenance_startup_read_only

    artifact_sha = api_config.domain_artifact_sha if is_v2 else None
    auth_service = AuthService(
        state_root=api_config.state_root,
        login_max_failures=api_config.login_max_failures,
        login_lockout_hours=api_config.login_lockout_hours,
    )
    app.state.auth_service = auth_service
    app.state.terminal_attachment_broker = TerminalAttachmentBroker()

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

    if maintenance_startup_read_only:
        # Keep a maintenance restart intentionally incomplete.  The app can
        # expose health and maintenance/capability evidence, but no service
        # whose construction might create a source file, run a migration, or
        # initialize an external runtime is attached.  Exiting maintenance
        # therefore requires a clean restart to regain the writable graph.
        app.state.domain_cutover_controller = None
        app.state.domain_service = None
        app.state.project_context_service = None
        app.state.persistent_environment_facade = None
        app.state.task_application_service = None
        app.state.attempt_projection_service = None
        app.state.task_projection_service = None
        app.state.project_task_projection_service = None
        app.state.session_projection_service = None
        app.state.project_cost_projection_service = None
        app.state.overview_snapshot_service = None
        app.state.project_service = None
        app.state.environment_service = None
        app.state.environment_observation_service = None
        app.state.resource_monitor_service = None
        app.state.workspace_service = None
        app.state.terminal_session_manager = None
        app.state.file_browser_service = None
        app.state.skills_discovery_service = None
        app.state.skill_registry_config_service = SkillRegistryConfigService(
            state_root=api_config.state_root,
            read_only=True,
        )
        app.state.session_service = None
        app.state.agentic_researcher_service = None
        app.state.literature_service = None
        app.state.literature_tracking_service = None
        app.state.literature_task_saga_service = None
    else:
        domain_cutover_controller = DomainCutoverController(api_config.state_root)
        _assert_domain_runtime_fuse(api_config, domain_cutover_controller)
        app.state.domain_cutover_controller = domain_cutover_controller

        default_workspace_dir = (
            runtime_paths.default_workspace_dir
            if is_v2
            else runtime_paths.ensure_default_workspace_dir()
        )
        project_service = None if is_v2 else ProjectRegistryService(api_config.state_root)
        environment_service = (
            PersistentEnvironmentFacade(api_config.state_root)
            if is_v2
            else InMemoryEnvironmentService(
                str(default_workspace_dir),
                project_service=project_service,
            )
        )
        legacy_workspace_service = (
            None
            if is_v2
            else WorkspaceRegistryService(
                api_config.state_root,
                default_workspace_dir=default_workspace_dir,
            )
        )
        workspace_service = (
            PersistentWorkspaceFacade(api_config.state_root) if is_v2 else legacy_workspace_service
        )
        app.state.domain_service = DomainService(api_config.state_root, artifact_sha=artifact_sha)
        app.state.project_context_service = ProjectContextService(
            api_config.state_root, artifact_sha=artifact_sha
        )
        app.state.persistent_environment_facade = PersistentEnvironmentFacade(api_config.state_root)
        app.state.task_application_service = TaskApplicationService(
            api_config.state_root, artifact_sha=artifact_sha
        )
        attempt_projection = AttemptProjectionService(api_config.state_root)
        app.state.attempt_projection_service = attempt_projection
        app.state.task_projection_service = TaskProjectionService(
            api_config.state_root,
            attempt_projection=attempt_projection,
        )
        # The legacy ``/projects/{id}/tasks`` compatibility adapter must consume
        # this v2 projection, never the absent legacy AgenticResearcher service.
        app.state.project_task_projection_service = app.state.task_projection_service
        app.state.session_projection_service = SessionProjectionService(
            api_config.state_root,
            attempt_projection=attempt_projection,
        )
        # Project costs are another read-only view over the same Attempt rows.
        app.state.project_cost_projection_service = attempt_projection
        app.state.overview_snapshot_service = OverviewSnapshotService(
            api_config.state_root,
            artifact_sha=artifact_sha,
        )
        app.state.project_service = project_service
        app.state.environment_service = environment_service
        if is_v2:
            if not isinstance(environment_service, PersistentEnvironmentFacade):
                raise RuntimeError("v2 must use the persistent Environment facade")
            app.state.environment_observation_service = PersistentEnvironmentObservationService(
                api_config.state_root, environment_service
            )
        else:
            app.state.environment_observation_service = None
        app.state.resource_monitor_service = ResourceMonitorService(environment_service)
        app.state.workspace_service = workspace_service
        app.state.terminal_session_manager = SessionManager(
            state_root=api_config.state_root,
            environment_service=environment_service,
            tmux_adapter=TmuxAdapter(api_config.state_root),
            default_shell=api_config.terminal_command[0] if api_config.terminal_command else None,
            auth_service=auth_service,
        )
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
        app.state.session_service = (
            None if is_v2 else SessionService(state_root=api_config.state_root)
        )

        if is_v2:
            # A v2 API has one durable Task writer/reader pair; constructing the
            # legacy in-process scheduler would recreate a second write path.
            app.state.agentic_researcher_service = None
        else:
            assert legacy_workspace_service is not None
            agentic_researcher_service = AgenticResearcherService(
                state_root=api_config.state_root,
                workspace_service=legacy_workspace_service,
                auth_service=auth_service,
                observability_reporter=reporter,
            )
            agentic_researcher_service.initialize()
            app.state.agentic_researcher_service = agentic_researcher_service
        app.state.literature_service = LiteratureService(state_root=api_config.state_root)
        app.state.literature_tracking_service = LiteratureTrackingService(
            state_root=api_config.state_root
        )
        app.state.literature_task_saga_service = LiteratureTaskSagaService(
            api_config.state_root,
            artifact_sha=artifact_sha,
        )

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
    from ainrf.development.frontend_faults import build_frontend_dev_fault_middleware

    app.middleware("http")(
        build_frontend_dev_fault_middleware(
            api_config.state_root,
            production=api_config.production,
        )
    )
    app.middleware("http")(
        build_domain_maintenance_middleware(app.state.domain_maintenance_service)
    )
    # This gate must wrap both the durable mutation fence and authentication:
    # an app constructed during an already-active epoch has no Auth SQLite
    # service initialized, so a Bearer-token lookup must not lazily create it
    # before the route can return the maintenance response.
    app.middleware("http")(
        build_maintenance_startup_read_only_middleware(metrics_path=api_config.metrics_path)
    )
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

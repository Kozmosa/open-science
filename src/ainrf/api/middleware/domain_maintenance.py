"""HTTP write barrier for persisted domain maintenance mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_READ_PATHS_WITH_DURABLE_REFRESH = frozenset(
    {
        "/terminal/session",
        "/terminal/session-pairs",
    }
)
_DOMAIN_PREFIXES = (
    # Authentication state, account role/password mutations, user settings,
    # and skill registries live under the backed-up state root.  During a
    # source-stability window they are no less material than a Task mutation:
    # a login failure counter or registry edit must not race a backup/cutover.
    "/auth",
    "/admin",
    "/settings",
    "/skills",
    "/skill-registries",
    "/domain",
    "/projects",
    "/task-edges",
    "/workspaces",
    "/environments",
    "/tasks",
    "/sessions",
    "/literature",
    # File uploads mutate the Workspace / tenant tree that may be selected as
    # a backup source.  Reads remain outside the lease because the method
    # filter below only considers mutations.
    "/files",
    # Terminal session creation/reset/exec mutates durable session bindings
    # and external runtime state.  It must observe the same maintenance epoch
    # as the domain APIs rather than remaining an untracked write side door.
    "/terminal",
)

# A process which starts *after* a maintenance epoch already exists does not
# assemble the normal service graph at all.  Its safe HTTP surface is therefore
# deliberately narrower than an already-running process which later enters
# maintenance: the latter retains its initialized read projections, while the
# former must never route a request into a ``None`` service (or an initializer
# which recreates source state).
_STARTUP_READ_ONLY_API_SEGMENTS = frozenset(
    {
        "admin",
        "auth",
        "client-logs",
        "client-metrics",
        "domain",
        "environments",
        "files",
        "health",
        "literature",
        "metrics",
        "projects",
        "resources",
        "sessions",
        "settings",
        "skill-registries",
        "skills",
        "task-edges",
        "tasks",
        "terminal",
        "token-usage",
        "workspaces",
    }
)


def _strip_api_version_prefix(path: str) -> str:
    """Return the unversioned router path without treating SPA paths as API."""

    for prefix in ("/api", "/v1"):
        if path == prefix:
            return "/"
        if path.startswith(f"{prefix}/"):
            return path[len(prefix) :]
    return path


def is_maintenance_startup_evidence_path(path: str, *, metrics_path: str) -> bool:
    """Whether *path* is safe to expose from an incomplete maintenance app.

    Health, Prometheus metrics, and the capability payload are operational
    evidence used to decide whether a staged restore/cutover can proceed.  The
    capability route is intentionally included even though it normally sits
    behind application authentication: the maintenance-startup variant only
    reports aggregate readiness and cannot instantiate a user-scoped service.
    """

    normalized = _strip_api_version_prefix(path).rstrip("/") or "/"
    configured_metrics = metrics_path.rstrip("/") or "/"
    return (
        normalized in {"/health", "/domain/capabilities"} or path.rstrip("/") == configured_metrics
    )


def _is_startup_read_only_api_path(path: str, *, metrics_path: str) -> bool:
    """Return whether a path belongs to a registered API rather than the SPA.

    We deliberately do not blanket-block every URL: the frontend mount is a
    read-only static fallback and remains usable for an operator viewing a
    maintenance banner.  Only known API namespaces are stopped before they
    can touch missing runtime services.
    """

    if is_maintenance_startup_evidence_path(path, metrics_path=metrics_path):
        return True
    normalized = _strip_api_version_prefix(path)
    if normalized == "/":
        # ``/api`` and ``/v1`` are reserved API roots even though no endpoint
        # is currently mounted there; they must not fall through to SPA HTML.
        return path.rstrip("/") in {"/api", "/v1"}
    first_segment = normalized.lstrip("/").split("/", 1)[0]
    return first_segment in _STARTUP_READ_ONLY_API_SEGMENTS


def _is_domain_mutation(request: Request) -> bool:
    path = request.url.path
    for prefix in ("/api", "/v1"):
        if path == prefix:
            path = "/"
        elif path.startswith(f"{prefix}/"):
            path = path[len(prefix) :]
    if request.method not in _MUTATION_METHODS and not (
        request.method == "GET" and path in _READ_PATHS_WITH_DURABLE_REFRESH
    ):
        return False
    return any(path.startswith(prefix) for prefix in _DOMAIN_PREFIXES)


def build_domain_maintenance_middleware(
    service: DomainMaintenanceService,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def domain_maintenance_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _is_domain_mutation(request):
            return await call_next(request)
        try:
            lease = service.begin_mutation(
                source=f"http:{request.method}:{request.url.path}",
                participant_id=getattr(request.app.state, "domain_api_participant_id", None),
            )
        except MaintenanceModeError:
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "DOMAIN_MAINTENANCE_ACTIVE",
                    "detail": "Domain writes are temporarily paused for maintenance.",
                },
            )
        try:
            service.check_lease(lease)
            response = await call_next(request)
            # A request that began before maintenance may have awaited an
            # external boundary.  Do not report that write as successful once
            # its epoch has crossed; durable services also recheck inside
            # their own transactions before committing.
            service.check_lease(lease)
            return response
        except MaintenanceModeError:
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "DOMAIN_MAINTENANCE_ACTIVE",
                    "detail": "Domain writes are temporarily paused for maintenance.",
                },
            )
        finally:
            service.finish_mutation(lease)

    return domain_maintenance_middleware


def build_maintenance_startup_read_only_middleware(
    *,
    metrics_path: str,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Fence incomplete maintenance-startup API services before auth/routes.

    This is intentionally separate from :func:`build_domain_maintenance_middleware`.
    The durable barrier protects mutations for a fully initialized process
    which subsequently enters maintenance.  A process assembled while the
    epoch is already active has no Project/Task/Auth/Literature service graph;
    allowing even a nominal GET through would either return a misleading 500
    or lazily recreate a source database.  It must be restarted after
    maintenance exits before normal API work can resume.
    """

    async def maintenance_startup_read_only_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not bool(getattr(request.app.state, "maintenance_startup_read_only", False)):
            return await call_next(request)
        path = request.url.path
        if is_maintenance_startup_evidence_path(path, metrics_path=metrics_path):
            return await call_next(request)
        if not _is_startup_read_only_api_path(path, metrics_path=metrics_path):
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "DOMAIN_MAINTENANCE_ACTIVE",
                "detail": (
                    "This API process started during domain maintenance and only exposes "
                    "maintenance evidence. Restart it after maintenance exits."
                ),
            },
        )

    return maintenance_startup_read_only_middleware

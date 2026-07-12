"""HTTP write barrier for persisted domain maintenance mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DOMAIN_PREFIXES = (
    "/projects",
    "/task-edges",
    "/workspaces",
    "/environments",
    "/tasks",
    "/sessions",
    "/literature",
)


def _is_domain_mutation(request: Request) -> bool:
    if request.method not in _MUTATION_METHODS:
        return False
    path = request.url.path
    for prefix in ("/api", "/v1"):
        if path == prefix:
            path = "/"
        elif path.startswith(f"{prefix}/"):
            path = path[len(prefix) :]
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
            service.check_lease(lease)
        except MaintenanceModeError:
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "DOMAIN_MAINTENANCE_ACTIVE",
                    "detail": "Domain writes are temporarily paused for maintenance.",
                },
            )
        try:
            return await call_next(request)
        finally:
            service.finish_mutation(lease)

    return domain_maintenance_middleware

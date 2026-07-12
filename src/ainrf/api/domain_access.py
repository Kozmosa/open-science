"""Authorization guards for v2 runtime adapters.

The persistent runtime facades deliberately only translate durable control
plane rows into legacy runtime shapes.  They do not carry a request actor, so
routes that use them must establish v2 visibility before touching a terminal
or file-system capability.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from ainrf.domain import DomainService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import DomainModelMode


def v2_domain_service(request: HTTPConnection) -> DomainService | None:
    """Return the ready v2 service, or ``None`` while legacy remains active.

    A process configured for v2 must not silently fall back to a facade-only
    read when the cutover fuse is unavailable: that would bypass authorization
    at precisely the point where the durable control plane is authoritative.
    """

    config = getattr(request.app.state, "api_config", None)
    if config is None or config.domain_model_mode is not DomainModelMode.V2:
        return None
    service = getattr(request.app.state, "domain_service", None)
    if not isinstance(service, DomainService) or not service.v2_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain v2 cutover is not ready",
        )
    return service


def require_v2_active_environment(
    request: HTTPConnection,
    user: dict[str, object],
    environment_id: str,
) -> None:
    """Require a visible, active durable Environment before runtime access."""

    service = v2_domain_service(request)
    if service is None:
        return
    try:
        service.environment(environment_id, user, include_disabled=False)
    except DomainNotFoundError as exc:
        # Environment grants are part of visibility.  Do not disclose whether
        # an ungranted ID exists or has merely been disabled.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Environment not found",
        ) from exc


def require_v2_workspace_execution_owner(
    request: HTTPConnection,
    user: dict[str, object],
    workspace_id: str,
) -> dict[str, object] | None:
    """Require owner-level access to a Workspace used for runtime I/O.

    ``DomainService.workspace`` preserves private-resource visibility: a
    non-owner cannot discover a Workspace ID.  An administrator may view that
    row, but must not gain Linux tenant filesystem or execution rights, so the
    second check deliberately rejects that case with 403.
    """

    service = v2_domain_service(request)
    if service is None:
        return None
    try:
        workspace = service.workspace(workspace_id, user)
    except DomainNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    if workspace.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.get("owner_user_id") != user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission is required",
        )
    return workspace

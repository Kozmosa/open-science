"""Authorization guards for authoritative domain runtime adapters.

The persistent runtime facades deliberately only translate durable control
plane rows into runtime shapes.  They do not carry a request actor, so
routes that use them must establish v2 visibility before touching a terminal
or file-system capability.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_telemetry import record_permission_denied


@runtime_checkable
class RuntimeDomainReader(Protocol):
    """Small domain read Interface required by runtime transport Modules."""

    def v2_ready(self) -> bool: ...

    def environment(
        self,
        environment_id: str,
        user: dict[str, object],
        *,
        include_disabled: bool = False,
    ) -> dict[str, object]: ...

    def workspace(self, workspace_id: str, user: dict[str, object]) -> dict[str, object]: ...


def v2_domain_service(request: HTTPConnection) -> RuntimeDomainReader:
    """Return the ready authoritative Domain Module or fail closed."""

    service = getattr(request.app.state, "domain_service", None)
    if not isinstance(service, RuntimeDomainReader) or not service.v2_ready():
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
) -> dict[str, object]:
    """Require owner-level access to a Workspace used for runtime I/O.

    ``DomainService.workspace`` preserves private-resource visibility: a
    non-owner cannot discover a Workspace ID.  An administrator may view that
    row, but must not gain Linux tenant filesystem or execution rights, so the
    second check deliberately rejects that case with 403.
    """

    service = v2_domain_service(request)
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
        config = getattr(request.app.state, "api_config", None)
        state_root = getattr(config, "state_root", None)
        user_id = user.get("id")
        record_permission_denied(
            resource="workspace",
            reason="tenant_owner_required",
            user_id=user_id if isinstance(user_id, str) else None,
            workspace_id=workspace_id,
            state_root=state_root,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission is required",
        )
    return workspace

"""Authorization guards for authoritative domain runtime adapters.

The persistent runtime facades deliberately only translate durable control
plane rows into runtime shapes.  They do not carry a request actor, so
routes that use them must establish v2 visibility before touching a terminal
or file-system capability.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from ainrf.domain.environment_access import has_active_environment_execution_grant
from ainrf.domain.interfaces import EnvironmentReader, WorkspaceReader
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_telemetry import record_permission_denied


_ENVIRONMENT_EXECUTION_GRANT_DETAIL = "Environment execution grant is required"


def _environment_module(request: HTTPConnection) -> EnvironmentReader:
    service = getattr(request.app.state, "environment_module", None)
    if not isinstance(service, EnvironmentReader) or not service.ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain is not ready for current reads",
        )
    return service


def v2_environment_module(request: HTTPConnection) -> EnvironmentReader:
    """Return the ready Environment application Interface."""

    return _environment_module(request)


def _workspace_module(request: HTTPConnection) -> WorkspaceReader:
    service = getattr(request.app.state, "workspace_module", None)
    if not isinstance(service, WorkspaceReader) or not service.ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain is not ready for current reads",
        )
    return service


def require_v2_active_environment(
    request: HTTPConnection,
    user: dict[str, object],
    environment_id: str,
) -> None:
    """Require a visible, active durable Environment before runtime access."""

    service = _environment_module(request)
    try:
        service.environment(environment_id, user, include_disabled=False)
    except DomainNotFoundError as exc:
        # Environment grants are part of visibility.  Do not disclose whether
        # an ungranted ID exists or has merely been disabled.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Environment not found",
        ) from exc


def _auth_db_path(request: HTTPConnection) -> Path | None:
    config = getattr(request.app.state, "api_config", None)
    state_root = getattr(config, "state_root", None)
    if not isinstance(state_root, Path):
        return None
    return state_root / "runtime" / "auth.sqlite3"


def _state_root(request: HTTPConnection) -> Path | None:
    config = getattr(request.app.state, "api_config", None)
    state_root = getattr(config, "state_root", None)
    return state_root if isinstance(state_root, Path) else None


def has_v2_environment_execution_grant(
    request: HTTPConnection,
    user: dict[str, object],
    environment_id: str,
) -> bool:
    """Return only the explicit active grant for a visible runtime identity.

    This helper intentionally has no visibility or telemetry behavior.  It is
    used by the all-environments session-pair filter, where a denied row must
    simply be omitted without disclosing it or turning a list into a 403.
    The actual SQLite read remains centralized in ``environment_access``.
    """

    user_id = user.get("id")
    auth_db_path = _auth_db_path(request)
    if not isinstance(user_id, str) or not user_id or auth_db_path is None:
        return False
    return has_active_environment_execution_grant(
        auth_db_path,
        environment_id=environment_id,
        user_id=user_id,
    )


def reject_v2_environment_execution_grant(
    request: HTTPConnection,
    *,
    user_id: str | None,
    environment_id: str,
) -> NoReturn:
    """Record and raise the canonical denial for a missing execution grant.

    Capability adapters such as the terminal attachment WebSocket may have a
    durable user ID but no request actor dict when their auth authority cannot
    be read.  They still use this same denial seam so a visible runtime denial
    has one status, detail, and permission telemetry contract.
    """

    record_permission_denied(
        resource="environment",
        reason="environment_grant_required",
        user_id=user_id,
        environment_id=environment_id,
        state_root=_state_root(request),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_ENVIRONMENT_EXECUTION_GRANT_DETAIL,
    )


def require_v2_environment_execution_grant(
    request: HTTPConnection,
    user: dict[str, object],
    environment_id: str,
) -> None:
    """Require visibility and an explicit active Environment execution grant.

    Visibility is checked first so an unknown, disabled, or otherwise
    invisible Environment remains a 404.  Ownership and administrator role
    only provide registry visibility; neither is an execution grant.  Missing,
    corrupt, or otherwise unreadable auth authority therefore fails closed as
    one bounded permission denial and a 403.
    """

    require_v2_active_environment(request, user, environment_id)
    if has_v2_environment_execution_grant(request, user, environment_id):
        return

    user_id = user.get("id")
    reject_v2_environment_execution_grant(
        request,
        user_id=user_id if isinstance(user_id, str) else None,
        environment_id=environment_id,
    )


def require_v2_workspace_execution_owner(
    request: HTTPConnection,
    user: dict[str, object],
    workspace_id: str,
) -> dict[str, object]:
    """Require owner-level access to a Workspace used for runtime I/O.

    The Workspace Module preserves private-resource visibility: a
    non-owner cannot discover a Workspace ID.  An administrator may view that
    row, but must not gain Linux tenant filesystem or execution rights, so the
    second check deliberately rejects that case with 403.
    """

    service = _workspace_module(request)
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

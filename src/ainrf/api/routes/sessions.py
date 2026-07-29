# src/ainrf/api/routes/sessions.py
"""Session and attempt API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.auth.permissions import get_current_user
from ainrf.api.schemas import (
    AttemptListResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from ainrf.domain import DomainPermissionError, SessionProjectionService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_telemetry import record_legacy_write_attempt

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _projection(request: Request) -> SessionProjectionService:
    service = getattr(request.app.state, "session_projection_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Session domain v2 is not ready")
    if not isinstance(service, SessionProjectionService):
        raise HTTPException(status_code=500, detail="Session projection service is invalid")
    return service


def _sessions_read_only(request: Request) -> HTTPException:
    """Sessions are retained as an API projection, never a v2 write model."""

    record_legacy_write_attempt(
        source="legacy_session",
        state_root=request.app.state.api_config.state_root,
    )
    return HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Sessions are a read-only Task Attempt projection in v2",
        headers={"Allow": "GET"},
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> SessionListResponse:
    user = get_current_user(request)
    projection = _projection(request)
    try:
        items, total, has_more, next_cursor = projection.list_sessions(
            project_id=project_id, user=user, status=status, cursor=cursor, limit=limit
        )
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return SessionListResponse.model_validate(
        {
            "items": items,
            "total": total if cursor is None else None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(request: Request) -> SessionResponse:
    raise _sessions_read_only(request)


@router.get("/batch-detail")
async def get_sessions_batch_detail(
    request: Request,
    ids: str = Query(..., description="Comma-separated session IDs"),
):
    session_ids = [sid.strip() for sid in ids.split(",") if sid.strip()]
    if not session_ids:
        return {"items": {}}
    if len(session_ids) > 200:
        raise HTTPException(status_code=400, detail="Too many IDs (max 200)")
    user = get_current_user(request)
    projection = _projection(request)
    return {"items": projection.batch_details(session_ids, user)}


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    user = get_current_user(request)
    projection = _projection(request)
    try:
        session, attempts = projection.get_session(session_id, user)
    except (DomainPermissionError, LookupError) as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return SessionDetailResponse.model_validate({**session, "attempts": attempts})


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, request: Request) -> SessionResponse:
    raise _sessions_read_only(request)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    raise _sessions_read_only(request)


@router.get("/{session_id}/attempts", response_model=AttemptListResponse)
async def list_attempts(session_id: str, request: Request) -> AttemptListResponse:
    user = get_current_user(request)
    projection = _projection(request)
    try:
        _session, attempts = projection.get_session(session_id, user)
    except (DomainPermissionError, LookupError) as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return AttemptListResponse.model_validate({"items": attempts})

# src/ainrf/api/routes/sessions.py
"""Session and attempt API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.auth.permissions import check_resource_ownership, get_current_user, is_admin
from ainrf.api.schemas import (
    AttemptListResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from ainrf.sessions import SessionService
from ainrf.domain import DomainPermissionError, SessionProjectionService
from ainrf.domain_control import DomainModelMode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _get_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="session service not initialized")
    return service


def _projection(request: Request) -> SessionProjectionService | None:
    domain = getattr(request.app.state, "domain_service", None)
    service = getattr(request.app.state, "session_projection_service", None)
    if (
        domain is None
        or service is None
        or request.app.state.api_config.domain_model_mode is not DomainModelMode.V2
        or not domain.v2_ready()
    ):
        return None
    return service


def _translate_error(exc: Exception) -> HTTPException:
    name = exc.__class__.__name__
    if name == "SessionNotFoundError":
        return HTTPException(status_code=404, detail=str(exc))
    if name == "AttemptNotFoundError":
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected session error")


def _v2_sessions_read_only() -> HTTPException:
    """Sessions are retained as an API projection, never a v2 write model."""

    return HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Sessions are a read-only Task Attempt projection in v2",
        headers={"Allow": "GET"},
    )


def _serialize_session(s) -> dict[str, Any]:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "title": s.title,
        "status": s.status.value if hasattr(s.status, "value") else s.status,
        "task_count": s.task_count,
        "total_duration_ms": s.total_duration_ms,
        "total_cost_usd": s.total_cost_usd,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _serialize_attempt(a) -> dict[str, Any]:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "task_id": a.task_id,
        "parent_attempt_id": a.parent_attempt_id,
        "attempt_seq": a.attempt_seq,
        "intervention_reason": a.intervention_reason,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "started_at": a.started_at,
        "finished_at": a.finished_at,
        "duration_ms": a.duration_ms,
        "token_usage_json": a.token_usage_json,
        "created_at": a.created_at,
    }


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
    if projection is not None:
        items, total, has_more, next_cursor = projection.list_sessions(
            project_id=project_id,
            owner_user_id=None if is_admin(user) else str(user["id"]),
            status=status,
            cursor=cursor,
            limit=limit,
        )
        return SessionListResponse.model_validate(
            {
                "items": items,
                "total": total if cursor is None else None,
                "has_more": has_more,
                "next_cursor": next_cursor,
            }
        )
    service = _get_service(request)
    try:
        if is_admin(user):
            items, total, has_more, next_cursor = service.list_sessions_cursor(
                project_id=project_id,
                status=status,
                cursor=cursor,
                limit=limit,
            )
        else:
            items, total, has_more, next_cursor = service.list_sessions_cursor(
                project_id=project_id,
                status=status,
                cursor=cursor,
                limit=limit,
                owner_user_id=user["id"],
            )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionListResponse.model_validate(
        {
            "items": [_serialize_session(s) for s in items],
            "total": total if cursor is None else None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreateRequest, request: Request) -> SessionResponse:
    if _projection(request) is not None:
        raise _v2_sessions_read_only()
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.create_session(
            project_id=payload.project_id, title=payload.title, owner_user_id=user["id"]
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


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
    if projection is not None:
        return {"items": projection.batch_details(session_ids, user)}
    service = _get_service(request)
    if is_admin(user):
        details = service.get_sessions_batch_detail(session_ids)
    else:
        details = service.get_sessions_batch_detail(session_ids, owner_user_id=user["id"])
    return {"items": details}


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    user = get_current_user(request)
    projection = _projection(request)
    if projection is not None:
        try:
            session, attempts = projection.get_session(session_id, user)
        except (DomainPermissionError, LookupError) as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return SessionDetailResponse.model_validate({**session, "attempts": attempts})
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        check_resource_ownership(user, s.owner_user_id)
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionDetailResponse.model_validate(
        {
            **_serialize_session(s),
            "attempts": [_serialize_attempt(a) for a in attempts],
        }
    )


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str, payload: SessionUpdateRequest, request: Request
) -> SessionResponse:
    if _projection(request) is not None:
        raise _v2_sessions_read_only()
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        check_resource_ownership(user, s.owner_user_id)
        s = service.update_session(session_id, title=payload.title, status=payload.status)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    if _projection(request) is not None:
        raise _v2_sessions_read_only()
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        check_resource_ownership(user, s.owner_user_id)
        service.delete_session(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return Response(status_code=204)


@router.get("/{session_id}/attempts", response_model=AttemptListResponse)
async def list_attempts(session_id: str, request: Request) -> AttemptListResponse:
    user = get_current_user(request)
    projection = _projection(request)
    if projection is not None:
        try:
            _session, attempts = projection.get_session(session_id, user)
        except (DomainPermissionError, LookupError) as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return AttemptListResponse.model_validate({"items": attempts})
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        check_resource_ownership(user, s.owner_user_id)
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return AttemptListResponse.model_validate(
        {
            "items": [_serialize_attempt(a) for a in attempts],
        }
    )

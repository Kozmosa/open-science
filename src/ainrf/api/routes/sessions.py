# src/ainrf/api/routes/sessions.py
"""Session and attempt API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.auth.permissions import check_resource_owner, get_current_user, is_admin
from ainrf.api.schemas import (
    AttemptListResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from ainrf.sessions import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _get_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="session service not initialized")
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
) -> SessionListResponse:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        if is_admin(user):
            sessions = service.list_sessions(project_id=project_id, status=status)
        else:
            sessions = service.list_sessions(project_id=project_id, status=status, owner_user_id=user["id"])
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionListResponse.model_validate({
        "items": [_serialize_session(s) for s in sessions],
    })


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest, request: Request
) -> SessionResponse:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.create_session(project_id=payload.project_id, title=payload.title, owner_user_id=user["id"])
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        if not check_resource_owner(user, s.owner_user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionDetailResponse.model_validate({
        **_serialize_session(s),
        "attempts": [_serialize_attempt(a) for a in attempts],
    })


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str, payload: SessionUpdateRequest, request: Request
) -> SessionResponse:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        if not check_resource_owner(user, s.owner_user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        s = service.update_session(
            session_id, title=payload.title, status=payload.status
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        if not check_resource_owner(user, s.owner_user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        service.delete_session(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return Response(status_code=204)


@router.get("/{session_id}/attempts", response_model=AttemptListResponse)
async def list_attempts(
    session_id: str, request: Request
) -> AttemptListResponse:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        if not check_resource_owner(user, s.owner_user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return AttemptListResponse.model_validate({
        "items": [_serialize_attempt(a) for a in attempts],
    })

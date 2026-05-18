"""Admin API routes — user and access management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    AdminPasswordResetRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
)
from ainrf.auth import AuthService
from ainrf.auth.permissions import get_current_user, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


def _serialize_user(u) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role.value if hasattr(u.role, "value") else u.role,
        "status": u.status.value if hasattr(u.status, "value") else u.status,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
    }


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(request: Request) -> AdminUserListResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    users = service.list_users()
    return AdminUserListResponse.model_validate({
        "items": [_serialize_user(u) for u in users],
    })


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str, payload: AdminUserUpdateRequest, request: Request
) -> AdminUserResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    try:
        if payload.status == "active":
            u = service.activate_user(user_id)
        elif payload.status == "disabled":
            u = service.disable_user(user_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid status")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminUserResponse.model_validate(_serialize_user(u))


@router.put("/users/{user_id}/password", status_code=204)
async def reset_password(
    user_id: str, payload: AdminPasswordResetRequest, request: Request
):
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    try:
        service.reset_password(user_id, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None

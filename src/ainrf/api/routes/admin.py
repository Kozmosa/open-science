from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    EnvironmentAccessListResponse,
    EnvironmentAccessRequest,
    EnvironmentAccessResponse,
)
from ainrf.auth.permissions import get_current_user, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_service(request: Request):
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


@router.get("/environments/{env_id}/access", response_model=EnvironmentAccessListResponse)
async def list_env_access(env_id: str, request: Request) -> EnvironmentAccessListResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    users = service.list_users()
    items = []
    for u in users:
        env_ids = service.get_user_environment_ids(u.id)
        if env_id in env_ids:
            items.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "max_concurrent_tasks": None,
                }
            )
    return EnvironmentAccessListResponse.model_validate({"items": items})


@router.put(
    "/environments/{env_id}/access", response_model=EnvironmentAccessResponse, status_code=201
)
async def grant_env_access(
    env_id: str, payload: EnvironmentAccessRequest, request: Request
) -> EnvironmentAccessResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    service.grant_environment(
        env_id=env_id,
        user_id=payload.user_id,
        max_tasks=payload.max_concurrent_tasks,
        granted_by=user["id"],
    )
    return EnvironmentAccessResponse.model_validate(
        {
            "user_id": payload.user_id,
            "username": "",
            "display_name": "",
            "max_concurrent_tasks": payload.max_concurrent_tasks,
        }
    )


@router.delete("/environments/{env_id}/access/{user_id}", status_code=204)
async def revoke_env_access(env_id: str, user_id: str, request: Request):
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    service.revoke_environment(env_id, user_id)
    return None

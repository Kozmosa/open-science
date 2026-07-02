"""Authentication API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

_LOG = logging.getLogger(__name__)
from ainrf.api.routes.metrics import inc_counter

from ainrf.api.config import ApiConfig
from ainrf.api.schemas import (
    ChangePasswordRequest,
    AccessTokenResponse,
    AuthTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserInfoResponse,
)
from ainrf.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
_ACCESS_COOKIE = "openscience_access_token"
_LEGACY_ACCESS_COOKIE = "ainrf_access_token"




def _get_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request) -> dict:
    service = _get_service(request)
    api_config: ApiConfig = request.app.state.api_config
    if not api_config.public_registration_enabled:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    try:
        user = service.register(
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
        )
    except Exception as exc:
        detail = str(exc)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    # Create a tenant-scoped workspace entry for the new user.
    workspace_service = getattr(request.app.state, "workspace_service", None)
    if workspace_service is not None:
        from ainrf.workspaces import WorkspaceRegistryService

        assert isinstance(workspace_service, WorkspaceRegistryService)
        workspace_service.ensure_tenant_workspace(username=payload.username)

    # Provision the per-user default project alongside the tenant workspace.
    project_service = getattr(request.app.state, "project_service", None)
    if project_service is not None:
        from ainrf.projects import ProjectRegistryService

        assert isinstance(project_service, ProjectRegistryService)
        project_service.get_or_create_user_default(
            username=payload.username, owner_user_id=user.id
        )

    _ = user  # user created; admin approval is still required for login
    return {"message": "Registration submitted. Awaiting admin approval."}


def _set_access_cookies(response: Response, access_token: str, *, secure: bool) -> None:
    for cookie_name in (_ACCESS_COOKIE, _LEGACY_ACCESS_COOKIE):
        response.set_cookie(
            key=cookie_name,
            value=access_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=3600,
            path="/",
        )


def _delete_access_cookies(response: Response) -> None:
    for cookie_name in (_ACCESS_COOKIE, _LEGACY_ACCESS_COOKIE):
        response.delete_cookie(key=cookie_name, path="/")


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: LoginRequest, request: Request) -> Response:
    service = _get_service(request)
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    ip = client_ip or "unknown"
    try:
        service.check_login_lockout(username=payload.username, ip_address=ip)
    except service.AccountLockedError as exc:
        inc_counter("ainrf_auth_login_failed_total", {"reason": "locked"})
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        _LOG.exception("login_lockout_check_failed username=%s", payload.username)
        raise HTTPException(
            status_code=503, detail="Authentication service temporarily unavailable"
        ) from exc
    try:
        result = service.login(username=payload.username, password=payload.password)
    except Exception as exc:
        try:
            service.record_login_attempt(username=payload.username, ip_address=ip, success=False)
        except Exception:
            _LOG.exception("record_login_attempt_failed username=%s", payload.username)
        inc_counter("ainrf_auth_login_failed_total", {"reason": "invalid_credentials"})
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        service.record_login_attempt(username=payload.username, ip_address=ip, success=True)
    except Exception:
        _LOG.exception("record_login_attempt_failed username=%s", payload.username)
    inc_counter("ainrf_auth_login_success_total")
    body = AuthTokenResponse.model_validate(result)
    response = Response(
        content=body.model_dump_json(),
        media_type="application/json",
        status_code=200,
    )
    # Set session cookie so nginx auth_request on /grafana, /prometheus, /litefuse can authenticate.
    # HttpOnly for XSS protection; SameSite=Lax for CSRF; Secure in production.
    is_secure = request.url.scheme == "https"
    _set_access_cookies(response, result["access_token"], secure=is_secure)
    return response


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, request: Request) -> Response:
    service = _get_service(request)
    try:
        result = service.refresh(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    body = AccessTokenResponse.model_validate(result)
    response = Response(
        content=body.model_dump_json(),
        media_type="application/json",
        status_code=200,
    )
    is_secure = request.url.scheme == "https"
    _set_access_cookies(response, result["access_token"], secure=is_secure)
    return response


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest, request: Request) -> Response:
    service = _get_service(request)
    try:
        service.logout(payload.refresh_token)
    except Exception:
        pass
    response = Response(status_code=204)
    _delete_access_cookies(response)
    return response


@router.get("/me", response_model=UserInfoResponse)
async def me(request: Request) -> UserInfoResponse:
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserInfoResponse.model_validate(user)


@router.get("/check")
async def check(request: Request) -> Response:
    """Auth check for nginx auth_request (Grafana reverse proxy).


    Only AINRF admins are allowed. Returns 200 with identity headers
    for admins, 401 for unauthenticated, 403 for non-admin users.
    """
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return Response(
        status_code=200,
        headers={
            "X-Remote-User": user["id"],
            "X-Remote-User-Role": "admin",
        },
    )

@router.post("/change-password", status_code=204)
async def change_password(payload: ChangePasswordRequest, request: Request):
    """Change password. Requires current password. Clears must_change_password flag."""
    service = _get_service(request)
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        service.change_password(user["id"], payload.old_password, payload.new_password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None

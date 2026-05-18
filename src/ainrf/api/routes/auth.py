"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    AccessTokenResponse,
    AuthTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserInfoResponse,
)
from ainrf.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request) -> dict:
    service = _get_service(request)
    try:
        service.register(
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
        )
    except Exception as exc:
        detail = str(exc)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"message": "Registration submitted. Awaiting admin approval."}


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: LoginRequest, request: Request) -> AuthTokenResponse:
    service = _get_service(request)
    try:
        result = service.login(username=payload.username, password=payload.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AuthTokenResponse.model_validate(result)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, request: Request) -> AccessTokenResponse:
    service = _get_service(request)
    try:
        result = service.refresh(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AccessTokenResponse.model_validate(result)


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest, request: Request):
    service = _get_service(request)
    try:
        service.logout(payload.refresh_token)
    except Exception:
        pass
    return None


@router.get("/me", response_model=UserInfoResponse)
async def me(request: Request) -> UserInfoResponse:
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserInfoResponse.model_validate(user)

"""JWT authentication middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.auth.service import AuthService

_EXEMPT_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/v1/models",
    "/v1/messages",
)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _EXEMPT_PATH_PREFIXES)


def build_jwt_auth_middleware(
    auth_service: AuthService,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def jwt_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _is_exempt(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        token = auth_header[7:]
        try:
            user = auth_service.get_user_by_token(token)
        except Exception:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.current_user = user
        return await call_next(request)

    return jwt_auth_middleware

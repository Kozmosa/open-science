"""JWT authentication middleware."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.api.config import ApiConfig
from ainrf.auth.service import AuthService

_EXEMPT_PATH_PREFIXES = (
    "/health",
    "/v1/health",
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
    api_config: ApiConfig,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def jwt_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _is_exempt(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                user = auth_service.get_user_by_token(token)
            except asyncio.CancelledError:
                raise
            except Exception:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            request.state.current_user = user
            return await call_next(request)

        # Fallback: API key in query string (needed for native EventSource/SSE)
        api_key = request.query_params.get("api_key")
        if api_key and api_config.verify_api_key(api_key):
            request.state.current_user = {
                "id": "api-key-user",
                "username": "api-key",
                "role": "admin",
                "display_name": "API Key",
            }
            return await call_next(request)

        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return jwt_auth_middleware

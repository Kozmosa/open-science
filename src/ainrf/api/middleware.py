from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.api.config import ApiConfig

_EXEMPT_PATH_PREFIXES = (
    "/health",
    "/v1/health",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/v1/models",
    "/v1/messages",
)


def build_api_key_middleware(
    api_config: ApiConfig,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def api_key_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith(_EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not api_config.verify_api_key(api_key):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)

    return api_key_middleware

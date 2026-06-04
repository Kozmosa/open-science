"""Authentication, IP allowlist, and production-mode security middleware."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.api.config import ApiConfig
from ainrf.auth.service import AuthService

_EXEMPT_PATH_PREFIXES = (
    "/health",
    "/v1/health",
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
)

# Paths exempt in dev mode only (never in production).
_DEV_EXEMPT_PATH_PREFIXES = (
    "/docs",
    "/openapi.json",
    "/redoc",
    "/v1/models",
    "/v1/messages",
)


def _is_exempt(path: str, production: bool) -> bool:
    if any(path.startswith(p) for p in _EXEMPT_PATH_PREFIXES):
        return True
    if production:
        return False
    return any(path.startswith(p) for p in _DEV_EXEMPT_PATH_PREFIXES)


def _parse_cidrs(raw: tuple[str, ...]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse CIDR strings into network objects. Invalid entries are silently skipped."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in raw:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return networks


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For from a trusted reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


def build_ip_allowlist_middleware(
    allowed_cidrs: tuple[str, ...],
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Return middleware that rejects requests from IPs outside the allowed CIDRs."""
    networks = _parse_cidrs(allowed_cidrs)

    async def ip_allowlist_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not networks:
            # No CIDRs configured — allow all (rely on network-level firewall).
            return await call_next(request)

        client_ip = _client_ip(request)
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        if not any(addr in net for net in networks):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        return await call_next(request)

    return ip_allowlist_middleware


def build_jwt_auth_middleware(
    auth_service: AuthService,
    api_config: ApiConfig,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def jwt_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _is_exempt(request.url.path, api_config.production):
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
            request.state.auth_scheme = "bearer"
            return await call_next(request)

        # Fallback: API key in query string (needed for native EventSource/SSE)
        # API keys are granted restricted non-admin role for security
        api_key = request.query_params.get("api_key")
        if api_key and api_config.verify_api_key(api_key):
            request.state.current_user = {
                "id": "api-key-user",
                "username": "api-key",
                "role": "user",  # API keys get user role, not admin
                "display_name": "API Key",
            }
            request.state.auth_scheme = "api_key"
            return await call_next(request)

        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return jwt_auth_middleware


def build_request_size_middleware(
    max_bytes: int,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Reject requests with Content-Length exceeding the limit."""
    async def request_size_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > max_bytes:
                return JSONResponse(
                    {"detail": f"Request body too large (max {max_bytes // (1024 * 1024)} MB)"},
                    status_code=413,
                )
        return await call_next(request)

    return request_size_middleware

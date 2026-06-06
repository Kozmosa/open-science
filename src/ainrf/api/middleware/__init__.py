"""Authentication, IP allowlist, production-mode, and concurrency security middleware."""

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
    # Frontend static files (SPA assets, no auth needed)
    "/assets/",
    "/favicon",
    "/vite.svg",
    "/logo",
)

# Known API route prefixes. Paths NOT matching these are SPA routes
# served by the frontend catch-all and do not require auth.
_API_PATH_PREFIXES = (
    "/health",
    "/v1/",
    "/auth/",
    "/tasks",
    "/sessions",
    "/terminal",
    "/files",
    "/workspaces",
    "/projects",
    "/environments",
    "/resources",
    "/settings",
    "/literature",
    "/skills",
    "/skill-registries",
    "/admin",
    "/metrics",
    "/token-usage",
    "/task-edges",
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
    # SPA routes (non-API paths) are served by the frontend catch-all and
    # do not require backend auth — the frontend handles its own auth flow.
    if not any(path.startswith(p) for p in _API_PATH_PREFIXES):
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


def _client_ip(
    request: Request,
    trusted_cidrs: tuple[str, ...] | None = None,
) -> str:
    """Extract client IP, respecting X-Forwarded-For from a trusted reverse proxy."""
    direct_ip = request.client.host if request.client else "0.0.0.0"
    if trusted_cidrs:
        networks = _parse_cidrs(trusted_cidrs)
        try:
            addr = ipaddress.ip_address(direct_ip)
            if any(
                net.supernet_of(
                    ipaddress.ip_network(f"{addr}/128" if addr.version == 6 else f"{addr}/32")
                )
                for net in networks
            ):
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    return forwarded.split(",")[0].strip()
        except ValueError:
            pass
    elif request.headers.get("x-forwarded-for"):
        # No trusted CIDRs configured — legacy behavior for dev
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return direct_ip


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


def build_concurrency_limit_middleware(
    max_concurrent: int,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Reject requests when the server is already handling max_concurrent in-flight requests.

    Uses an asyncio.Semaphore so the limit is enforced across the single event loop.
    Set max_concurrent=0 to disable (unlimited).
    """
    semaphore: asyncio.Semaphore | None = None

    async def concurrency_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        nonlocal semaphore
        if max_concurrent <= 0:
            return await call_next(request)
        if semaphore is None:
            semaphore = asyncio.Semaphore(max_concurrent)
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=5.0)
        except TimeoutError:
            return JSONResponse(
                {"detail": "Server is busy. Please retry later."},
                status_code=503,
            )
        try:
            return await call_next(request)
        finally:
            semaphore.release()

    return concurrency_limit_middleware

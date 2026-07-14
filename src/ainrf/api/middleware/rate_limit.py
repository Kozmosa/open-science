"""Per-user / per-IP rate-limiting middleware.

Implements a sliding-window rate limiter using in-memory token buckets.
When enabled, rejects requests exceeding the configured rate with a 429
response and a ``Retry-After`` header.

Configuration (environment variables):
  ``AINRF_RATE_LIMIT_ENABLED`` — set to ``"true"`` to enable (default: off).
  ``AINRF_RATE_LIMIT_REQUESTS_PER_MINUTE`` — max requests per user/IP per minute
     (default: 60).
  ``AINRF_RATE_LIMIT_BURST_SIZE`` — additional burst allowance (default: 10).

Bucket entries for inactive clients are cleaned up periodically to prevent
memory growth.
"""

from __future__ import annotations

import logging
import os
import time as _time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_LOG = logging.getLogger(__name__)

# Default configuration — overridable via env vars.
_DEFAULT_REQUESTS_PER_MINUTE = 60
_DEFAULT_BURST_SIZE = 10
_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


class _TokenBucket:
    """Simple token bucket for a single client."""

    __slots__ = ("tokens", "last_refill", "burst_size", "rate")

    def __init__(self, burst_size: int, rate_per_second: float) -> None:
        self.tokens = float(burst_size)
        self.burst_size = burst_size
        self.rate = rate_per_second
        self.last_refill = _time.monotonic()

    def consume(self, now: float | None = None) -> bool:
        """Try to consume one token.  Returns ``True`` if allowed."""
        if now is None:
            now = _time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst_size, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def expired(self) -> bool:
        """Return True if this bucket hasn't been used recently."""
        return _time.monotonic() - self.last_refill > _CLEANUP_INTERVAL_SECONDS


# In-memory bucket store: key → _TokenBucket.
_buckets: dict[str, _TokenBucket] = {}
_last_cleanup = _time.monotonic()


def _cleanup_expired() -> None:
    """Periodically remove buckets for inactive clients."""
    global _last_cleanup
    now = _time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup = now
    expired = [k for k, b in _buckets.items() if b.expired]
    for k in expired:
        _buckets.pop(k, None)


def _read_config() -> tuple[bool, int, int]:
    """Read rate-limit configuration from env vars."""
    enabled = os.environ.get("AINRF_RATE_LIMIT_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
    rpm = int(
        os.environ.get("AINRF_RATE_LIMIT_REQUESTS_PER_MINUTE", str(_DEFAULT_REQUESTS_PER_MINUTE))
    )
    burst = int(os.environ.get("AINRF_RATE_LIMIT_BURST_SIZE", str(_DEFAULT_BURST_SIZE)))
    return enabled, rpm, burst


def build_rate_limit_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Return a rate-limiting middleware (disabled by default).

    Rate limit is applied per authenticated user ID, or per client IP if
    unauthenticated.
    """
    enabled, rpm, burst = _read_config()

    if not enabled:

        async def _passthrough(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            return await call_next(request)

        return _passthrough

    rate_per_second = rpm / 60.0
    _LOG.info(
        "rate_limit_enabled",
        extra={
            "requests_per_minute": rpm,
            "burst_size": burst,
            "rate_per_second": round(rate_per_second, 2),
        },
    )

    async def rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        _cleanup_expired()

        # Identify client by authenticated user ID, or fall back to client IP.
        user = getattr(request.state, "current_user", None)
        if user and isinstance(user, dict):
            client_key = f"user:{user.get('id', 'unknown')}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            client_key = f"ip:{client_ip}"

        bucket = _buckets.get(client_key)
        if bucket is None:
            bucket = _TokenBucket(burst_size=burst, rate_per_second=rate_per_second)
            _buckets[client_key] = bucket

        if bucket.consume():
            return await call_next(request)

        from ainrf.api.routes.sla_metrics import rate_limited
        from ainrf.api.routes.metrics import route_template_for_request

        route = route_template_for_request(request)
        rate_limited("user_quota", route)

        _LOG.warning(
            "rate_limited",
            extra={
                "client_scope": "authenticated" if user else "anonymous",
                "route": route,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "RATE_LIMITED",
                "message": "Too many requests. Please slow down.",
                "retry_after_seconds": 60,
            },
            headers={"Retry-After": "60"},
        )

    return rate_limit_middleware

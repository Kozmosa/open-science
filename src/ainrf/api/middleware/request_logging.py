"""HTTP request/response logging middleware.

Logs every request with method, stable route template, status, duration, and
the request_id set by ``request_context`` middleware.  Slow requests and 5xx
responses are elevated to WARNING / ERROR so they stand out in production logs.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from starlette.requests import Request
from starlette.responses import Response

from ainrf.api.routes.metrics import route_template_for_request

if TYPE_CHECKING:
    from ainrf.api.config import ApiConfig

# Paths that generate high traffic but have low debugging value.
_SKIP_PATHS: frozenset[str] = frozenset(
    {"/health", "/metrics", "/api/metrics", "/v1/metrics", "/favicon.ico"}
)


def build_request_logging_middleware(
    config: ApiConfig,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Return middleware that logs HTTP request/response details."""
    logger = structlog.get_logger("request_logging")
    slow_threshold = config.slow_request_threshold_seconds

    async def request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip noisy / low-value paths.
        if request.url.path in _SKIP_PATHS or request.url.path.startswith("/assets/"):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "-")
        method = request.method
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.monotonic() - start
            logger.error(
                "request_error",
                request_id=request_id,
                method=method,
                route=route_template_for_request(request),
                status=500,
                elapsed_ms=round(elapsed * 1000, 1),
            )
            raise

        elapsed = time.monotonic() - start
        status = response.status_code
        elapsed_ms = round(elapsed * 1000, 1)

        # Determine log level.
        if status >= 500:
            log_fn = logger.error
        elif elapsed >= slow_threshold:
            log_fn = logger.warning
        else:
            log_fn = logger.info

        log_fn(
            "request",
            request_id=request_id,
            method=method,
            route=route_template_for_request(request),
            status=status,
            elapsed_ms=elapsed_ms,
        )

        return response

    return request_logging_middleware

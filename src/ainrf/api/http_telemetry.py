"""HTTP-specific telemetry Adapter built on neutral metric recording."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response

from ainrf.telemetry.metrics import inc_counter, observe_histogram


def route_template_for_request(request: Request) -> str:
    """Return a bounded matched route template for metric labels."""

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template
    return "/unmatched"


def build_http_metrics_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Record HTTP request counts and latency through neutral telemetry."""

    async def http_metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in ("/metrics", "/api/metrics", "/v1/metrics"):
            return await call_next(request)
        start_time = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.monotonic() - start_time
            path = route_template_for_request(request)
            inc_counter(
                "ainrf_http_requests_total",
                {"method": request.method, "path": path, "status": "500"},
            )
            observe_histogram(
                "ainrf_http_request_duration_seconds",
                elapsed,
                {"method": request.method, "path": path},
            )
            raise
        elapsed = time.monotonic() - start_time
        path = route_template_for_request(request)
        inc_counter(
            "ainrf_http_requests_total",
            {"method": request.method, "path": path, "status": str(response.status_code)},
        )
        observe_histogram(
            "ainrf_http_request_duration_seconds",
            elapsed,
            {"method": request.method, "path": path},
        )
        return response

    return http_metrics_middleware

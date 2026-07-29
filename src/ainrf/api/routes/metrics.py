"""HTTP Adapter for neutral Prometheus telemetry."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from starlette import status

from ainrf.api.http_telemetry import build_http_metrics_middleware, route_template_for_request
from ainrf.domain_telemetry import refresh_domain_metrics
from ainrf.runtime.product_config import ApiConfig
from ainrf.telemetry.metrics import (
    dec_gauge,
    get_metrics_text,
    inc_counter,
    inc_gauge,
    observe_histogram,
    reset_metrics,
    set_counter,
    set_gauge,
)

__all__ = [
    "build_http_metrics_middleware",
    "create_metrics_router",
    "dec_gauge",
    "get_metrics_text",
    "inc_counter",
    "inc_gauge",
    "observe_histogram",
    "reset_metrics",
    "route_template_for_request",
    "set_counter",
    "set_gauge",
]


def create_metrics_router(config: ApiConfig) -> APIRouter:
    """Expose neutral metrics through the configured HTTP route."""

    router = APIRouter()

    @router.get(config.metrics_path)
    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        app_config: ApiConfig = request.app.state.api_config
        if not app_config.metrics_enabled:
            return PlainTextResponse("metrics disabled\n", status_code=status.HTTP_404_NOT_FOUND)
        refresh_domain_metrics(
            app_config.state_root,
            runtime_mode="v2",
            read_only=bool(getattr(request.app.state, "maintenance_startup_read_only", False)),
        )
        return PlainTextResponse(get_metrics_text())

    return router

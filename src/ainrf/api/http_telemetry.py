"""HTTP-specific telemetry Adapter built on neutral metric recording."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from ainrf.api.openapi import stable_operation_id
from ainrf.telemetry.compatibility import HttpContractObservation, observe_http_contract
from ainrf.telemetry.metrics import inc_counter, observe_histogram


def route_template_for_request(request: Request) -> str:
    """Return a bounded matched route template for metric labels."""

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template
    return "/unmatched"


def contract_operation_for_route(route: object, method: str) -> str:
    """Return one prefix-independent bounded operation ID."""

    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path.startswith("/"):
        return "unmatched"
    for prefix in ("/api", "/v1"):
        if path == prefix:
            path = "/"
            break
        if path.startswith(f"{prefix}/"):
            path = path[len(prefix) :]
            break
    normalized = APIRoute(path, lambda: None, methods=[method])
    return stable_operation_id(normalized)


def frozen_contract_operations(app: object) -> frozenset[str]:
    routes = getattr(app, "routes", ())
    operations = {
        contract_operation_for_route(route, method)
        for route in routes
        for method in (getattr(route, "methods", None) or ())
        if method != "HEAD"
    }
    operations.update({"get_models", "post_messages", "unmatched"})
    return frozenset(operations)


def contract_operation_for_request(request: Request) -> str:
    if request.url.path == "/v1/models":
        return "get_models"
    if request.url.path == "/v1/messages":
        return "post_messages"
    return contract_operation_for_route(request.scope.get("route"), request.method)


def build_http_metrics_middleware(
    *,
    allowed_operations: frozenset[str] | None = None,
    state_root: Path | None = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Record HTTP request counts and latency through neutral telemetry."""

    frozen_operations = allowed_operations or frozenset({"unmatched"})

    def observation_state_root(request: Request) -> Path | None:
        if state_root is not None:
            return state_root
        config = getattr(request.app.state, "api_config", None)
        configured = getattr(config, "state_root", None)
        return configured if isinstance(configured, Path) else None

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
            durable_root = observation_state_root(request)
            if durable_root is not None:
                observe_http_contract(
                    HttpContractObservation(
                        actual_path=request.url.path,
                        operation=contract_operation_for_request(request),
                        method=request.method,
                        status=500,
                        duration_seconds=elapsed,
                        allowed_operations=frozen_operations,
                        state_root=durable_root,
                        request_id=getattr(request.state, "request_id", None),
                    )
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
        durable_root = observation_state_root(request)
        if durable_root is not None:
            observe_http_contract(
                HttpContractObservation(
                    actual_path=request.url.path,
                    operation=contract_operation_for_request(request),
                    method=request.method,
                    status=response.status_code,
                    duration_seconds=elapsed,
                    allowed_operations=frozen_operations,
                    state_root=durable_root,
                    request_id=getattr(request.state, "request_id", None),
                )
            )
        return response

    return http_metrics_middleware

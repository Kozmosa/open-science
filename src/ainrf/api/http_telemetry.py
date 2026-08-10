"""HTTP-specific telemetry Adapter built on neutral metric recording."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from ainrf.api.openapi import stable_operation_id
from ainrf.telemetry.compatibility import HttpContractObservation, observe_http_contract
from ainrf.telemetry.metrics import inc_counter, observe_histogram


def route_template_for_request(request: Request) -> str:
    """Return a bounded route template for metric labels.

    Middleware runs before Starlette dispatches a request, so ``scope["route"]``
    is normally absent when a request is rejected by an outer limiter.  Fall
    back to the application's route table in that case so a known dynamic
    route keeps its template while unknown paths remain ``/unmatched``.
    """

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template
    return _route_template_from_table(request)


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


@dataclass(frozen=True, slots=True)
class ContractRoute:
    path: str
    path_regex: Pattern[str]
    methods: frozenset[str]


def _contract_routes(app: object) -> tuple[ContractRoute, ...]:
    frozen: list[ContractRoute] = []
    for route in getattr(app, "routes", ()):
        if isinstance(route, APIRoute):
            candidates: tuple[object, ...] = (route,)
        else:
            effective = getattr(route, "effective_route_contexts", None)
            candidates = tuple(effective()) if callable(effective) else ()
        for candidate in candidates:
            path = getattr(candidate, "path", None)
            path_regex = getattr(candidate, "path_regex", None)
            methods = getattr(candidate, "methods", None)
            if isinstance(path, str) and hasattr(path_regex, "fullmatch") and methods:
                frozen.append(ContractRoute(path, path_regex, frozenset(methods)))
    return tuple(frozen)


def _route_template_from_table(request: Request) -> str:
    """Resolve a bounded route template before Starlette route dispatch."""

    partial_template: str | None = None
    for candidate in _contract_routes(request.app):
        if not candidate.path_regex.fullmatch(request.url.path):
            continue
        if request.method in candidate.methods:
            return candidate.path
        partial_template = partial_template or candidate.path
    return partial_template or "/unmatched"


def frozen_contract_operations(app: object) -> frozenset[str]:
    routes = _contract_routes(app)
    operations = {
        contract_operation_for_route(route, method)
        for route in routes
        for method in (getattr(route, "methods", None) or ())
        if method != "HEAD"
    }
    operations.update({"get_models", "post_messages", "unmatched"})
    return frozenset(operations)


def frozen_contract_routes(app: object) -> tuple[ContractRoute, ...]:
    return _contract_routes(app)


def contract_operation_for_request(
    request: Request, contract_routes: tuple[ContractRoute, ...]
) -> str:
    if request.url.path == "/v1/models":
        return "get_models"
    if request.url.path == "/v1/messages":
        return "post_messages"
    for route in contract_routes:
        if request.method in (route.methods or ()) and route.path_regex.fullmatch(request.url.path):
            return contract_operation_for_route(route, request.method)
    return "unmatched"


def build_http_metrics_middleware(
    *,
    allowed_operations: frozenset[str] | None = None,
    contract_routes: tuple[ContractRoute, ...] = (),
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
                        operation=contract_operation_for_request(request, contract_routes),
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
                    operation=contract_operation_for_request(request, contract_routes),
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

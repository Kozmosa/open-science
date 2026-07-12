"""Prometheus metrics exposition backed by the ``prometheus_client`` library.

Replaces the hand-rolled in-memory dicts with production-grade histogram
bucketing (fixed memory) and standard exposition-format rendering.

Public API functions (``inc_counter``, ``observe_histogram``, ``inc_gauge``,
``dec_gauge``, ``get_metrics_text``, ``reset_metrics``) are preserved so
existing call sites work without changes.

Label names are pre-declared for each metric.  Metrics not listed in the
pre-declaration tables are created lazily (without labels, for test usage).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, REGISTRY, generate_latest
from starlette import status
from starlette.responses import Response

if TYPE_CHECKING:
    from ainrf.api.config import ApiConfig

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-declared metric specs
# ---------------------------------------------------------------------------
# (name, label_names, documentation)
_COUNTER_SPECS: list[tuple[str, list[str], str]] = [
    ("ainrf_http_requests_total", ["method", "path", "status"], "Total HTTP requests"),
    ("ainrf_auth_login_success_total", [], "Successful login attempts"),
    ("ainrf_auth_login_failed_total", ["reason"], "Failed login attempts"),
    ("ainrf_terminal_exec_total", [], "Terminal command executions"),
    ("ainrf_terminal_exec_denied_total", [], "Denied terminal command executions"),
    ("ainrf_files_sensitive_path_access_total", [], "Sensitive file path access events"),
    ("ainrf_environment_update_total", [], "Environment detection/update events"),
    ("ainrf_code_session_created_total", [], "Code session spawn events"),
    ("ainrf_task_created_total", [], "Tasks created"),
    ("ainrf_task_completed_total", [], "Tasks completed"),
    ("ainrf_task_failed_total", [], "Tasks failed"),
    (
        "ainrf_deprecated_route_calls_total",
        ["route"],
        "Deprecated compatibility route or field uses",
    ),
    ("ainrf_ssh_connection_attempt_total", ["host"], "SSH connection attempts"),
    ("ainrf_ssh_connection_error_total", ["host", "error_type"], "SSH connection errors"),
    ("ainrf_db_slow_query_total", ["db"], "Slow database queries (>1s)"),
    ("ainrf_client_error_events_total", [], "Client-side error events ingested"),
    ("ainrf_literature_fetch_total", ["subscription_id", "status"], "Literature fetch attempts"),
    (
        "ainrf_literature_papers_fetched_total",
        ["subscription_id"],
        "Papers returned from arXiv queries",
    ),
    (
        "ainrf_literature_papers_new_total",
        ["subscription_id"],
        "New papers inserted (excludes duplicates)",
    ),
    ("ainrf_literature_summarize_total", ["status"], "LLM summarize calls for literature papers"),
]

_HISTOGRAM_SPECS: list[tuple[str, list[str], str]] = [
    ("ainrf_http_request_duration_seconds", ["method", "path"], "HTTP request latency"),
    ("ainrf_ssh_command_duration_seconds", ["host"], "SSH command execution latency"),
    ("ainrf_db_query_duration_seconds", ["db"], "Database query latency"),
    (
        "ainrf_literature_fetch_duration_seconds",
        ["subscription_id"],
        "Literature fetch duration per subscription",
    ),
    ("ainrf_literature_summarize_duration_seconds", [], "Per-paper LLM summarize duration"),
]

_GAUGE_SPECS: list[tuple[str, list[str], str]] = [
    ("ainrf_terminal_ws_active", [], "Active WebSocket terminal sessions"),
    (
        "ainrf_literature_last_fetch_timestamp_seconds",
        ["subscription_id"],
        "Unix timestamp of last successful literature fetch",
    ),
]

# Default histogram buckets (seconds): 5 ms → 10 s
_DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# Set of metric names we own (for selective reset).
_OWN_METRIC_NAMES: set[str] = set()

# ---------------------------------------------------------------------------
# Metric storage (populated by _init_all)
# ---------------------------------------------------------------------------

_COUNTERS: dict[str, Counter] = {}
_HISTOGRAMS: dict[str, Histogram] = {}
_GAUGES: dict[str, Gauge] = {}


def _init_all() -> None:
    """Create all pre-declared metrics in the default registry."""
    for name, labelnames, doc in _COUNTER_SPECS:
        if name not in _COUNTERS:
            _COUNTERS[name] = Counter(name, doc, labelnames=labelnames, registry=REGISTRY)
            _OWN_METRIC_NAMES.add(name)
    for name, labelnames, doc in _HISTOGRAM_SPECS:
        if name not in _HISTOGRAMS:
            _HISTOGRAMS[name] = Histogram(
                name,
                doc,
                labelnames=labelnames,
                buckets=_DEFAULT_BUCKETS,
                registry=REGISTRY,
            )
            _OWN_METRIC_NAMES.add(name)
    for name, labelnames, doc in _GAUGE_SPECS:
        if name not in _GAUGES:
            _GAUGES[name] = Gauge(name, doc, labelnames=labelnames, registry=REGISTRY)
            _OWN_METRIC_NAMES.add(name)


_init_all()


def _get_or_create_counter(name: str) -> Counter:
    c = _COUNTERS.get(name)
    if c is not None:
        return c
    # Lazily create an unlabelled counter (test-only path).
    _LOG.debug("lazy_register_counter name=%s", name)
    c = Counter(name, name, registry=REGISTRY)
    _COUNTERS[name] = c
    _OWN_METRIC_NAMES.add(name)
    return c


def _get_or_create_histogram(name: str) -> Histogram:
    h = _HISTOGRAMS.get(name)
    if h is not None:
        return h
    _LOG.debug("lazy_register_histogram name=%s", name)
    h = Histogram(name, name, buckets=_DEFAULT_BUCKETS, registry=REGISTRY)
    _HISTOGRAMS[name] = h
    _OWN_METRIC_NAMES.add(name)
    return h


def _get_or_create_gauge(name: str) -> Gauge:
    g = _GAUGES.get(name)
    if g is not None:
        return g
    _LOG.debug("lazy_register_gauge name=%s", name)
    g = Gauge(name, name, registry=REGISTRY)
    _GAUGES[name] = g
    _OWN_METRIC_NAMES.add(name)
    return g


# ---------------------------------------------------------------------------
# Public mutation API (same signatures as the hand-rolled originals)
# ---------------------------------------------------------------------------


def inc_counter(name: str, labels: dict[str, str] | None = None, amount: float = 1) -> None:
    """Increment a Prometheus counter by *amount* (default 1)."""
    c = _get_or_create_counter(name)
    if labels:
        c.labels(**labels).inc(amount)
    else:
        c.inc(amount)


def observe_histogram(
    name: str,
    value: float,
    labels: dict[str, str] | None = None,
) -> None:
    """Record an observation on a Prometheus histogram."""
    h = _get_or_create_histogram(name)
    if labels:
        h.labels(**labels).observe(value)
    else:
        h.observe(value)


def set_gauge(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    """Set a Prometheus gauge to an absolute value."""
    g = _get_or_create_gauge(name)
    if labels:
        g.labels(**labels).set(value)
    else:
        g.set(value)


def inc_gauge(name: str, labels: dict[str, str] | None = None) -> None:
    """Increment a Prometheus gauge by 1."""
    g = _get_or_create_gauge(name)
    if labels:
        g.labels(**labels).inc()
    else:
        g.inc()


def dec_gauge(name: str, labels: dict[str, str] | None = None) -> None:
    """Decrement a Prometheus gauge by 1."""
    g = _get_or_create_gauge(name)
    if labels:
        g.labels(**labels).dec()
    else:
        g.dec()


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------


def get_metrics_text() -> str:
    """Render all registered metrics in Prometheus text exposition format."""
    return generate_latest(REGISTRY).decode("utf-8")


def reset_metrics() -> None:
    """Reset all metrics (for test isolation).

    Unregisters only our own collectors from the default registry and clears
    the internal lookup dicts so metrics are re-created on next use.
    Python runtime collectors (GC, platform) are left untouched.
    """
    for name in list(_OWN_METRIC_NAMES):
        # Find and unregister the collector that owns this metric name.
        for collector in list(REGISTRY._collector_to_names):
            if name in REGISTRY._collector_to_names[collector]:
                try:
                    REGISTRY.unregister(collector)
                except KeyError:
                    pass
                break
    _COUNTERS.clear()
    _HISTOGRAMS.clear()
    _GAUGES.clear()
    _OWN_METRIC_NAMES.clear()
    # Re-initialize pre-declared metrics.
    _init_all()


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_metrics_router(config: ApiConfig) -> APIRouter:
    """Return a router with a GET /metrics endpoint.

    The endpoint is always registered, but returns 404 when metrics are disabled.
    """
    router = APIRouter()

    @router.get(config.metrics_path)
    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        app_config: ApiConfig = request.app.state.api_config
        if not getattr(app_config, "metrics_enabled", False):
            return PlainTextResponse("metrics disabled\n", status_code=status.HTTP_404_NOT_FOUND)
        return PlainTextResponse(get_metrics_text())

    return router


# ---------------------------------------------------------------------------
# HTTP metrics middleware
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r"[0-9a-f]{8,}-?[0-9a-f]{4,}")
_NUM_RE = re.compile(r"/\d{2,}")


def _normalize_path(path: str) -> str:
    """Reduce path cardinality for Prometheus labels."""
    p = _NUM_RE.sub("/{id}", path)
    p = _UUID_RE.sub("{id}", p)
    if len(p) > 80:
        p = p[:77] + "..."
    return p


def build_http_metrics_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Starlette middleware that records request rate and latency histograms."""

    async def http_metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip the /metrics endpoint itself to avoid self-referential noise.
        if request.url.path in ("/metrics", "/api/metrics", "/v1/metrics"):
            return await call_next(request)

        start_time = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.monotonic() - start_time
            path = _normalize_path(request.url.path)
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
        path = _normalize_path(request.url.path)
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

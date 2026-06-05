from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from starlette import status

if TYPE_CHECKING:
    from ainrf.api.config import ApiConfig

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
_counters: dict[str, dict[frozenset[tuple[str, str]], int]] = {}
_histograms: dict[str, dict[frozenset[tuple[str, str]], list[float]]] = {}
_gauges: dict[str, dict[frozenset[tuple[str, str]], int]] = {}

_lock = threading.Lock()

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


# ---------------------------------------------------------------------------
# Pre-declared metrics
# ---------------------------------------------------------------------------
def _init_counters() -> None:
    names = [
        "ainrf_http_requests_total",
        "ainrf_auth_login_success_total",
        "ainrf_auth_login_failed_total",
        "ainrf_terminal_exec_total",
        "ainrf_terminal_exec_denied_total",
        "ainrf_files_sensitive_path_access_total",
        "ainrf_environment_update_total",
        "ainrf_code_session_created_total",
    ]
    for name in names:
        _counters.setdefault(name, {frozenset(): 0})


def _init_histograms() -> None:
    _histograms.setdefault("ainrf_http_request_duration_seconds", {frozenset(): []})


def _init_gauges() -> None:
    _gauges.setdefault("ainrf_terminal_ws_active", {frozenset(): 0})


_init_counters()
_init_histograms()
_init_gauges()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _label_key(labels: dict[str, str] | None) -> frozenset[tuple[str, str]]:
    return frozenset((labels or {}).items())


def inc_counter(name: str, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with _lock:
        _counters.setdefault(name, {})[key] = _counters.get(name, {}).get(key, 0) + 1


def observe_histogram(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with _lock:
        _histograms.setdefault(name, {})[key] = _histograms.get(name, {}).get(key, []) + [value]


def set_gauge(name: str, value: int, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with _lock:
        _gauges.setdefault(name, {})[key] = value


def inc_gauge(name: str, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with _lock:
        _gauges.setdefault(name, {})[key] = _gauges.get(name, {}).get(key, 0) + 1


def dec_gauge(name: str, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with _lock:
        _gauges.setdefault(name, {})[key] = _gauges.get(name, {}).get(key, 0) - 1


def _format_labels(key: frozenset[tuple[str, str]]) -> str:
    if not key:
        return ""
    items = sorted(key)
    pairs = ",".join(f'{k}="{v}"' for k, v in items)
    return "{" + pairs + "}"


def _render_counter(name: str) -> list[str]:
    lines: list[str] = []
    lines.append(f"# TYPE {name} counter")
    with _lock:
        data = dict(_counters.get(name, {}))
    for key, value in sorted(data.items(), key=lambda x: sorted(x[0]) if x[0] else []):
        lines.append(f"{name}{_format_labels(key)} {value}")
    return lines


def _render_gauge(name: str) -> list[str]:
    lines: list[str] = []
    lines.append(f"# TYPE {name} gauge")
    with _lock:
        data = dict(_gauges.get(name, {}))
    for key, value in sorted(data.items(), key=lambda x: sorted(x[0]) if x[0] else []):
        lines.append(f"{name}{_format_labels(key)} {value}")
    return lines


def _render_histogram(name: str) -> list[str]:
    lines: list[str] = []
    lines.append(f"# TYPE {name} histogram")
    with _lock:
        data = dict(_histograms.get(name, {}))
    for key, observations in sorted(data.items(), key=lambda x: sorted(x[0]) if x[0] else []):
        label_str = _format_labels(key)
        # bucket lines
        for bound in _DEFAULT_BUCKETS:
            count = sum(1 for v in observations if v <= bound)
            bucket_label = (
                "{" + ",".join(f'{k}="{v}"' for k, v in sorted(key)) + ',le="' + str(bound) + '"}'
                if key
                else '{le="' + str(bound) + '"}'
            )
            lines.append(f"{name}_bucket{bucket_label} {count}")
        # +Inf bucket
        inf_label = (
            "{" + ",".join(f'{k}="{v}"' for k, v in sorted(key)) + ',le="+Inf"}'
            if key
            else '{le="+Inf"}'
        )
        lines.append(f"{name}_bucket{inf_label} {len(observations)}")
        lines.append(f"{name}_sum{label_str} {sum(observations)}")
        lines.append(f"{name}_count{label_str} {len(observations)}")
    return lines


def get_metrics_text() -> str:
    """Render all metrics in Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        counter_names = list(_counters.keys())
        histogram_names = list(_histograms.keys())
        gauge_names = list(_gauges.keys())
    for name in counter_names:
        lines.extend(_render_counter(name))
    for name in gauge_names:
        lines.extend(_render_gauge(name))
    for name in histogram_names:
        lines.extend(_render_histogram(name))
    return "\n".join(lines) + "\n"


def reset_metrics() -> None:
    """Reset all metrics to their initial state (for testing)."""
    with _lock:
        _counters.clear()
        _histograms.clear()
        _gauges.clear()
    _init_counters()
    _init_histograms()
    _init_gauges()


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

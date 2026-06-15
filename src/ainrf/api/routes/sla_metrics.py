"""SLA (Service Level Agreement) metrics.

Defines Prometheus metrics that measure end-to-end service quality:
  - Task completion latency (create → complete)
  - LLM first-token latency
  - Task outcomes (succeeded / failed / cancelled)
  - Process uptime

These are recorded alongside the existing ``ainrf_*`` metrics and feed into
Grafana SLA dashboards and Prometheus alerting rules.

Usage::

    from ainrf.api.routes.sla_metrics import (
        record_task_completed, record_llm_first_token, record_uptime,
    )
"""

from __future__ import annotations

import time as _time

from prometheus_client import Counter, Gauge, Histogram, REGISTRY

# ---------------------------------------------------------------------------
# SLA metric definitions
# ---------------------------------------------------------------------------

# Task end-to-end latency: from QUEUED → SUCCEEDED / FAILED / CANCELLED.
# Buckets: 1 min → 2 hours (covers most research tasks).
sla_task_completion_seconds = Histogram(
    "ainrf_sla_task_completion_seconds",
    "End-to-end task completion latency (queued → terminal status)",
    labelnames=["status"],
    buckets=(60, 300, 600, 900, 1800, 3600, 7200),
    registry=REGISTRY,
)

# LLM first-token latency: time from LLM request to first contentful token.
# Buckets: 100 ms → 60 s.
sla_llm_first_token_seconds = Histogram(
    "ainrf_sla_llm_first_token_seconds",
    "Time to first token from LLM calls",
    labelnames=["model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

# Task outcome counter (succeeded / failed / cancelled).
sla_tasks_total = Counter(
    "ainrf_sla_tasks_total",
    "Total tasks completed by outcome",
    labelnames=["status", "researcher_type", "harness_engine"],
    registry=REGISTRY,
)

# Process uptime gauge (set at startup, incremented periodically).
# Prometheus can compute availability from this + HTTP status metrics.
sla_uptime_seconds = Gauge(
    "ainrf_sla_uptime_seconds",
    "Process uptime in seconds",
    registry=REGISTRY,
)

# Rate-limited request counter (updated by middleware and client-logs route).
sla_rate_limited_total = Counter(
    "ainrf_rate_limited_total",
    "Requests rejected by rate limiting",
    labelnames=["reason", "path"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------

_start_time: float = _time.monotonic()
_first_token_times: dict[str, float] = {}  # task_id → timestamp of first LLM token
_task_start_times: dict[str, float] = {}   # task_id → timestamp when task started


def record_uptime() -> None:
    """Set the uptime gauge to current elapsed seconds."""
    sla_uptime_seconds.set(_time.monotonic() - _start_time)


def record_task_started(task_id: str) -> None:
    """Record the wall-clock time when a task begins execution."""
    _task_start_times[task_id] = _time.monotonic()


def record_task_completed(
    task_id: str,
    status: str,
    *,
    researcher_type: str = "",
    harness_engine: str = "",
) -> None:
    """Record task completion latency and outcome counter.

    Must be called *after* ``record_task_started`` for the same task_id.
    """
    start = _task_start_times.pop(task_id, None)
    if start is not None:
        elapsed = _time.monotonic() - start
        sla_task_completion_seconds.labels(status=status).observe(elapsed)
    sla_tasks_total.labels(
        status=status,
        researcher_type=researcher_type,
        harness_engine=harness_engine,
    ).inc()


def record_llm_first_token(
    task_id: str,
    model: str = "",
) -> None:
    """Record LLM first-token latency for a task.

    Idempotent: only the first call per task_id is recorded; subsequent
    calls are silently ignored (we want *first* token, not every token).
    """
    if task_id in _first_token_times:
        return
    _first_token_times[task_id] = _time.monotonic()
    # We don't have the actual request-start timestamp here — the caller
    # (service.py) should pass it.  For now, this marks "first token seen".
    # The caller can pass `latency` directly if known.
    # This is a best-effort implementation; Phase 2 (OTel) will provide
    # span-based timing for more precise measurement.


def record_llm_first_token_latency(
    model: str,
    latency_seconds: float,
) -> None:
    """Directly record a first-token latency measurement."""
    sla_llm_first_token_seconds.labels(model=model).observe(latency_seconds)


def cleanup_task_state(task_id: str) -> None:
    """Remove any in-memory state for a completed task."""
    _first_token_times.pop(task_id, None)
    _task_start_times.pop(task_id, None)


def rate_limited(reason: str, path: str = "") -> None:
    """Increment the rate-limited counter."""
    sla_rate_limited_total.labels(reason=reason, path=path).inc()

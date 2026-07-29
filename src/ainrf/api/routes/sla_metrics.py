"""Compatibility exports for neutral SLA telemetry."""

from ainrf.telemetry.sla import (
    cleanup_task_state,
    rate_limited,
    record_llm_first_token,
    record_llm_first_token_latency,
    record_task_completed,
    record_task_started,
    record_uptime,
    sla_llm_first_token_seconds,
    sla_rate_limited_total,
    sla_task_completion_seconds,
    sla_tasks_total,
    sla_uptime_seconds,
)

__all__ = [
    "cleanup_task_state",
    "rate_limited",
    "record_llm_first_token",
    "record_llm_first_token_latency",
    "record_task_completed",
    "record_task_started",
    "record_uptime",
    "sla_llm_first_token_seconds",
    "sla_rate_limited_total",
    "sla_task_completion_seconds",
    "sla_tasks_total",
    "sla_uptime_seconds",
]

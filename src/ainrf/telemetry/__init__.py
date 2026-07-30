"""Transport-neutral metrics and optional OpenTelemetry instrumentation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ainrf.telemetry.metrics import (
    dec_gauge,
    get_metrics_text,
    inc_counter,
    inc_gauge,
    observe_histogram,
    reset_metrics,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class TelemetryConfig:
    enabled: bool = False
    service_name: str = "ainrf"
    deployment_environment: str = "production"
    exporter_endpoint: str = ""
    sample_rate: float = 1.0

    @classmethod
    def from_env(cls) -> TelemetryConfig:
        return cls(
            enabled=os.environ.get("AINRF_OTEL_ENABLED", "").lower() in ("1", "true", "yes"),
            service_name=os.environ.get("AINRF_OTEL_SERVICE_NAME", "ainrf"),
            deployment_environment=os.environ.get("AINRF_OTEL_DEPLOYMENT_ENV", "production"),
            exporter_endpoint=os.environ.get("AINRF_OTEL_EXPORTER_ENDPOINT", ""),
            sample_rate=float(os.environ.get("AINRF_OTEL_SAMPLE_RATE", "1.0")),
        )


def init_telemetry(app: FastAPI, config: TelemetryConfig | None = None) -> None:
    """Initialize optional OpenTelemetry instrumentation for the HTTP Adapter."""

    telemetry_config = config or TelemetryConfig.from_env()
    if not telemetry_config.enabled:
        _LOG.debug("OpenTelemetry is disabled (AINRF_OTEL_ENABLED not set)")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError as exc:
        _LOG.warning("otel_import_failed error=%s", exc)
        return
    provider = TracerProvider(
        resource=Resource(
            attributes={
                SERVICE_NAME: telemetry_config.service_name,
                "deployment.environment": telemetry_config.deployment_environment,
            }
        ),
        sampler=TraceIdRatioBased(telemetry_config.sample_rate),
    )
    if telemetry_config.exporter_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=telemetry_config.exporter_endpoint))
            )
        except Exception as exc:
            _LOG.warning("otel_exporter_init_failed error=%s", exc)
    trace.set_tracer_provider(provider)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health,/metrics")
    except Exception as exc:
        _LOG.warning("otel_fastapi_instrumentation_failed error=%s", exc)
    try:
        from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

        SQLite3Instrumentor().instrument()
    except Exception as exc:
        _LOG.warning("otel_sqlite3_instrumentation_failed error=%s", exc)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        _LOG.warning("otel_httpx_instrumentation_failed error=%s", exc)


__all__ = [
    "TelemetryConfig",
    "dec_gauge",
    "get_metrics_text",
    "inc_counter",
    "inc_gauge",
    "init_telemetry",
    "observe_histogram",
    "reset_metrics",
]

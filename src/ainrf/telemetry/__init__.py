"""OpenTelemetry auto-instrumentation for distributed tracing.

When enabled (``AINRF_OTEL_ENABLED=true``), automatically creates spans for:
  - Every HTTP request (FastAPI instrumentor)
  - Every SQLite3 database query (SQLite3 instrumentor)
  - Every outgoing HTTPX request (HTTPX instrumentor)

Traces are exported to the configured OTLP endpoint.  When disabled (default),
zero overhead: no SDK initialization, no span creation.

Usage — call once at application startup::

    from ainrf.telemetry import init_telemetry

    init_telemetry(app, config)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class TelemetryConfig:
    """Configuration for OpenTelemetry instrumentation."""

    enabled: bool = False
    service_name: str = "ainrf"
    deployment_environment: str = "production"
    exporter_endpoint: str = ""
    sample_rate: float = 1.0

    @classmethod
    def from_env(cls) -> TelemetryConfig:
        """Read configuration from ``AINRF_OTEL_*`` environment variables."""
        return cls(
            enabled=os.environ.get("AINRF_OTEL_ENABLED", "").lower()
            in ("1", "true", "yes"),
            service_name=os.environ.get("AINRF_OTEL_SERVICE_NAME", "ainrf"),
            deployment_environment=os.environ.get(
                "AINRF_OTEL_DEPLOYMENT_ENV", "production",
            ),
            exporter_endpoint=os.environ.get("AINRF_OTEL_EXPORTER_ENDPOINT", ""),
            sample_rate=float(
                os.environ.get("AINRF_OTEL_SAMPLE_RATE", "1.0"),
            ),
        )


def init_telemetry(app: FastAPI, config: TelemetryConfig | None = None) -> None:
    """Initialize OpenTelemetry SDK and auto-instrumentation.

    Parameters
    ----------
    app:
        The FastAPI application instance to instrument.
    config:
        Telemetry configuration.  Reads from env vars when ``None``.
    """
    if config is None:
        config = TelemetryConfig.from_env()

    if not config.enabled:
        _LOG.debug("OpenTelemetry is disabled (AINRF_OTEL_ENABLED not set)")
        return

    _LOG.info(
        "otel_init",
        service_name=config.service_name,
        exporter_endpoint=config.exporter_endpoint or "(none — local only)",
    )

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError as exc:
        _LOG.warning("otel_import_failed error=%s", exc)
        return

    # Resource identifies this service in the trace backend.
    resource = Resource(attributes={
        SERVICE_NAME: config.service_name,
        "deployment.environment": config.deployment_environment,
    })

    # Tracer provider with optional sampling.
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(config.sample_rate),
    )

    # OTLP exporter (optional — when not configured, spans stay local only,
    # which is useful for development).
    if config.exporter_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=config.exporter_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            _LOG.info("otel_exporter_configured endpoint=%s", config.exporter_endpoint)
        except Exception as exc:
            _LOG.warning("otel_exporter_init_failed error=%s", exc)

    trace.set_tracer_provider(provider)

    # ── Auto-instrumentation ──────────────────────────────────────
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=",".join(["/health", "/metrics"]),
        )
        _LOG.info("otel_fastapi_instrumented")
    except Exception as exc:
        _LOG.warning("otel_fastapi_instrumentation_failed error=%s", exc)

    try:
        from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
        SQLite3Instrumentor().instrument()
        _LOG.info("otel_sqlite3_instrumented")
    except Exception as exc:
        _LOG.warning("otel_sqlite3_instrumentation_failed error=%s", exc)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXInstrumentor
        HTTPXInstrumentor().instrument()
        _LOG.info("otel_httpx_instrumented")
    except Exception as exc:
        _LOG.warning("otel_httpx_instrumentation_failed error=%s", exc)

"""Client-side web vitals metrics ingestion endpoint.

Accepts Core Web Vitals (LCP, FCP, INP, CLS) from the frontend and records
them as Prometheus histograms for observability dashboards.

The endpoint is **unauthenticated** (metrics can be collected before login)
but rate-limited to prevent abuse.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

from ainrf.api.routes.sla_metrics import rate_limited

router = APIRouter(prefix="/client-metrics", tags=["client-metrics"])

_LOGGER = logging.getLogger("client_metrics")

# Simple rate limiter: max 20 batches per IP per 60-second window.
_MAX_BATCHES_PER_WINDOW = 20
_WINDOW_SECONDS = 60
_ip_counts: dict[str, tuple[int, float]] = {}


def _is_rate_limited(client_ip: str) -> bool:
    import time

    now = time.monotonic()
    count, window_start = _ip_counts.get(client_ip, (0, now))
    if now - window_start > _WINDOW_SECONDS:
        _ip_counts[client_ip] = (1, now)
        return False
    if count >= _MAX_BATCHES_PER_WINDOW:
        return True
    _ip_counts[client_ip] = (count + 1, window_start)
    return False


@router.post("", status_code=204)
async def ingest_client_metrics(request: Request) -> Response:
    """Accept a batch of client-side web vitals metrics."""
    client_ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(client_ip):
        rate_limited("ip_quota", "/client-metrics")
        return PlainTextResponse("rate limited", status_code=429)

    try:
        body = await request.json()
    except Exception:
        return PlainTextResponse("invalid json", status_code=400)

    metrics = body.get("metrics") if isinstance(body, dict) else None
    if not isinstance(metrics, list):
        return PlainTextResponse("expected {metrics: [...]}", status_code=400)

    for metric in metrics[:20]:  # cap per-request batch size
        if not isinstance(metric, dict):
            continue
        name = metric.get("name", "")
        value = metric.get("value")
        rating = metric.get("rating", "")
        url = metric.get("url", "")

        if not isinstance(name, str) or not isinstance(value, (int, float)):
            continue

        _LOGGER.info(
            "web_vital",
            extra={
                "client_ip": client_ip,
                "name": name,
                "value": value,
                "rating": rating,
                "url": url,
            },
        )

        # Record to Prometheus histogram if we have a matching metric.
        _record_web_vital(name, float(value), rating, url)

    return Response(status_code=204)


def _record_web_vital(name: str, value: float, rating: str, _url: str) -> None:
    """Record a web vital metric to the appropriate Prometheus histogram."""
    try:
        from prometheus_client import REGISTRY

        metric_name = f"ainrf_client_{name.lower()}_seconds"
        # Metrics are created lazily via observe_histogram in sla_metrics.
        from ainrf.api.routes.metrics import observe_histogram

        labels: dict[str, str] = {"rating": rating} if rating else {}
        observe_histogram(metric_name, value, labels)
    except Exception:
        pass

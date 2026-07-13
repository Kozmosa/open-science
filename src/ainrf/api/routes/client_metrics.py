"""Client-side web vitals metrics ingestion endpoint.

Accepts Core Web Vitals (LCP, FCP, INP, CLS) from the frontend and records
them as Prometheus histograms for observability dashboards.

The endpoint is **unauthenticated** (metrics can be collected before login)
but rate-limited to prevent abuse.
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

from ainrf.api.routes.sla_metrics import rate_limited

router = APIRouter(prefix="/client-metrics", tags=["client-metrics"])

_LOGGER = logging.getLogger("client_metrics")

# Simple rate limiter: max 20 batches per IP per 60-second window.
_MAX_BATCHES_PER_WINDOW = 20
_WINDOW_SECONDS = 60
_ip_counts: dict[str, tuple[int, float]] = {}

# This endpoint is intentionally public, so neither the Prometheus metric
# name nor a label may be derived from a browser-supplied value.  Keep the
# frontend contract's four Core Web Vitals while mapping malformed ratings to
# one bounded bucket for operational visibility.
_WEB_VITAL_METRICS = {
    "LCP": "ainrf_client_lcp_seconds",
    "FCP": "ainrf_client_fcp_seconds",
    "INP": "ainrf_client_inp_seconds",
    "CLS": "ainrf_client_cls_seconds",
}
_WEB_VITAL_RATINGS = frozenset({"good", "needs-improvement", "poor"})
_UNKNOWN_WEB_VITAL_RATING = "unknown"


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
        normalized = _normalize_web_vital(
            metric.get("name"), metric.get("value"), metric.get("rating")
        )
        if normalized is None:
            continue
        metric_name, value, rating = normalized

        _LOGGER.info(
            "web_vital",
            extra={
                "client_ip": client_ip,
                "metric_name": metric_name,
                "value": value,
                "rating": rating,
            },
        )

        _record_web_vital(metric_name, value, rating)

    return Response(status_code=204)


def _normalize_web_vital(
    raw_name: object, raw_value: object, raw_rating: object
) -> tuple[str, float, str] | None:
    """Validate browser input against the bounded public metric contract."""

    if not isinstance(raw_name, str):
        return None
    metric_name = _WEB_VITAL_METRICS.get(raw_name)
    if metric_name is None:
        return None
    if (
        not isinstance(raw_value, (int, float))
        or isinstance(raw_value, bool)
        or not math.isfinite(float(raw_value))
    ):
        return None
    rating = (
        raw_rating
        if isinstance(raw_rating, str) and raw_rating in _WEB_VITAL_RATINGS
        else _UNKNOWN_WEB_VITAL_RATING
    )
    return metric_name, float(raw_value), rating


def _record_web_vital(metric_name: str, value: float, rating: str) -> None:
    """Record one already-normalized Core Web Vital histogram observation."""

    from ainrf.api.routes.metrics import observe_histogram

    observe_histogram(metric_name, value, {"rating": rating})

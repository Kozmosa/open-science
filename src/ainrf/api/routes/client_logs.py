"""Client-side error log ingestion endpoint.

Accepts error events from the frontend and writes them to a dedicated
log file (``<state_root>/logs/frontend-YYYYMMDD.log``) via structlog.
The endpoint is **unauthenticated** (frontend errors may occur before
login) but rate-limited to prevent abuse.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

from ainrf.api.routes.metrics import inc_counter

router = APIRouter(prefix="/client-logs", tags=["client-logs"])

_logger = logging.getLogger("client_logs")

# Simple in-memory rate limiter: max N events per IP per window.
_MAX_EVENTS_PER_WINDOW = 50
_WINDOW_SECONDS = 60
_ip_counts: dict[str, tuple[int, float]] = {}


def _is_rate_limited(client_ip: str) -> bool:
    import time

    now = time.monotonic()
    count, window_start = _ip_counts.get(client_ip, (0, now))
    if now - window_start > _WINDOW_SECONDS:
        _ip_counts[client_ip] = (1, now)
        return False
    if count >= _MAX_EVENTS_PER_WINDOW:
        return True
    _ip_counts[client_ip] = (count + 1, window_start)
    return False


@router.post("", status_code=204)
async def ingest_client_logs(request: Request) -> Response:
    """Accept a batch of client-side error events."""
    client_ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(client_ip):
        from ainrf.api.routes.sla_metrics import rate_limited

        rate_limited("ip_quota", "/client-logs")
        return PlainTextResponse("rate limited", status_code=429)

    try:
        body = await request.json()
    except Exception:
        return PlainTextResponse("invalid json", status_code=400)

    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list):
        return PlainTextResponse("expected {events: [...]}", status_code=400)

    for event in events[:20]:  # cap per-request batch size
        if not isinstance(event, dict):
            continue
        _logger.warning(
            "client_error",
            extra={
                "client_ip": client_ip,
                "message": event.get("message", ""),
                "url": event.get("url", ""),
                "request_id": event.get("requestId", ""),
                "user_agent": event.get("userAgent", ""),
                "stack": (event.get("stack") or "")[:500],
                "metadata": event.get("metadata"),
            },
        )

    inc_counter("ainrf_client_error_events_total")
    return Response(status_code=204)

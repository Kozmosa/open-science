"""Request-context middleware.

Generates a ``request_id`` (UUID) and attaches it to every request, then
propagates it via structlog contextvars and the ``X-Request-ID`` response
header.

When an upstream proxy / load balancer sends an ``X-Request-ID`` header,
that value is reused so trace context can be correlated across services.
When a W3C ``traceparent`` header is present, the ``trace_id`` portion is
extracted and bound to structlog context as well.

All bound contextvars are unbound in a ``finally`` block to prevent
cross-request context leakage.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response

# W3C Trace Context: traceparent = version-trace_id-parent_id-flags
# https://www.w3.org/TR/trace-context/#traceparent-header
_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def build_request_context_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Return middleware that generates/accepts request_id and propagates via structlog."""

    async def request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Accept an upstream request ID so trace context can be correlated
        # across services (nginx → backend → downstream).
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Parse W3C traceparent header for distributed tracing.
        trace_id: str | None = None
        tp = request.headers.get("traceparent", "")
        m = _TRACEPARENT_RE.match(tp)
        if m:
            trace_id = m.group(2)  # 32-char hex trace ID
        request.state.trace_id = trace_id

        # Bind to structlog context so all downstream logs carry these IDs.
        bound_keys: dict[str, str] = {"request_id": request_id}
        if trace_id:
            bound_keys["trace_id"] = trace_id
        structlog.contextvars.bind_contextvars(**bound_keys)

        try:
            response = await call_next(request)
        finally:
            # Unbind ALL keys we added to prevent context leakage across requests.
            for key in bound_keys:
                structlog.contextvars.unbind_contextvars(key)

        response.headers["X-Request-ID"] = request_id
        return response

    return request_context_middleware

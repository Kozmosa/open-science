"""Consistent compatibility-response deprecation metadata and observability."""

from __future__ import annotations

import logging

from starlette.responses import Response

from ainrf.api.routes.metrics import inc_counter

_LOG = logging.getLogger(__name__)

# The actual removal remains Release-E gated.  A fixed, intentionally distant
# RFC 7231 date makes the compatibility contract machine-readable without
# claiming that a production cleanup has already been approved.
DEFAULT_SUNSET = "Thu, 31 Dec 2026 23:59:59 GMT"


def deprecation_headers(*, route: str, replacement: str) -> dict[str, str]:
    """Record one compatibility use and return its stable HTTP headers."""

    inc_counter("ainrf_deprecated_route_calls_total", {"route": route})
    _LOG.info("deprecated_route_used route=%s replacement=%s", route, replacement)
    return {
        "Deprecation": "true",
        "Sunset": DEFAULT_SUNSET,
        "Link": f'<{replacement}>; rel="successor-version"',
    }


def mark_deprecated(response: Response, *, route: str, replacement: str) -> None:
    """Attach deprecation headers to an already-created compatibility response."""

    for name, value in deprecation_headers(route=route, replacement=replacement).items():
        response.headers[name] = value

"""Consistent compatibility-response deprecation metadata and observability."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from ainrf.domain_telemetry import record_deprecated_route

# The actual removal remains Release-E gated.  A fixed, intentionally distant
# RFC 7231 date makes the compatibility contract machine-readable without
# claiming that a production cleanup has already been approved.
DEFAULT_SUNSET = "Thu, 31 Dec 2026 23:59:59 GMT"


def record_deprecated_use(*, request: Request, route: str, replacement: str) -> None:
    """Maintain the superseded legacy metric during its transition release."""

    record_deprecated_route(
        route=route,
        replacement=replacement,
        state_root=request.app.state.api_config.state_root,
    )


def deprecation_headers(*, route: str, replacement: str) -> dict[str, str]:
    """Return stable HTTP deprecation headers without inferring telemetry."""

    record_deprecated_route(route=route, replacement=replacement)
    return {
        "Deprecation": "true",
        "Sunset": DEFAULT_SUNSET,
        "Link": f'<{replacement}>; rel="successor-version"',
    }


def mark_deprecated(response: Response, *, route: str, replacement: str) -> None:
    """Attach deprecation headers to an already-created compatibility response."""

    for name, value in deprecation_headers(route=route, replacement=replacement).items():
        response.headers[name] = value

"""Prometheus telemetry for bounded rate-limit events."""

from __future__ import annotations

from ainrf.telemetry.metrics import inc_counter

_PUBLIC_STATIC_RATE_LIMIT_ROUTES = frozenset({"/client-logs", "/client-metrics"})


def normalize_rate_limit_route(route: str) -> str:
    """Return a bounded route label suitable for public metric exposition."""

    if route in _PUBLIC_STATIC_RATE_LIMIT_ROUTES or "{" in route:
        return route
    return "/unmatched"


def rate_limited(reason: str, route: str = "/unmatched") -> None:
    """Record one request rejected by a rate limit."""

    inc_counter(
        "ainrf_rate_limited_total",
        {"reason": reason, "route": normalize_rate_limit_route(route)},
    )


__all__ = ["normalize_rate_limit_route", "rate_limited"]

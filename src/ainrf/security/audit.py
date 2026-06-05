from __future__ import annotations

from typing import Any

import structlog

_AUDIT_LOGGER: structlog.stdlib.BoundLogger | None = None

_SEVERITY_METHODS: dict[str, str] = {
    "info": "info",
    "warning": "warning",
    "high": "error",
    "critical": "critical",
}


def get_audit_logger() -> structlog.stdlib.BoundLogger:
    """Return the module-level audit logger singleton."""
    global _AUDIT_LOGGER
    if _AUDIT_LOGGER is None:
        _AUDIT_LOGGER = structlog.get_logger("audit").bind(component="audit")
    return _AUDIT_LOGGER


def audit_event(event: str, severity: str = "info", **kwargs: Any) -> None:
    """Log a structured security audit event.

    The event is always emitted with ``event``, ``severity``, and a
    ``timestamp`` (added by the structlog processors configured in
    ``ainrf.logging``). Additional keyword arguments are attached as-is.
    """
    logger = get_audit_logger()
    method_name = _SEVERITY_METHODS.get(severity.lower(), "info")
    method = getattr(logger, method_name)
    method(event, severity=severity, **kwargs)

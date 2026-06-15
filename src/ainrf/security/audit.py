"""Structured security audit logging.

Provides a typed schema for audit events and an ``emit_audit()`` function
that auto-extracts common fields (request_id, client IP) from runtime context.

The legacy ``audit_event(event, severity, **kwargs)`` function is kept as a
compatibility wrapper for existing call sites.

Usage::

    from ainrf.security.audit import AuditEvent, emit_audit

    emit_audit(AuditEvent(
        action="user.login",
        result="success",
        actor_id="user-123",
        actor_type="user",
    ))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

_AUDIT_LOGGER: structlog.stdlib.BoundLogger | None = None

_SEVERITY_ME = {
    "info": "info",
    "warning": "warning",
    "high": "error",
    "critical": "critical",
}

# Reverse mapping for AuditEvent.severity → structlog method name
_SEVERITY_METHODS = {
    "info": "info",
    "warning": "warning",
    "error": "error",
    "critical": "critical",
}


def _get_audit_logger() -> structlog.stdlib.BoundLogger:
    """Return the module-level audit logger singleton."""
    global _AUDIT_LOGGER
    if _AUDIT_LOGGER is None:
        _AUDIT_LOGGER = structlog.get_logger("audit").bind(component="audit")
    return _AUDIT_LOGGER


def _ctx_request_id() -> str | None:
    """Best-effort extraction of request_id from structlog contextvars."""
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id")


# ---------------------------------------------------------------------------
# Typed audit event
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AuditEvent:
    """Structured security audit event.

    Fields
    ------
    action:
        What happened, in ``<noun>.<verb>`` form (e.g. ``"user.login"``).
    result:
        Outcome: ``"success"``, ``"failure"``, or ``"denied"``.
    actor_id:
        Who performed the action (user ID, API key ID, ``"system"``).
    actor_type:
        Kind of actor: ``"user"``, ``"api_key"``, or ``"system"``.
    resource_id:
        What was acted upon (task ID, workspace ID, file path).
    resource_type:
        Kind of resource: ``"task"``, ``"workspace"``, ``"file"``, ``"session"``.
    details:
        Supplementary structured context dict.
    severity:
        ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
    client_ip:
        IP address of the originating client.
    request_id:
        Correlating request ID (auto-extracted if not provided).
    """

    action: str
    result: str = "success"
    actor_id: str | None = None
    actor_type: str = "user"
    resource_id: str | None = None
    resource_type: str | None = None
    details: dict[str, Any] | None = None
    severity: str = "info"
    client_ip: str | None = None
    request_id: str | None = field(default_factory=_ctx_request_id)


def emit_audit(event: AuditEvent) -> None:
    """Emit a structured audit event via structlog.

    The event is logged with ``component="audit"`` and all fields attached
    as structured key-value pairs.  Timestamp is added automatically by the
    structlog processors configured in ``ainrf.logging``.
    """
    logger = _get_audit_logger()
    method_name = _SEVERITY_METHODS.get(event.severity, "info")
    method = getattr(logger, method_name)
    method(
        event.action,
        result=event.result,
        actor_id=event.actor_id,
        actor_type=event.actor_type,
        resource_id=event.resource_id,
        resource_type=event.resource_type,
        details=event.details,
        severity=event.severity,
        client_ip=event.client_ip,
        request_id=event.request_id,
    )


# ---------------------------------------------------------------------------
# Legacy compatibility wrapper
# ---------------------------------------------------------------------------


def audit_event(event: str, severity: str = "info", **kwargs: Any) -> None:
    """Log a structured security audit event (legacy API).

    Prefer :func:`emit_audit` for new code — it enforces a consistent
    schema across all call sites.
    """
    logger = _get_audit_logger()
    method_name = _SEVERITY_ME.get(severity.lower(), "info")
    method = getattr(logger, method_name)
    method(event, severity=severity, **kwargs)

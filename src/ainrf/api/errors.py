"""Structured API error helpers.

Provides :func:`raise_structured_error` which creates an ``HTTPException``
with a machine-readable ``error_code`` alongside the human-readable
``detail``, and automatically logs the error via structlog.

When ``request_id`` is not explicitly passed, it is auto-extracted from
structlog's bound contextvars (set by the ``request_context`` middleware).

This is an **opt-in** utility — existing ``HTTPException`` raises continue
to work.  New code and high-value endpoints should migrate gradually.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import HTTPException

_LOG = structlog.get_logger(__name__).bind(component="api_errors")


def raise_structured_error(
    status_code: int,
    error_code: str,
    detail: str,
    *,
    log_level: str = "warning",
    request_id: str | None = None,
    **context: Any,
) -> None:
    """Raise an ``HTTPException`` with structured detail and automatic logging.

    Parameters
    ----------
    status_code:
        HTTP status code (e.g. 400, 404, 500).
    error_code:
        Machine-readable error identifier (e.g. ``"task_not_found"``).
    detail:
        Human-readable error description.
    log_level:
        Structlog level name for the log entry (default ``"warning"``).
    request_id:
        Correlating request ID.  Auto-extracted from structlog contextvars
        if not explicitly provided.
    **context:
        Additional key-value pairs attached to both the log entry and the
        response detail payload.
    """
    # Auto-extract request_id from structlog contextvars if not provided.
    if request_id is None:
        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get("request_id")

    _LOG_kwargs: dict[str, Any] = {
        "error_code": error_code,
        "status_code": status_code,
        "detail": detail,
        **context,
    }
    if request_id is not None:
        _LOG_kwargs["request_id"] = request_id

    getattr(_LOG, log_level)("api_error", **_LOG_kwargs)

    detail_payload: dict[str, Any] = {
        "error_code": error_code,
        "message": detail,
        **context,
    }
    if request_id is not None:
        detail_payload["request_id"] = request_id

    raise HTTPException(
        status_code=status_code,
        detail=detail_payload,
    )

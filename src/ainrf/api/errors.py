"""Structured API error helpers.

Provides :func:`raise_structured_error` which creates an ``HTTPException``
with a machine-readable ``error_code`` alongside the human-readable
``detail``, and automatically logs the error via structlog.

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
    **context:
        Additional key-value pairs attached to both the log entry and the
        response detail payload.
    """
    getattr(_LOG, log_level)(
        "api_error",
        error_code=error_code,
        status_code=status_code,
        detail=detail,
        **context,
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": detail,
            **context,
        },
    )

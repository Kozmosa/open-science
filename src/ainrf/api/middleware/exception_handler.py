"""Global exception-handling middleware.

Catches unhandled exceptions that escape route handlers and returns a
structured JSON error response that includes the ``request_id`` for
correlation with logs.

``HTTPException`` (4xx/5xx raised intentionally by routes) and
``asyncio.CancelledError`` are intentionally **not** caught — FastAPI
handles the former, and swallowing the latter breaks cancellation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_LOG = structlog.get_logger(__name__).bind(component="exception_handler")


def build_exception_handler_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Return middleware that converts unhandled exceptions to structured 500s."""

    async def exception_handler_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except HTTPException:
            raise  # FastAPI handles these natively
        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception:
            request_id = getattr(request.state, "request_id", "-")
            _LOG.error(
                "unhandled_exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error_code": "INTERNAL_ERROR",
                    "message": "An internal error occurred. Please retry or contact support.",
                    "request_id": request_id,
                },
            )

    return exception_handler_middleware

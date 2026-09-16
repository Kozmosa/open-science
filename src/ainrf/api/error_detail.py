"""Coded error detail for domain errors surfaced to HTTP clients."""

from __future__ import annotations


def coded_detail(exc: Exception, surface_message: str | None = None) -> str | dict[str, str]:
    """Pair a stable domain error code with its canonical English message.

    ``surface_message`` is provided by branches that deliberately replace the
    exception text with a generic surface (resource IDs are not user copy);
    ``None`` keeps the exception's own message for permission and conflict
    errors.  Uncoded errors keep the plain string detail so unmapped internal
    errors stay backwards compatible and degrade gracefully in the client.
    """

    code = getattr(exc, "code", "")
    if not isinstance(code, str) or not code:
        message = surface_message if surface_message is not None else str(exc)
        return message
    message = surface_message if surface_message is not None else str(exc)
    return {"code": code, "message": message}

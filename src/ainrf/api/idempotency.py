"""HTTP transport validation for durable domain idempotency keys.

The header is the public contract.  A compatibility request body may carry the
same key while older clients migrate, but the two transports must never choose
different durable operations.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ainrf.domain_telemetry import record_deprecated_route, record_idempotency_event

_MAX_IDEMPOTENCY_KEY_LENGTH = 256


def require_idempotency_key(request: Request, body_key: object | None = None) -> str:
    """Return one normalized request key or reject an ambiguous mutation."""

    state_root = request.app.state.api_config.state_root
    if body_key is not None:
        path_parts = [part for part in request.url.path.split("/") if part]
        if path_parts and path_parts[0] in {"api", "v1"}:
            path_parts.pop(0)
        route_group = path_parts[0] if path_parts else "other"
        record_deprecated_route(
            route=f"{route_group}.idempotency_key",
            replacement="Idempotency-Key header",
            state_root=state_root,
        )
    if body_key is not None and not isinstance(body_key, str):
        record_idempotency_event("invalid", scope=request.url.path, state_root=state_root)
        raise HTTPException(status_code=422, detail="idempotency_key must be a string")
    header_value = request.headers.get("Idempotency-Key")
    header_key = header_value.strip() if header_value is not None else None
    normalized_body_key = body_key.strip() if isinstance(body_key, str) else None
    if header_key and normalized_body_key and header_key != normalized_body_key:
        record_idempotency_event("conflict", scope=request.url.path, state_root=state_root)
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key header and body field must match",
        )
    key = header_key or normalized_body_key
    if not key:
        record_idempotency_event("missing", scope=request.url.path, state_root=state_root)
        raise HTTPException(status_code=409, detail="Idempotency-Key is required")
    if len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        record_idempotency_event(
            "invalid",
            scope=request.url.path,
            idempotency_key=key,
            state_root=state_root,
        )
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    record_idempotency_event(
        "accepted",
        scope=request.url.path,
        idempotency_key=key,
        state_root=state_root,
    )
    return key

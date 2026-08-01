"""HTTP header validation for durable domain idempotency keys."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ainrf.domain_telemetry import record_idempotency_event

_MAX_IDEMPOTENCY_KEY_LENGTH = 256


def require_idempotency_key(request: Request) -> str:
    """Return one normalized header key or reject the mutation."""

    state_root = request.app.state.api_config.state_root
    header_value = request.headers.get("Idempotency-Key")
    header_key = header_value.strip() if header_value is not None else None
    key = header_key
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

from __future__ import annotations

import urllib.parse
from typing import Any

REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api_key",
        "token",
        "refresh_token",
        "access_token",
        "password",
        "secret",
        "private_key",
        "ssh_key",
    }
)

_REDACTED: str = "[REDACTED]"


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a new dict with sensitive header values replaced by ``[REDACTED]``.

    Matching is case-insensitive.
    """
    return {
        key: _REDACTED if key.lower() in REDACTED_KEYS else value for key, value in headers.items()
    }


def redact_query_string(qs: str) -> str:
    """Return a query string with sensitive parameter values replaced by ``[REDACTED]``.

    Matching is case-insensitive. Parameters without values are preserved.
    """
    if not qs:
        return qs
    pairs = urllib.parse.parse_qsl(qs, keep_blank_values=True)
    redacted = [(key, _REDACTED if key.lower() in REDACTED_KEYS else value) for key, value in pairs]
    return urllib.parse.urlencode(redacted)


def redact_dict(data: dict, keys: frozenset[str] | None = None) -> dict:
    """Return a new dict with values redacted for matching keys recursively.

    If ``keys`` is not provided, ``REDACTED_KEYS`` is used. Matching is
    case-insensitive.
    """
    target_keys = REDACTED_KEYS if keys is None else keys
    return _redact_value(data, target_keys)


def _redact_value(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: (_REDACTED if key.lower() in keys else _redact_value(nested, keys))
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, keys) for item in value]
    return value

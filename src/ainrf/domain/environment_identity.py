"""Canonical Environment connection identity helpers.

An Environment ID becomes a durable execution reference once a Workspace or
Task points at it.  Human-facing connection metadata may change, but the
endpoint identity behind that ID must not silently become another host.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_connection_object(connection: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe canonical copy of an Environment connection object."""

    if any(not isinstance(key, str) for key in connection):
        raise ValueError("Environment connection keys must be strings")
    try:
        encoded = json.dumps(
            dict(connection),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Environment connection must be JSON serializable") from exc
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):  # pragma: no cover - json object invariant
        raise ValueError("Environment connection must be a JSON object")
    return {str(key): value for key, value in decoded.items()}


def canonical_connection_json(connection: Mapping[str, object]) -> str:
    """Serialize a validated connection object with a stable representation."""

    return json.dumps(
        canonical_connection_object(connection),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def environment_connection_fingerprint(connection: Mapping[str, object]) -> str:
    """Hash only the fields that establish an execution endpoint identity."""

    normalized = canonical_connection_object(connection)
    identity = {
        "auth_kind": _text_or_default(normalized.get("auth_kind"), "ssh_key"),
        "host": _text_or_default(normalized.get("host"), ""),
        "identity_file": _optional_text(normalized.get("identity_file")),
        "port": _port_or_default(normalized.get("port"), 22),
        "proxy_command": _optional_text(normalized.get("proxy_command")),
        "proxy_jump": _optional_text(normalized.get("proxy_jump")),
        "ssh_options": _string_mapping(normalized.get("ssh_options")),
        "user": _text_or_default(normalized.get("user"), "root"),
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _text_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _port_or_default(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1 <= value <= 65535 else default
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if 1 <= parsed <= 65535 else default
    return default


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))
    }

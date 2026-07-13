"""Viewer-safe redaction for durable Task output projections.

Task output is retained verbatim as execution evidence so an owner or an
administrator can diagnose a runtime after the fact.  A Project collaborator,
however, is entitled to the shared dialogue rather than credentials or any
tenant filesystem detail that a tool happened to print.  This module is a
read-side policy only: it never changes the durable ``task_outputs`` rows.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import cast

_REDACTED_SECRET = "[REDACTED]"
_REDACTED_PATH = "[REDACTED_PATH]"

_SENSITIVE_FIELD_PARTS = (
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "ssh_key",
    "cookie",
)
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "access_token",
        "refresh_token",
        "token",
        "x_api_key",
        "key",
    }
)
_SENSITIVE_FIELD_SUFFIXES = (
    "_api_key",
    "_access_key",
    "_auth_token",
    "_access_token",
    "_refresh_token",
    "_password",
    "_private_key",
    "_secret",
    "_ssh_key",
)
_SENSITIVE_FIELD_TOKENS = frozenset(
    {
        "api",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "key",
        "password",
        "private",
        "secret",
        "ssh",
        "token",
        "tokens",
    }
)

# The patterns intentionally redact *all* absolute filesystem paths from a
# shared projection.  An arbitrary absolute path cannot safely be classified
# as public at this boundary, and this avoids coupling read authorization to a
# particular production tenant-root layout.  The lookbehind excludes URL
# scheme slashes (``https://…``).
_ABSOLUTE_PATH = re.compile(r"(?<![:/])/(?:[^\s'\"`<>()\[\]{},;]+)")
_AUTHORIZATION_VALUE = re.compile(
    r"""(?ix)\b(?:proxy-)?authorization\b\s*[:=]\s*(?:bearer\s+)?[^\s,;\]\}"']+"""
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<key>
        [\"']?(?:
            [a-z][a-z0-9_]*?(?:api_key|access_key|auth_token|access_token|refresh_token|password|private_key|secret|ssh_key)
            |api[ _-]?key|access[ _-]?token|refresh[ _-]?token
            |password|secret|credential|private[ _-]?key|ssh[ _-]?key|token
        )[\"']?
    )
    (?P<separator>\s*(?:=|:)\s*)
    (?P<value>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s,;}\]]+)
    """
)
_FIELD_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<key>[\"']?[a-z][a-z0-9_. -]{0,127}[\"']?)
    (?P<separator>\s*(?:=|:)\s*)
    (?P<value>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s,;}\]]+)
    """
)
_SENSITIVE_FLAG = re.compile(
    r"""(?ix)
    (?P<key>--?(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|password|secret|credential|private[ _-]?key|ssh[ _-]?key|token))
    (?P<separator>\s+|=)
    (?P<value>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s,;}\]]+)
    """
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KNOWN_TOKEN_LITERAL = re.compile(
    r"(?i)\b(?:sk|rk|ghp|gho|ghu|ghs|github_pat|xox[baprs])[-_][A-Za-z0-9._=-]{8,}\b"
)
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?ix)(?P<key>(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)=)(?P<value>[^&#\s]+)"
)


def redact_task_output_for_viewer(content: str) -> str:
    """Return a shared-viewer-safe representation of one durable output item.

    Structured engine events are recursively inspected so sensitive values in
    nested payloads and environment maps cannot survive behind an unrelated
    top-level ``content`` field.  Plain-text output receives the same secret
    and path rules.  If a valid JSON value does not need redaction, its source
    text is returned unchanged to preserve existing compatibility formatting.
    """

    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return _redact_text(content)

    redacted = _redact_json_value(decoded)
    if redacted == decoded:
        return content
    return json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))


def _redact_json_value(value: object, *, field_name: str = "", depth: int = 0) -> object:
    if _is_sensitive_field_name(field_name):
        return _REDACTED_SECRET
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _redact_json_value(nested, field_name=str(key), depth=depth + 1)
            for key, nested in mapping.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item, field_name=field_name, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_embedded_json(value, depth=depth)
    return value


def _is_sensitive_field_name(field_name: str) -> bool:
    normalized = _normalize_field_name(field_name)
    tokens = frozenset(token for token in normalized.split("_") if token)
    return (
        normalized in _SENSITIVE_FIELD_NAMES
        or normalized.endswith(_SENSITIVE_FIELD_SUFFIXES)
        or any(part in normalized for part in _SENSITIVE_FIELD_PARTS)
        or any(token in _SENSITIVE_FIELD_TOKENS for token in tokens)
    )


def _normalize_field_name(field_name: str) -> str:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", field_name)
    return camel_split.replace("-", "_").replace(" ", "_").lower()


def _redact_text(value: str) -> str:
    """Redact secret-shaped text and arbitrary absolute filesystem paths."""

    redacted = _AUTHORIZATION_VALUE.sub("Authorization: " + _REDACTED_SECRET, value)
    redacted = _SENSITIVE_ASSIGNMENT.sub(_redact_assignment, redacted)
    redacted = _FIELD_ASSIGNMENT.sub(_redact_sensitive_field_assignment, redacted)
    redacted = _SENSITIVE_FLAG.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}{_REDACTED_SECRET}",
        redacted,
    )
    redacted = _BEARER_TOKEN.sub("Bearer " + _REDACTED_SECRET, redacted)
    redacted = _KNOWN_TOKEN_LITERAL.sub(_REDACTED_SECRET, redacted)
    redacted = _SENSITIVE_QUERY_VALUE.sub(
        lambda match: f"{match.group('key')}{_REDACTED_SECRET}", redacted
    )
    return _ABSOLUTE_PATH.sub(_REDACTED_PATH, redacted)


def _redact_sensitive_field_assignment(match: re.Match[str]) -> str:
    """Redact camelCase and other tokenized field names in plain text."""

    raw_key = match.group("key")
    field_name = raw_key.strip("\"'")
    if not _is_sensitive_field_name(field_name):
        return match.group(0)
    return _redact_assignment(match)


def _redact_assignment(match: re.Match[str]) -> str:
    """Keep a serialized JSON/string value syntactically valid after masking."""

    value = match.group("value")
    if value.startswith('"'):
        replacement = json.dumps(_REDACTED_SECRET)
    elif value.startswith("'"):
        replacement = f"'{_REDACTED_SECRET}'"
    else:
        replacement = _REDACTED_SECRET
    return f"{match.group('key')}{match.group('separator')}{replacement}"


def _redact_embedded_json(value: str, *, depth: int) -> str:
    """Inspect an object/array serialized inside an engine event string.

    Some adapters put a complete tool payload in a nominally plain ``content``
    field.  Decode only JSON containers and cap nesting, so an adversarial
    stream cannot turn viewer projection into an unbounded parser loop.
    """

    redacted_text = _redact_text(value)
    candidate = redacted_text.strip()
    if not candidate.startswith(("{", "[")):
        return redacted_text
    # Do not let a deliberately nested sequence of JSON-encoded strings turn
    # the projection boundary into an unbounded recursive parser.  Returning
    # the raw string at the limit could leave a secret in a deeper container,
    # so fail closed for a JSON-shaped embedded payload instead.
    if depth >= 8:
        return _REDACTED_SECRET
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        return redacted_text
    if not isinstance(decoded, (dict, list)):
        return redacted_text
    redacted = _redact_json_value(decoded, depth=depth + 1)
    if redacted == decoded:
        return redacted_text
    serialized = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]
    return f"{leading}{serialized}{trailing}"

"""Read-only admin audit access to unmapped legacy domain records.

The importer keeps records it cannot safely map instead of converting them
into writable v2 objects.  This module intentionally exposes only inspection
operations so an administrator can reconcile historical Sessions without
turning an archived payload into a new Task or Session write path.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import cast

from ainrf.db import connect, run_pending

_REDACTED = "[redacted]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "credential",
    "identity",
    "password",
    "private_key",
    "secret",
    "token",
)


class LegacyDomainRecordAuditService:
    """Read archived legacy records without granting a mutation capability."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_records(
        self,
        *,
        run_id: str | None = None,
        record_type: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, object]], bool, str | None]:
        """List immutable audit metadata, excluding archived payloads."""

        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type)
        if cursor:
            clauses.append("legacy_record_id < ?")
            params.append(cursor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""SELECT legacy_record_id, run_id, record_type, source_path,
                           source_record_id, source_payload_sha256, reason, created_at
                      FROM legacy_domain_records {where}
                     ORDER BY legacy_record_id DESC LIMIT ?""",
                (*params, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = str(visible[-1]["legacy_record_id"]) if has_more and visible else None
        return [self._summary(row) for row in visible], has_more, next_cursor

    def inspect_record(self, legacy_record_id: str) -> dict[str, object]:
        """Return one archived payload for an administrator-only audit view."""

        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT legacy_record_id, run_id, record_type, payload_json, source_path,
                           source_record_id, source_payload_sha256, reason, created_at
                      FROM legacy_domain_records WHERE legacy_record_id = ?""",
                (legacy_record_id,),
            ).fetchone()
        if row is None:
            raise LookupError(legacy_record_id)
        result = self._summary(row)
        result["payload"] = _redact_payload(_decode_payload(row["payload_json"]))
        return result

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, object]:
        return {
            "legacy_record_id": str(row["legacy_record_id"]),
            "run_id": str(row["run_id"]),
            "record_type": str(row["record_type"]),
            "source_path": _optional_str(row["source_path"]),
            "source_record_id": _optional_str(row["source_record_id"]),
            "source_payload_sha256": _optional_str(row["source_payload_sha256"]),
            "reason": _optional_str(row["reason"]),
            "created_at": str(row["created_at"]),
        }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _decode_payload(value: object) -> object:
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"invalid_payload_json": True}


def _redact_payload(value: object, *, field_name: str = "") -> object:
    """Recursively preserve audit shape while removing credential material."""

    normalized_name = field_name.lower()
    if any(part in normalized_name for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _redact_payload(item, field_name=str(key)) for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item, field_name=field_name) for item in value]
    return value

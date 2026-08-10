"""Durable provider-oriented literature tracking service.

The queue transport is deliberately outside this module.  Every externally
visible state transition is first committed to SQLite, which means a worker or
Redis restart never decides whether a paper, a check, or an LLM request exists.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from ainrf.db.connection import connect
from ainrf.db.migration import run_pending
from ainrf.literature.attempts import (
    ExternalCallAttempt,
    request_fingerprint as request_fingerprint_for_attempt,
)

_SUMMARY_RECIPE_VERSION = "v1"
_DEFAULT_SUMMARY_MODEL = "claude-sonnet-4-6"
logger = structlog.get_logger(__name__).bind(component="literature-tracking")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _non_empty_evidence(value: object) -> bool:
    """Return whether a persisted evidence field carries meaningful data."""

    if isinstance(value, bytes):
        return bool(value)
    return isinstance(value, str) and bool(value.strip())


def _payload_hash_matches(payload: object, response_hash: object) -> bool:
    """Return whether a persisted text payload matches its durable hash."""

    return bool(
        isinstance(payload, str)
        and payload.strip()
        and isinstance(response_hash, str)
        and response_hash.strip()
        and hashlib.sha256(payload.encode()).hexdigest() == response_hash
    )


def _snapshot_body_hash_matches(snapshot: sqlite3.Row | dict[str, Any] | None) -> bool:
    """Return whether a persisted RSS body matches its durable body hash."""

    if snapshot is None:
        return False
    body = snapshot["body"]
    if isinstance(body, memoryview):
        body = body.tobytes()
    if not isinstance(body, bytes) or not body:
        return False
    body_hash = snapshot["body_hash"]
    return bool(
        isinstance(body_hash, str)
        and body_hash.strip()
        and hashlib.sha256(body).hexdigest() == body_hash
    )


def _snapshot_has_replay_evidence(snapshot: sqlite3.Row | dict[str, Any] | None) -> bool:
    """Return whether a raw RSS snapshot is complete enough for replay."""

    return _snapshot_body_hash_matches(snapshot)


def canonical_arxiv_id(value: str) -> tuple[str, str]:
    """Return base and version IDs without corrupting old-style arXiv names."""
    text = value.strip().rstrip("/").split("/")[-1]
    if "v" in text:
        base, marker, version = text.rpartition("v")
        if marker and base and version.isdecimal():
            return base, f"v{version}"
    return text, "v1"


@dataclass(frozen=True, slots=True)
class DiscoveredPaper:
    provider: str
    external_id: str
    provider_version: str
    title: str
    authors: list[str]
    abstract: str
    primary_category: str
    categories: list[str]
    published_at: str | None
    updated_at: str | None
    source_url: str
    pdf_url: str
    announce_type: str = "new"
    announced_at: str | None = None


@dataclass(frozen=True, slots=True)
class WorkItem:
    work_item_id: str
    kind: str
    payload: dict[str, Any]
    attempt_count: int = 1


class LiteratureIdempotencyConflictError(ValueError):
    """Raised when one caller key is reused for different Literature input."""


class LiteratureTrackingService:
    """Persistence, matching and durable workflow operations for literature."""

    def __init__(self, state_root: Path | str) -> None:
        self._state_root = Path(state_root)
        self._db_path = self._state_root / "runtime" / "literature.sqlite3"

    @property
    def state_root(self) -> Path:
        """Shared runtime root used by planners and durable worker helpers."""
        return self._state_root

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            run_pending(conn, "literature")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def begin_api_attempt(
        self,
        *,
        provider: str,
        operation: str,
        request: object,
        check_id: str | None = None,
        work_item_id: str | None = None,
        attempt_number: int = 1,
    ) -> ExternalCallAttempt:
        """Create or reuse the durable row for one concrete external call.

        The request fingerprint is stable across process retries while the
        deterministic attempt ID additionally binds it to a durable work-item
        claim.  ``INSERT OR IGNORE`` makes duplicate delivery of one claim
        idempotent without turning Redis or an in-process lock into authority.
        """

        provider = provider.strip()
        operation = operation.strip()
        if not provider or not operation:
            raise ValueError("provider and operation are required")
        if attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        request_fingerprint = request_fingerprint_for_attempt(provider, operation, request)
        identity = "|".join(
            (
                work_item_id or "unbound",
                provider,
                operation,
                request_fingerprint,
                str(attempt_number),
            )
        )
        attempt_id = f"attempt_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_api_attempts (
                    attempt_id, check_id, work_item_id, provider, operation,
                    request_fingerprint, attempt_number, state, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)
                """,
                (
                    attempt_id,
                    check_id,
                    work_item_id,
                    provider,
                    operation,
                    request_fingerprint,
                    attempt_number,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to persist Literature API attempt")
        return self._api_attempt_dict(row)

    def record_api_response(
        self,
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> ExternalCallAttempt:
        """Persist that a response arrived before downstream parsing/storage."""

        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = 'response_received', status_code = ?, response_hash = ?,
                    response_payload = COALESCE(?, response_payload),
                    retry_after_seconds = COALESCE(?, retry_after_seconds),
                    response_received_at = COALESCE(response_received_at, ?),
                    error_kind = NULL, error_message = NULL
                WHERE attempt_id = ? AND state IN ('started', 'response_received')
                """,
                (
                    status_code,
                    response_hash,
                    response_payload,
                    retry_after_seconds,
                    now,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"API attempt cannot receive a response: {attempt_id}")
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Literature API attempt not found: {attempt_id}")
        return self._api_attempt_dict(row)

    @staticmethod
    def _attempt_has_response_evidence(
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        response_hash: str | None = None,
    ) -> bool:
        """Check the durable evidence required before response persistence.

        A non-empty provider hash without raw payload is durable response
        evidence for providers that intentionally do not retain bodies.  When
        a payload or RSS snapshot is present, its bytes must match the stored
        hash before the response boundary can advance.  Empty strings are
        deliberately not treated as evidence; this prevents callers from
        manufacturing a boundary with placeholder fields.
        """

        stored_hash = response_hash or row["response_hash"]
        payload = row["response_payload"]
        snapshot = conn.execute(
            """
            SELECT body, body_hash FROM literature_source_snapshots
            WHERE attempt_id = ? LIMIT 1
            """,
            (row["attempt_id"],),
        ).fetchone()
        if _non_empty_evidence(payload):
            if not _payload_hash_matches(payload, stored_hash):
                return False
            if response_hash is not None and row["response_hash"] != response_hash:
                return False
            if snapshot is not None:
                if not _snapshot_body_hash_matches(snapshot):
                    return False
                if snapshot["body_hash"] != stored_hash:
                    return False
            return True
        if _snapshot_body_hash_matches(snapshot):
            snapshot_hash = snapshot["body_hash"]
            if _non_empty_evidence(stored_hash) and stored_hash != snapshot_hash:
                return False
            return True
        if snapshot is not None:
            return False
        return _non_empty_evidence(stored_hash)

    @staticmethod
    def _attempt_has_replay_evidence(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
        """Return whether an attempt contains verified raw evidence for replay."""

        payload = row["response_payload"]
        snapshot = conn.execute(
            """
            SELECT body, body_hash FROM literature_source_snapshots
            WHERE attempt_id = ? LIMIT 1
            """,
            (row["attempt_id"],),
        ).fetchone()
        if _non_empty_evidence(payload):
            if not _payload_hash_matches(payload, row["response_hash"]):
                return False
            return snapshot is None or (
                _snapshot_body_hash_matches(snapshot)
                and snapshot["body_hash"] == row["response_hash"]
            )
        if not _snapshot_body_hash_matches(snapshot):
            return False
        snapshot_hash = snapshot["body_hash"]
        return (
            not _non_empty_evidence(row["response_hash"]) or row["response_hash"] == snapshot_hash
        )

    @staticmethod
    def _promote_attempt_with_replay_evidence(
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        snapshot: sqlite3.Row | None,
        *,
        now: str,
    ) -> sqlite3.Row:
        """Promote an abandoned attempt through both durable response states.

        Reconciliation runs inside its caller's transaction.  Keeping the
        intermediate ``response_received`` update explicit satisfies the
        lifecycle trigger and makes a crash roll back both transitions.
        """

        attempt_id = str(row["attempt_id"])
        if row["state"] == "started":
            snapshot_status = snapshot["status_code"] if snapshot is not None else None
            snapshot_hash = snapshot["body_hash"] if snapshot is not None else None
            conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = 'response_received',
                    status_code = COALESCE(status_code, ?),
                    response_hash = COALESCE(response_hash, ?),
                    response_received_at = COALESCE(response_received_at, ?),
                    error_kind = NULL, error_message = NULL
                WHERE attempt_id = ? AND state = 'started'
                """,
                (snapshot_status, snapshot_hash, now, attempt_id),
            )
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Literature API attempt not found: {attempt_id}")
        if row["state"] == "response_received":
            if not LiteratureTrackingService._attempt_has_response_evidence(conn, row):
                raise RuntimeError(
                    f"API attempt cannot persist without durable response evidence: {attempt_id}"
                )
            conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = 'response_persisted',
                    response_persisted_at = COALESCE(response_persisted_at, ?),
                    error_kind = NULL, error_message = NULL
                WHERE attempt_id = ? AND state = 'response_received'
                """,
                (now, attempt_id),
            )
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Literature API attempt not found: {attempt_id}")
        return row

    def mark_api_response_persisted(
        self,
        attempt_id: str,
        *,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> ExternalCallAttempt:
        """Record that a received source response reached durable SQLite state."""

        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Literature API attempt not found: {attempt_id}")
            if row["state"] not in {"response_received", "response_persisted"}:
                raise RuntimeError(f"API attempt response is not ready to persist: {attempt_id}")
            if not self._attempt_has_response_evidence(conn, row):
                raise RuntimeError(
                    f"API attempt cannot persist without durable response evidence: {attempt_id}"
                )
            cursor = conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = 'response_persisted',
                    response_persisted_at = COALESCE(response_persisted_at, ?),
                    error_kind = ?, error_message = ?
                WHERE attempt_id = ? AND state IN ('response_received', 'response_persisted')
                """,
                (
                    now,
                    error_kind[:100] if error_kind else None,
                    error_message[:1000] if error_message else None,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"API attempt response is not ready to persist: {attempt_id}")
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Literature API attempt not found: {attempt_id}")
        return self._api_attempt_dict(row)

    def mark_api_succeeded(
        self,
        attempt_id: str,
        *,
        response_hash: str | None = None,
        status_code: int | None = None,
    ) -> ExternalCallAttempt:
        """Finalize a call after its response or durable side effect succeeds."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Literature API attempt not found: {attempt_id}")
            if row["state"] == "succeeded":
                if (
                    row["response_persisted_at"] is None
                    or row["response_received_at"] is None
                    or row["completed_at"] is None
                ):
                    raise RuntimeError(
                        f"API attempt succeeded without persisted response evidence: {attempt_id}"
                    )
                if not self._attempt_has_response_evidence(conn, row, response_hash=response_hash):
                    raise RuntimeError(
                        f"API attempt succeeded without durable response evidence: {attempt_id}"
                    )
                if status_code is not None and row["status_code"] != status_code:
                    raise RuntimeError(
                        f"API attempt success replay mismatches status: {attempt_id}"
                    )
                if response_hash is not None and row["response_hash"] != response_hash:
                    raise RuntimeError(f"API attempt success replay mismatches hash: {attempt_id}")
                return self._api_attempt_dict(row)
            if row["state"] != "response_persisted":
                raise RuntimeError(
                    f"API attempt cannot succeed before persisted response: {attempt_id}"
                )
            if row["response_persisted_at"] is None or row["response_received_at"] is None:
                raise RuntimeError(
                    f"API attempt persisted state lacks response timestamps: {attempt_id}"
                )
            if not self._attempt_has_response_evidence(conn, row, response_hash=response_hash):
                raise RuntimeError(
                    f"API attempt cannot succeed without durable response evidence: {attempt_id}"
                )
            now = _now()
            cursor = conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = 'succeeded', status_code = COALESCE(?, status_code),
                    response_hash = COALESCE(?, response_hash),
                    completed_at = COALESCE(completed_at, ?),
                    error_kind = NULL, error_message = NULL
                WHERE attempt_id = ? AND state = 'response_persisted'
                """,
                (status_code, response_hash, now, attempt_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"API attempt cannot succeed: {attempt_id}")
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Literature API attempt not found: {attempt_id}")
        return self._api_attempt_dict(row)

    def latest_api_attempt(
        self,
        *,
        work_item_id: str,
        provider: str,
        operation: str | None,
        with_response_evidence: bool = False,
    ) -> ExternalCallAttempt | None:
        """Return the newest attempt that can be inspected during recovery."""

        operation_clause = " AND operation = ?" if operation is not None else ""
        params: tuple[object, ...] = (
            (work_item_id, provider, operation)
            if operation is not None
            else (work_item_id, provider)
        )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM literature_api_attempts
                WHERE work_item_id = ? AND provider = ?
                """
                + operation_clause
                + " ORDER BY attempt_number DESC, started_at DESC"
                + (" LIMIT 1" if not with_response_evidence else ""),
                params,
            ).fetchall()
            for row in rows:
                if not with_response_evidence or self._attempt_has_response_evidence(conn, row):
                    return self._api_attempt_dict(row)
        return None

    def reconcile_stale_api_attempts(
        self, stale_after_seconds: int = 300
    ) -> list[ExternalCallAttempt]:
        """Conservatively classify abandoned calls and promote durable evidence."""

        cutoff = (datetime.now(UTC) - timedelta(seconds=stale_after_seconds)).isoformat()
        reconciled: list[ExternalCallAttempt] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT attempt.* FROM literature_api_attempts AS attempt
                WHERE attempt.state IN ('started', 'response_received')
                  AND attempt.started_at < ?
                ORDER BY attempt.started_at
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                evidence = conn.execute(
                    """
                    SELECT body, body_hash, status_code FROM literature_source_snapshots
                    WHERE attempt_id = ? LIMIT 1
                    """,
                    (row["attempt_id"],),
                ).fetchone()
                now = _now()
                if self._attempt_has_replay_evidence(conn, row):
                    self._promote_attempt_with_replay_evidence(
                        conn,
                        row,
                        evidence,
                        now=now,
                    )
                else:
                    conn.execute(
                        """
                        UPDATE literature_api_attempts
                        SET state = 'unknown', error_kind = 'stale_attempt',
                            error_message = 'Worker stopped before response evidence was durable',
                            completed_at = COALESCE(completed_at, ?)
                        WHERE attempt_id = ? AND state IN ('started', 'response_received')
                        """,
                        (now, row["attempt_id"]),
                    )
                updated = conn.execute(
                    "SELECT * FROM literature_api_attempts WHERE attempt_id = ?",
                    (row["attempt_id"],),
                ).fetchone()
                if updated is not None:
                    reconciled.append(self._api_attempt_dict(updated))
        return reconciled

    def mark_api_retryable_failure(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
    ) -> ExternalCallAttempt:
        """Finalize a failed call that may be retried after a cooldown."""

        return self._finish_api_attempt(
            attempt_id,
            state="retryable_failure",
            error_kind=error_kind,
            error_message=error_message,
            retry_after_seconds=retry_after_seconds,
            status_code=status_code,
        )

    def mark_api_definitive_failure(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        status_code: int | None = None,
    ) -> ExternalCallAttempt:
        """Finalize a call that must not be automatically retried."""

        return self._finish_api_attempt(
            attempt_id,
            state="definitive_failure",
            error_kind=error_kind,
            error_message=error_message,
            status_code=status_code,
        )

    def mark_api_unknown(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        retry_after_seconds: int | None = None,
    ) -> ExternalCallAttempt:
        """Record timeout/cancellation where the request may have been sent."""

        return self._finish_api_attempt(
            attempt_id,
            state="unknown",
            error_kind=error_kind,
            error_message=error_message,
            retry_after_seconds=retry_after_seconds,
        )

    def api_attempt(self, attempt_id: str) -> ExternalCallAttempt | None:
        """Read one durable attempt for recovery and diagnostics."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        return self._api_attempt_dict(row) if row is not None else None

    def api_attempt_has_replay_evidence(self, attempt_id: str) -> bool:
        """Return whether an attempt has raw payload/snapshot evidence to replay."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                return False
            return self._attempt_has_replay_evidence(conn, row)

    def list_api_attempts(
        self,
        *,
        work_item_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> list[ExternalCallAttempt]:
        """List durable attempts for recovery diagnostics without exposing SQL."""

        clauses: list[str] = []
        params: list[str] = []
        if work_item_id is not None:
            clauses.append("work_item_id = ?")
            params.append(work_item_id)
        if request_fingerprint is not None:
            clauses.append("request_fingerprint = ?")
            params.append(request_fingerprint)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM literature_api_attempts"
                + where
                + " ORDER BY started_at, attempt_number",
                params,
            ).fetchall()
        return [self._api_attempt_dict(row) for row in rows]

    def _finish_api_attempt(
        self,
        attempt_id: str,
        *,
        state: str,
        error_kind: str,
        error_message: str,
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
    ) -> ExternalCallAttempt:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE literature_api_attempts
                SET state = ?, status_code = COALESCE(?, status_code),
                    retry_after_seconds = ?, error_kind = ?, error_message = ?,
                    completed_at = COALESCE(completed_at, ?)
                WHERE attempt_id = ? AND state IN (
                    'started', 'response_received', 'response_persisted',
                    'retryable_failure', 'definitive_failure', 'unknown'
                )
                """,
                (
                    state,
                    status_code,
                    retry_after_seconds,
                    error_kind[:100],
                    error_message[:1000],
                    now,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"API attempt cannot transition to {state}: {attempt_id}")
            row = conn.execute(
                "SELECT * FROM literature_api_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Literature API attempt not found: {attempt_id}")
        return self._api_attempt_dict(row)

    def create_topic(
        self,
        *,
        user_id: str,
        label: str,
        include_terms: list[str],
        exclude_terms: list[str],
        categories: list[str],
    ) -> dict[str, Any]:
        self._validate_topic(label, categories)
        now = _now()
        topic_id = _identifier("topic")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO literature_topics (
                    topic_id, user_id, label, include_terms_json, exclude_terms_json,
                    categories_json, status, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    topic_id,
                    user_id,
                    label.strip(),
                    json.dumps(self._clean_terms(include_terms)),
                    json.dumps(self._clean_terms(exclude_terms)),
                    json.dumps(sorted(set(categories))),
                    now,
                    now,
                ),
            )
        return self.get_topic(user_id, topic_id)

    def list_topics(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM literature_topics WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [self._topic_dict(row) for row in rows]

    def get_topic(self, user_id: str, topic_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_topics WHERE topic_id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Topic not found")
        return self._topic_dict(row)

    def update_topic(self, user_id: str, topic_id: str, body: dict[str, Any]) -> dict[str, Any]:
        current = self.get_topic(user_id, topic_id)
        label = str(body.get("label", current["label"])).strip()
        categories = body.get("categories", current["categories"])
        if not isinstance(categories, list):
            raise ValueError("categories must be a list")
        self._validate_topic(label, categories)
        include_terms = body.get("include_terms", current["include_terms"])
        exclude_terms = body.get("exclude_terms", current["exclude_terms"])
        if not isinstance(include_terms, list) or not isinstance(exclude_terms, list):
            raise ValueError("terms must be lists")
        is_active = bool(body.get("is_active", current["is_active"]))
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE literature_topics
                SET label = ?, include_terms_json = ?, exclude_terms_json = ?, categories_json = ?,
                    is_active = ?, status = ?, updated_at = ?
                WHERE topic_id = ? AND user_id = ?
                """,
                (
                    label,
                    json.dumps(self._clean_terms(include_terms)),
                    json.dumps(self._clean_terms(exclude_terms)),
                    json.dumps(sorted(set(str(value) for value in categories))),
                    int(is_active),
                    "active" if is_active else "paused",
                    now,
                    topic_id,
                    user_id,
                ),
            )
        return self.get_topic(user_id, topic_id)

    def delete_topic(self, user_id: str, topic_id: str) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM literature_topics WHERE topic_id = ? AND user_id = ?",
                (topic_id, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("Topic not found")

    def sync_legacy_topic(
        self,
        *,
        topic_id: str,
        user_id: str,
        label: str,
        include_terms: list[str],
        categories: list[str],
        is_active: bool,
    ) -> None:
        """Keep legacy subscription IDs as a thin compatibility mapping."""
        now = _now()
        valid_categories = self._clean_terms(categories)
        active = bool(is_active and valid_categories)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO literature_topics (
                    topic_id, user_id, label, include_terms_json, exclude_terms_json, categories_json,
                    status, is_active, legacy_subscription_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    label=excluded.label, include_terms_json=excluded.include_terms_json,
                    categories_json=excluded.categories_json, status=excluded.status,
                    is_active=excluded.is_active, updated_at=excluded.updated_at
                """,
                (
                    topic_id,
                    user_id,
                    label,
                    json.dumps(self._clean_terms(include_terms)),
                    json.dumps(valid_categories),
                    "active" if active else "attention_needed",
                    int(active),
                    topic_id,
                    now,
                    now,
                ),
            )

    def preview_topic(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        categories = body.get("categories", [])
        include_terms = body.get("include_terms", [])
        exclude_terms = body.get("exclude_terms", [])
        if not all(isinstance(value, list) for value in (categories, include_terms, exclude_terms)):
            raise ValueError("categories and terms must be lists")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM literature_catalog_papers ORDER BY last_seen_at DESC LIMIT 500"
            ).fetchall()
        matches = [
            row for row in rows if self._matches(row, categories, include_terms, exclude_terms)[0]
        ]
        return {
            "matched_count": len(matches),
            "samples": [self._catalog_dict(row) for row in matches[:5]],
            "local_coverage": {"paper_count": len(rows), "complete": bool(rows)},
            "needs_check": not rows,
        }

    def create_check(
        self,
        *,
        user_id: str,
        topic_ids: list[str] | None,
        trigger: str = "manual",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "topic_ids": sorted(topic_ids) if topic_ids is not None else None,
            "trigger": trigger,
        }
        with self._connect() as conn:
            cached = self._idempotent_result(
                conn, user_id, "literature.check.create", idempotency_key, request
            )
            if cached is not None:
                logger.debug(
                    "literature_check_reused_idempotency",
                    check_id=cached.get("check_id"),
                    trigger=trigger,
                    topic_count=len(topic_ids or []),
                )
                return cached
            if trigger == "scheduled":
                topic_rows = conn.execute(
                    "SELECT * FROM literature_topics WHERE is_active = 1"
                ).fetchall()
            else:
                topic_rows = conn.execute(
                    "SELECT * FROM literature_topics WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            topics = [self._topic_dict(row) for row in topic_rows]
            if topic_ids is not None:
                wanted = set(topic_ids)
                topics = [topic for topic in topics if topic["topic_id"] in wanted]
                if wanted != {topic["topic_id"] for topic in topics}:
                    raise KeyError("Topic not found")
            active = [topic for topic in topics if topic["is_active"]]
            categories = sorted({category for topic in active for category in topic["categories"]})
            if not categories:
                raise ValueError("At least one active topic with an arXiv category is required")
            # An Eastern-date slot avoids a user clicking refresh repeatedly creating
            # separate requests for the same official daily announcement feed.
            slot = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
            fingerprint = _fingerprint(
                {"provider": "arxiv", "categories": categories, "slot": slot}
            )
            existing = conn.execute(
                "SELECT * FROM literature_checks WHERE request_fingerprint = ?", (fingerprint,)
            ).fetchone()
            if existing is not None:
                result = self._check_dict(existing)
                self._store_idempotency(
                    conn,
                    user_id,
                    "literature.check.create",
                    idempotency_key,
                    request,
                    result,
                )
                logger.debug(
                    "literature_check_reused_daily_scope",
                    check_id=result.get("check_id"),
                    trigger=trigger,
                    category_count=len(categories),
                    categories=categories,
                )
                return result
            now = _now()
            check_id = _identifier("check")
            conn.execute(
                """
                INSERT INTO literature_checks (
                    check_id, user_id, trigger, request_fingerprint, status, window_start,
                    window_end, scheduled_for, created_at
                ) VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?)
                """,
                (check_id, None, trigger, fingerprint, slot, slot, now, now),
            )
            scope_id = _identifier("scope")
            conn.execute(
                """
                INSERT INTO literature_check_scopes (scope_id, check_id, provider, scope_key, status)
                VALUES (?, ?, 'arxiv-rss', ?, 'planned')
                """,
                (scope_id, check_id, "+".join(categories)),
            )
            work_item_id = self._insert_work_item(
                conn,
                kind="fetch_rss",
                idempotency_key=f"fetch-rss:{fingerprint}",
                payload={"check_id": check_id, "scope_id": scope_id, "categories": categories},
            )
            row = conn.execute(
                "SELECT * FROM literature_checks WHERE check_id = ?", (check_id,)
            ).fetchone()
            assert row is not None
            result = self._check_dict(row)
            self._store_idempotency(
                conn,
                user_id,
                "literature.check.create",
                idempotency_key,
                request,
                result,
            )
            logger.debug(
                "literature_check_created",
                check_id=check_id,
                scope_id=scope_id,
                work_item_id=work_item_id,
                trigger=trigger,
                category_count=len(categories),
                categories=categories,
            )
            return result

    def plan_daily_check(self) -> dict[str, Any] | None:
        """Plan one shared daily RSS check for all active user topics."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM literature_topics WHERE is_active = 1 ORDER BY user_id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self.create_check(user_id=str(row["user_id"]), topic_ids=None, trigger="scheduled")

    def list_checks(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM literature_checks WHERE user_id = ? OR user_id IS NULL
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._check_dict(row) for row in rows]

    def get_check(self, user_id: str, check_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_checks WHERE check_id = ? AND (user_id = ? OR user_id IS NULL)",
                (check_id, user_id),
            ).fetchone()
            scopes = conn.execute(
                "SELECT * FROM literature_check_scopes WHERE check_id = ? ORDER BY scope_key",
                (check_id,),
            ).fetchall()
        if row is None:
            raise KeyError("Check not found")
        result = self._check_dict(row)
        result["scopes"] = [dict(scope) for scope in scopes]
        return result

    def overview(self, user_id: str) -> dict[str, Any]:
        today = datetime.now(UTC).date().isoformat()
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN substr(ups.first_seen_at, 1, 10) = ? THEN 1 ELSE 0 END) AS today,
                  SUM(CASE WHEN ups.is_read = 0 AND ups.is_ignored = 0 THEN 1 ELSE 0 END) AS unread,
                  SUM(CASE WHEN ups.is_saved = 1 THEN 1 ELSE 0 END) AS saved,
                  SUM(CASE WHEN ups.latest_seen_version_id != cp.current_version_id THEN 1 ELSE 0 END) AS updated
                FROM literature_user_paper_states ups
                JOIN literature_catalog_papers cp ON cp.paper_id = ups.paper_id
                WHERE ups.user_id = ?
                """,
                (today, user_id),
            ).fetchone()
            current = conn.execute(
                """
                SELECT * FROM literature_checks WHERE user_id = ? AND status IN ('planned', 'checking', 'partial', 'retrying')
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            last = conn.execute(
                "SELECT completed_at FROM literature_checks WHERE user_id = ? AND status = 'completed' ORDER BY completed_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return {
            "last_successful_check_at": last["completed_at"] if last else None,
            "next_scheduled_check_at": None,
            "active_check": self._check_dict(current) if current else None,
            "counts": {
                key: int(counts[key] or 0) for key in ("today", "unread", "saved", "updated")
            },
        }

    def list_papers(
        self,
        user_id: str,
        *,
        view: str = "today",
        topic_id: str | None = None,
        category: str | None = None,
        summary_status: str | None = None,
        has_research_task: bool | None = None,
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        if view not in {"today", "unread", "saved", "updated", "all"}:
            raise ValueError("Unsupported literature view")
        params: list[object] = [user_id]
        clauses = ["ups.user_id = ?", "ups.is_ignored = 0"]
        if view == "today":
            clauses.append("substr(ups.first_seen_at, 1, 10) = ?")
            params.append(datetime.now(UTC).date().isoformat())
        elif view == "unread":
            clauses.append("ups.is_read = 0")
        elif view == "saved":
            clauses.append("ups.is_saved = 1")
        elif view == "updated":
            clauses.append("ups.latest_seen_version_id != cp.current_version_id")
        if topic_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM literature_topic_matches tm WHERE tm.paper_id = cp.paper_id AND tm.topic_id = ?)"
            )
            params.append(topic_id)
        if category:
            clauses.append("cp.primary_category = ?")
            params.append(category)
        if summary_status:
            valid_summary_statuses = {
                "not_requested",
                "queued",
                "generating",
                "completed",
                "stale",
                "failed",
            }
            if summary_status not in valid_summary_statuses:
                raise ValueError("Unsupported summary status")
            if summary_status == "not_requested":
                clauses.append(
                    "NOT EXISTS (SELECT 1 FROM literature_summaries s WHERE s.version_id = cp.current_version_id)"
                )
            elif summary_status == "stale":
                clauses.append(
                    "EXISTS (SELECT 1 FROM literature_summaries s WHERE s.paper_id = cp.paper_id AND s.version_id != cp.current_version_id)"
                )
                clauses.append(
                    "NOT EXISTS (SELECT 1 FROM literature_summaries s WHERE s.version_id = cp.current_version_id)"
                )
            else:
                clauses.append(
                    "EXISTS (SELECT 1 FROM literature_summaries s WHERE s.version_id = cp.current_version_id AND s.status = ?)"
                )
                params.append(summary_status)
        if has_research_task is not None:
            predicate = "EXISTS" if has_research_task else "NOT EXISTS"
            clauses.append(
                f"{predicate} (SELECT 1 FROM literature_research_task_intents intent WHERE intent.user_id = ups.user_id AND intent.paper_id = cp.paper_id)"
            )
        if cursor:
            clauses.append("(ups.last_seen_at, cp.paper_id) < (?, ?)")
            cursor_at, _, cursor_id = cursor.partition("|")
            params.extend([cursor_at, cursor_id])
        params.append(limit + 1)
        query = f"""
            SELECT cp.*, ups.is_read, ups.is_saved, ups.is_ignored, ups.first_seen_at AS user_first_seen_at,
                   ups.last_seen_at AS user_last_seen_at, ups.latest_seen_version_id
            FROM literature_catalog_papers cp
            JOIN literature_user_paper_states ups ON ups.paper_id = cp.paper_id
            WHERE {" AND ".join(clauses)}
            ORDER BY ups.last_seen_at DESC, cp.paper_id DESC LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            items = [self._paper_for_user(conn, user_id, row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            final = rows[limit - 1]
            next_cursor = f"{final['user_last_seen_at']}|{final['paper_id']}"
        return {"items": items, "next_cursor": next_cursor, "total": len(items)}

    def get_paper(self, user_id: str, paper_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            return self._get_paper(conn, user_id, paper_id)

    def update_paper_state(
        self,
        user_id: str,
        paper_id: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        allowed = {"is_read", "is_saved", "is_ignored"}
        updates = {key: int(bool(value)) for key, value in body.items() if key in allowed}
        if not updates:
            raise ValueError("No supported paper state fields provided")
        request = {"paper_id": paper_id, "updates": updates}
        with self._connect() as conn:
            cached = self._idempotent_result(
                conn, user_id, "literature.paper.state", idempotency_key, request
            )
            if cached is not None:
                return cached
            existing = conn.execute(
                "SELECT 1 FROM literature_user_paper_states WHERE user_id = ? AND paper_id = ?",
                (user_id, paper_id),
            ).fetchone()
            if existing is None:
                raise KeyError("Paper not found")
            columns = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE literature_user_paper_states SET {columns}, last_seen_at = ? WHERE user_id = ? AND paper_id = ?",
                [*updates.values(), _now(), user_id, paper_id],
            )
            result = self._get_paper(conn, user_id, paper_id)
            self._store_idempotency(
                conn,
                user_id,
                "literature.paper.state",
                idempotency_key,
                request,
                result,
            )
            return result

    def request_summary(
        self,
        user_id: str,
        paper_id: str,
        language: str = "zh",
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        request = {"paper_id": paper_id, "language": language}
        with self._connect() as conn:
            cached = self._idempotent_result(
                conn, user_id, "literature.summary.request", idempotency_key, request
            )
            if cached is not None:
                return cached
            paper = conn.execute(
                """
                SELECT cp.* FROM literature_catalog_papers cp
                JOIN literature_user_paper_states ups ON ups.paper_id = cp.paper_id
                WHERE cp.paper_id = ? AND ups.user_id = ?
                """,
                (paper_id, user_id),
            ).fetchone()
            if paper is None or not paper["current_version_id"]:
                raise KeyError("Paper not found")
            version = conn.execute(
                "SELECT * FROM literature_paper_versions WHERE version_id = ?",
                (paper["current_version_id"],),
            ).fetchone()
            assert version is not None
            existing = conn.execute(
                """
                SELECT * FROM literature_summaries WHERE version_id = ? AND content_hash = ?
                  AND recipe_version = ? AND model = ? AND language = ?
                """,
                (
                    version["version_id"],
                    version["content_hash"],
                    _SUMMARY_RECIPE_VERSION,
                    _DEFAULT_SUMMARY_MODEL,
                    language,
                ),
            ).fetchone()
            if existing is not None:
                result = self._summary_dict(existing)
                self._store_idempotency(
                    conn,
                    user_id,
                    "literature.summary.request",
                    idempotency_key,
                    request,
                    result,
                )
                logger.debug(
                    "literature_summary_reused",
                    summary_id=result.get("summary_id"),
                    paper_id=paper_id,
                    language=language,
                    status=result.get("status"),
                )
                return result
            now = _now()
            summary_id = _identifier("summary")
            work_id = self._insert_work_item(
                conn,
                kind="summarize",
                idempotency_key=f"summary:{version['version_id']}:{version['content_hash']}:{language}",
                payload={"summary_id": summary_id},
            )
            conn.execute(
                """
                INSERT INTO literature_summaries (
                    summary_id, paper_id, version_id, content_hash, recipe_version, model, language,
                    status, work_item_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    summary_id,
                    paper_id,
                    version["version_id"],
                    version["content_hash"],
                    _SUMMARY_RECIPE_VERSION,
                    _DEFAULT_SUMMARY_MODEL,
                    language,
                    work_id,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM literature_summaries WHERE summary_id = ?", (summary_id,)
            ).fetchone()
            assert row is not None
            result = self._summary_dict(row)
            self._store_idempotency(
                conn,
                user_id,
                "literature.summary.request",
                idempotency_key,
                request,
                result,
            )
            logger.debug(
                "literature_summary_queued",
                summary_id=summary_id,
                work_item_id=work_id,
                paper_id=paper_id,
                version_id=version["version_id"],
                language=language,
            )
            return result

    def get_summary(self, user_id: str, paper_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            accessible = conn.execute(
                "SELECT current_version_id FROM literature_catalog_papers cp JOIN literature_user_paper_states ups ON ups.paper_id = cp.paper_id WHERE cp.paper_id = ? AND ups.user_id = ?",
                (paper_id, user_id),
            ).fetchone()
            if accessible is None:
                raise KeyError("Paper not found")
            row = conn.execute(
                "SELECT * FROM literature_summaries WHERE version_id = ? ORDER BY created_at DESC LIMIT 1",
                (accessible["current_version_id"],),
            ).fetchone()
            stale = None
            if row is None:
                stale = conn.execute(
                    "SELECT * FROM literature_summaries WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
                    (paper_id,),
                ).fetchone()
        if row is not None:
            return self._summary_dict(row)
        if stale is not None:
            result = self._summary_dict(stale)
            result["status"] = "stale"
            return result
        return {"status": "not_requested"}

    def summary_context(self, summary_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.summary_id, s.paper_id, s.version_id, p.title, p.authors_json, p.abstract,
                       p.primary_category, p.published_at
                FROM literature_summaries s
                JOIN literature_catalog_papers p ON p.paper_id = s.paper_id
                WHERE s.summary_id = ?
                """,
                (summary_id,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE literature_summaries SET status = 'generating' WHERE summary_id = ?",
                    (summary_id,),
                )
        return dict(row) if row else None

    def complete_summary(self, summary_id: str, text: str, practice_note: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE literature_summaries SET status = 'completed', summary_text = ?, practice_note = ?,
                  error_message = NULL, completed_at = ? WHERE summary_id = ?
                """,
                (text, practice_note, _now(), summary_id),
            )

    def fail_summary(self, summary_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE literature_summaries SET status = 'failed', error_message = ? WHERE summary_id = ?",
                (error[:1000], summary_id),
            )

    def reconcile_expired_work_items(self) -> None:
        """Recover expired leases without crossing an unknown external-call fence."""

        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT work_item_id FROM literature_work_items
                WHERE status = 'running' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                """,
                (now,),
            ).fetchall()
        for row in rows:
            work_item_id = str(row["work_item_id"])
            with self._connect() as conn:
                attempt_row = conn.execute(
                    """
                    SELECT * FROM literature_api_attempts
                    WHERE work_item_id = ?
                    ORDER BY attempt_number DESC, started_at DESC LIMIT 1
                    """,
                    (work_item_id,),
                ).fetchone()
                snapshot = (
                    conn.execute(
                        """
                        SELECT body, body_hash, status_code
                        FROM literature_source_snapshots
                        WHERE attempt_id = ? LIMIT 1
                        """,
                        (attempt_row["attempt_id"],),
                    ).fetchone()
                    if attempt_row is not None
                    else None
                )
                attempt = self._api_attempt_dict(attempt_row) if attempt_row is not None else None
                replay_evidence = bool(
                    attempt is not None and self._attempt_has_replay_evidence(conn, attempt_row)
                )
                if attempt is not None and attempt.state in {"started", "response_received"}:
                    if replay_evidence:
                        attempt_row = self._promote_attempt_with_replay_evidence(
                            conn,
                            attempt_row,
                            snapshot,
                            now=now,
                        )
                        attempt = self._api_attempt_dict(attempt_row)
                    else:
                        conn.execute(
                            """
                            UPDATE literature_api_attempts
                            SET state = 'unknown', error_kind = 'expired_work_item',
                                error_message = 'Work lease expired before response evidence was durable',
                                completed_at = COALESCE(completed_at, ?)
                            WHERE attempt_id = ? AND state IN ('started', 'response_received')
                            """,
                            (now, attempt.attempt_id),
                        )
                        attempt_row = conn.execute(
                            "SELECT * FROM literature_api_attempts WHERE attempt_id = ?",
                            (attempt.attempt_id,),
                        ).fetchone()
                        if attempt_row is None:
                            raise KeyError(
                                f"Literature API attempt not found: {attempt.attempt_id}"
                            )
                        attempt = self._api_attempt_dict(attempt_row)
                elif (
                    attempt is not None
                    and attempt.state == "response_persisted"
                    and not replay_evidence
                ):
                    conn.execute(
                        """
                        UPDATE literature_api_attempts
                        SET state = 'unknown', error_kind = 'expired_work_item',
                            error_message = 'Response-persisted boundary lacks durable response evidence',
                            completed_at = COALESCE(completed_at, ?)
                        WHERE attempt_id = ? AND state = 'response_persisted'
                        """,
                        (now, attempt.attempt_id),
                    )
                    attempt_row = conn.execute(
                        "SELECT * FROM literature_api_attempts WHERE attempt_id = ?",
                        (attempt.attempt_id,),
                    ).fetchone()
                    if attempt_row is None:
                        raise KeyError(f"Literature API attempt not found: {attempt.attempt_id}")
                    attempt = self._api_attempt_dict(attempt_row)
                blocked = attempt is not None and attempt.state == "unknown" and not replay_evidence
                available_at = now
                if (
                    attempt is not None
                    and attempt.state == "retryable_failure"
                    and attempt.retry_after_seconds is not None
                ):
                    try:
                        retry_at = datetime.fromisoformat(attempt.completed_at or now) + timedelta(
                            seconds=max(0, attempt.retry_after_seconds)
                        )
                        available_at = max(datetime.fromisoformat(now), retry_at).isoformat()
                    except ValueError:
                        available_at = now
                conn.execute(
                    """
                    UPDATE literature_work_items
                    SET status = ?, available_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, last_error = ?, updated_at = ?
                    WHERE work_item_id = ? AND status = 'running'
                    """,
                    (
                        "failed" if blocked else "retrying",
                        available_at,
                        "external call outcome is unknown; manual reconciliation required"
                        if blocked
                        else "expired Literature work lease recovered",
                        now,
                        work_item_id,
                    ),
                )

    def claim_work_item(self, worker_id: str, lease_seconds: int = 120) -> WorkItem | None:
        now = datetime.now(UTC)
        self.reconcile_stale_api_attempts()
        self.reconcile_expired_work_items()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM literature_work_items
                WHERE status IN ('queued', 'retrying') AND available_at <= ?
                  AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                ORDER BY available_at, created_at LIMIT 1
                """,
                (now.isoformat(), now.isoformat()),
            ).fetchone()
            if row is None:
                return None
            lease = (now + timedelta(seconds=lease_seconds)).isoformat()
            updated = conn.execute(
                """
                UPDATE literature_work_items
                SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE work_item_id = ? AND status IN ('queued', 'retrying')
                """,
                (worker_id, lease, now.isoformat(), row["work_item_id"]),
            )
            if updated.rowcount != 1:
                return None
        item = WorkItem(
            row["work_item_id"],
            row["kind"],
            json.loads(row["payload_json"]),
            attempt_count=int(row["attempt_count"]) + 1,
        )
        logger.debug(
            "literature_work_item_claimed",
            work_item_id=item.work_item_id,
            kind=item.kind,
            worker_id=worker_id,
            attempt_count=int(row["attempt_count"]) + 1,
        )
        return item

    def claim_work_item_by_id(
        self, work_item_id: str, worker_id: str, lease_seconds: int = 120
    ) -> WorkItem | None:
        """Claim the durable item named by a broker message exactly once."""
        now = datetime.now(UTC)
        self.reconcile_stale_api_attempts()
        self.reconcile_expired_work_items()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM literature_work_items
                WHERE work_item_id = ? AND status IN ('queued', 'retrying') AND available_at <= ?
                  AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                """,
                (work_item_id, now.isoformat(), now.isoformat()),
            ).fetchone()
            if row is None:
                return None
            lease = (now + timedelta(seconds=lease_seconds)).isoformat()
            cursor = conn.execute(
                """
                UPDATE literature_work_items SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                  attempt_count = attempt_count + 1, updated_at = ?
                WHERE work_item_id = ? AND status IN ('queued', 'retrying')
                """,
                (worker_id, lease, now.isoformat(), work_item_id),
            )
            if cursor.rowcount != 1:
                return None
        item = WorkItem(
            row["work_item_id"],
            row["kind"],
            json.loads(row["payload_json"]),
            attempt_count=int(row["attempt_count"]) + 1,
        )
        logger.debug(
            "literature_work_item_claimed",
            work_item_id=item.work_item_id,
            kind=item.kind,
            worker_id=worker_id,
            attempt_count=int(row["attempt_count"]) + 1,
        )
        return item

    def work_item(self, work_item_id: str) -> WorkItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT work_item_id, kind, payload_json, attempt_count FROM literature_work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkItem(
            row["work_item_id"],
            row["kind"],
            json.loads(row["payload_json"]),
            attempt_count=int(row["attempt_count"]) + 1,
        )

    def persist_rss_snapshot(
        self,
        *,
        attempt_id: str,
        check_id: str,
        scope_id: str,
        body: bytes,
        etag: str | None,
        last_modified: str | None,
        cache_control: str | None,
        status_code: int,
    ) -> dict[str, Any]:
        """Persist raw source evidence before parsing or catalog writes.

        A checking scope keeps its last committed validators until the
        catalog write completes.  That keeps the durable request fingerprint
        applicable to recovery; response ETag/Last-Modified values are
        advanced by ``complete_rss_response``.
        """

        body_hash = hashlib.sha256(body).hexdigest()
        now = _now()
        with self._connect() as conn:
            attempt = conn.execute(
                "SELECT request_fingerprint FROM literature_api_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            request_fp = str(attempt["request_fingerprint"]) if attempt is not None else body_hash
            existing = conn.execute(
                "SELECT * FROM literature_source_snapshots WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO literature_source_snapshots (
                        snapshot_id, attempt_id, check_id, scope_id, provider,
                        request_fingerprint, content_type, status_code, body, body_hash,
                        etag, last_modified, cache_control, received_at
                    ) VALUES (?, ?, ?, ?, 'arxiv-rss', ?, 'application/rss+xml', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _identifier("snapshot"),
                        attempt_id,
                        check_id,
                        scope_id,
                        request_fp,
                        status_code,
                        body,
                        body_hash,
                        etag,
                        last_modified,
                        cache_control,
                        now,
                    ),
                )
            conn.execute(
                """
                UPDATE literature_check_scopes
                SET status = 'checking', response_hash = ?, last_error = NULL
                WHERE scope_id = ?
                """,
                (body_hash, scope_id),
            )
            conn.execute(
                "UPDATE literature_checks SET status = 'checking', started_at = COALESCE(started_at, ?) WHERE check_id = ?",
                (now, check_id),
            )
            row = conn.execute(
                "SELECT * FROM literature_source_snapshots WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"RSS snapshot was not persisted: {attempt_id}")
        return dict(row)

    def rss_snapshot_for_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        """Load the raw source evidence associated with one API attempt."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_source_snapshots WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_rss_response(
        self,
        *,
        check_id: str,
        scope_id: str,
        papers: list[DiscoveredPaper],
        is_truncated: bool,
        response_hash: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        """Persist parsed catalog/matching output after a raw snapshot exists."""

        self.store_discovered_papers(check_id, papers, complete_check=not is_truncated)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE literature_check_scopes
                SET status = ?, item_count = ?, etag = ?, last_modified = ?,
                    response_hash = ?, last_error = NULL
                WHERE scope_id = ?
                """,
                (
                    "partial" if is_truncated else "completed",
                    len(papers),
                    etag,
                    last_modified,
                    response_hash,
                    scope_id,
                ),
            )

    def complete_rss_not_modified(
        self,
        *,
        check_id: str,
        scope_id: str,
        etag: str | None,
        last_modified: str | None,
        response_hash: str,
    ) -> None:
        """Persist semantic state for a 304 response after durable evidence."""

        if not response_hash.strip():
            raise ValueError("response_hash is required for a not-modified response")
        self.store_discovered_papers(check_id, [], complete_check=True)
        now = _now()
        with self._connect() as conn:
            scope = conn.execute(
                "SELECT etag, last_modified FROM literature_check_scopes WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            if scope is None:
                raise KeyError(f"Literature check scope not found: {scope_id}")
            conn.execute(
                """
                UPDATE literature_check_scopes
                SET status = 'completed', item_count = 0,
                    etag = COALESCE(?, etag),
                    last_modified = COALESCE(?, last_modified),
                    response_hash = ?, next_attempt_at = NULL, last_error = NULL
                WHERE scope_id = ?
                """,
                (etag, last_modified, response_hash, scope_id),
            )
            conn.execute(
                """
                UPDATE literature_checks
                SET status = 'completed', completed_at = COALESCE(completed_at, ?),
                    next_attempt_at = NULL, last_error = NULL
                WHERE check_id = ?
                """,
                (now, check_id),
            )

    def record_rss_response(
        self,
        *,
        check_id: str,
        scope_id: str,
        body: bytes,
        etag: str | None,
        last_modified: str | None,
        papers: list[DiscoveredPaper],
        is_truncated: bool,
    ) -> None:
        """Compatibility wrapper for callers that already parsed the body."""

        snapshot = self.persist_rss_snapshot(
            attempt_id=_identifier("compat-attempt"),
            check_id=check_id,
            scope_id=scope_id,
            body=body,
            etag=etag,
            last_modified=last_modified,
            cache_control=None,
            status_code=200,
        )
        self.complete_rss_response(
            check_id=check_id,
            scope_id=scope_id,
            papers=papers,
            is_truncated=is_truncated,
            response_hash=str(snapshot["body_hash"]),
            etag=etag,
            last_modified=last_modified,
        )
        logger.debug(
            "literature_rss_persisted",
            check_id=check_id,
            scope_id=scope_id,
            paper_count=len(papers),
            paper_id_sample=[f"{paper.provider}:{paper.external_id}" for paper in papers[:5]],
            response_hash=str(snapshot["body_hash"]),
            body_bytes=len(body),
            is_truncated=is_truncated,
        )

    def mark_check_retrying(self, check_id: str, error: str, delay_seconds: int = 60) -> None:
        retry_at = (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE literature_checks SET status = 'retrying', next_attempt_at = ?, last_error = ? WHERE check_id = ?",
                (retry_at, error[:1000], check_id),
            )
        logger.warning(
            "literature_check_retrying",
            check_id=check_id,
            error=error[:500],
            retry_delay_seconds=delay_seconds,
        )

    def check_scope(self, scope_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_check_scopes WHERE scope_id = ?", (scope_id,)
            ).fetchone()
        return dict(row) if row else None

    def pending_outbox_work_ids(self, limit: int = 100) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT work_item_id FROM literature_outbox WHERE status = 'pending'
                ORDER BY created_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [str(row["work_item_id"]) for row in rows]

    def mark_outbox_published(self, work_item_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE literature_outbox SET status = 'published', published_at = ?,
                  publish_attempts = publish_attempts + 1, last_error = NULL WHERE work_item_id = ?
                """,
                (_now(), work_item_id),
            )
        logger.debug("literature_outbox_published", work_item_id=work_item_id)

    def mark_outbox_failed(self, work_item_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE literature_outbox SET publish_attempts = publish_attempts + 1, last_error = ?
                WHERE work_item_id = ?
                """,
                (error[:1000], work_item_id),
            )
        logger.warning(
            "literature_outbox_publish_failed",
            work_item_id=work_item_id,
            error=error[:500],
        )

    def complete_work_item(self, work_item_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE literature_work_items SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL, updated_at = ? WHERE work_item_id = ?",
                (_now(), work_item_id),
            )
        logger.debug("literature_work_item_completed", work_item_id=work_item_id)

    def retry_work_item(
        self, work_item_id: str, error: str, delay_seconds: int | None = None
    ) -> None:
        attempt = self.latest_api_attempt(
            work_item_id=work_item_id,
            provider="arxiv-rss",
            operation=None,
        ) or self.latest_api_attempt(
            work_item_id=work_item_id,
            provider="anthropic",
            operation=None,
        )
        evidence = bool(
            attempt is not None
            and (
                attempt.response_payload is not None
                or self.rss_snapshot_for_attempt(attempt.attempt_id) is not None
            )
        )
        persisted_delay = attempt.retry_after_seconds if attempt is not None else None
        effective_delay = (
            delay_seconds
            if delay_seconds is not None
            else persisted_delay
            if persisted_delay is not None
            else 60
        )
        available_at = (datetime.now(UTC) + timedelta(seconds=effective_delay)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempt_count, max_attempts FROM literature_work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                return
            blocked_without_evidence = (
                attempt is not None
                and attempt.state in {"unknown", "definitive_failure"}
                and not evidence
            )
            state = (
                "failed"
                if blocked_without_evidence or row["attempt_count"] >= row["max_attempts"]
                else "retrying"
            )
            conn.execute(
                """
                UPDATE literature_work_items SET status = ?, available_at = ?, lease_owner = NULL,
                lease_expires_at = NULL, last_error = ?, updated_at = ? WHERE work_item_id = ?
                """,
                (state, available_at, error[:1000], _now(), work_item_id),
            )
        logger.warning(
            "literature_work_item_retrying"
            if state == "retrying"
            else "literature_work_item_failed",
            work_item_id=work_item_id,
            status=state,
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            error=error[:500],
            retry_delay_seconds=effective_delay if state == "retrying" else None,
        )

    def store_discovered_papers(
        self, check_id: str, papers: list[DiscoveredPaper], *, complete_check: bool = True
    ) -> int:
        """Store parsed source data before matching any user topics."""
        now = _now()
        with self._connect() as conn:
            for paper in papers:
                paper_id = f"{paper.provider}:{paper.external_id}"
                content_hash = _fingerprint(
                    {
                        "title": paper.title,
                        "authors": paper.authors,
                        "abstract": paper.abstract,
                        "categories": paper.categories,
                    }
                )
                version_id = f"{paper_id}:{paper.provider_version}"
                conn.execute(
                    """
                    INSERT INTO literature_catalog_papers (
                        paper_id, provider, external_id, title, authors_json, primary_category,
                        categories_json, abstract, source_url, pdf_url, published_at, updated_at,
                        current_version_id, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, external_id) DO UPDATE SET
                      title=excluded.title, authors_json=excluded.authors_json,
                      primary_category=excluded.primary_category, categories_json=excluded.categories_json,
                      abstract=excluded.abstract, source_url=excluded.source_url, pdf_url=excluded.pdf_url,
                      published_at=COALESCE(excluded.published_at, literature_catalog_papers.published_at),
                      updated_at=COALESCE(excluded.updated_at, literature_catalog_papers.updated_at),
                      current_version_id=excluded.current_version_id, last_seen_at=excluded.last_seen_at
                    """,
                    (
                        paper_id,
                        paper.provider,
                        paper.external_id,
                        paper.title,
                        json.dumps(paper.authors),
                        paper.primary_category,
                        json.dumps(paper.categories),
                        paper.abstract,
                        paper.source_url,
                        paper.pdf_url,
                        paper.published_at,
                        paper.updated_at,
                        version_id,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO literature_paper_versions (
                        version_id, paper_id, provider_version, title, authors_json, abstract,
                        categories_json, published_at, updated_at, content_hash, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id, provider_version) DO UPDATE SET
                      title=excluded.title, authors_json=excluded.authors_json, abstract=excluded.abstract,
                      categories_json=excluded.categories_json, updated_at=excluded.updated_at,
                      content_hash=excluded.content_hash
                    """,
                    (
                        version_id,
                        paper_id,
                        paper.provider_version,
                        paper.title,
                        json.dumps(paper.authors),
                        paper.abstract,
                        json.dumps(paper.categories),
                        paper.published_at,
                        paper.updated_at,
                        content_hash,
                        now,
                    ),
                )
            matched_count = self._match_all_topics(conn, papers, now)
            if complete_check:
                conn.execute(
                    "UPDATE literature_checks SET status = 'completed', completed_at = ? WHERE check_id = ?",
                    (now, check_id),
                )
            else:
                conn.execute(
                    "UPDATE literature_checks SET status = 'partial' WHERE check_id = ?",
                    (check_id,),
                )
        logger.debug(
            "literature_papers_stored",
            check_id=check_id,
            paper_count=len(papers),
            matched_count=matched_count,
            paper_id_sample=[f"{paper.provider}:{paper.external_id}" for paper in papers[:5]],
            complete_check=complete_check,
        )
        return len(papers)

    def _match_all_topics(
        self, conn: sqlite3.Connection, papers: list[DiscoveredPaper], now: str
    ) -> int:
        topics = conn.execute("SELECT * FROM literature_topics WHERE is_active = 1").fetchall()
        matched_count = 0
        for paper in papers:
            paper_id = f"{paper.provider}:{paper.external_id}"
            version_id = f"{paper_id}:{paper.provider_version}"
            catalog = conn.execute(
                "SELECT * FROM literature_catalog_papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            assert catalog is not None
            for topic in topics:
                categories = json.loads(topic["categories_json"])
                include_terms = json.loads(topic["include_terms_json"])
                exclude_terms = json.loads(topic["exclude_terms_json"])
                matched, reasons = self._matches(catalog, categories, include_terms, exclude_terms)
                if not matched:
                    continue
                matched_count += 1
                conn.execute(
                    """
                    INSERT INTO literature_topic_matches (topic_id, paper_id, reason_json, matched_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(topic_id, paper_id) DO UPDATE SET reason_json=excluded.reason_json, matched_at=excluded.matched_at
                    """,
                    (topic["topic_id"], paper_id, json.dumps(reasons), now),
                )
                conn.execute(
                    """
                    INSERT INTO literature_user_paper_states (
                        user_id, paper_id, first_seen_at, last_seen_at, latest_seen_version_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, paper_id) DO UPDATE SET
                      last_seen_at=excluded.last_seen_at, latest_seen_version_id=excluded.latest_seen_version_id
                    """,
                    (topic["user_id"], paper_id, now, now, version_id),
                )
                conn.execute(
                    "UPDATE literature_topics SET last_matched_at = ? WHERE topic_id = ?",
                    (now, topic["topic_id"]),
                )
        return matched_count

    def _insert_work_item(
        self, conn: sqlite3.Connection, *, kind: str, idempotency_key: str, payload: dict[str, Any]
    ) -> str:
        existing = conn.execute(
            "SELECT work_item_id FROM literature_work_items WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return str(existing["work_item_id"])
        now = _now()
        work_item_id = _identifier("work")
        conn.execute(
            """
            INSERT INTO literature_work_items (
                work_item_id, kind, idempotency_key, status, payload_json, available_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (work_item_id, kind, idempotency_key, json.dumps(payload), now, now, now),
        )
        conn.execute(
            "INSERT INTO literature_outbox (outbox_id, work_item_id, created_at) VALUES (?, ?, ?)",
            (_identifier("outbox"), work_item_id, now),
        )
        return work_item_id

    def _get_paper(self, conn: sqlite3.Connection, user_id: str, paper_id: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT cp.*, ups.is_read, ups.is_saved, ups.is_ignored,
                   ups.first_seen_at AS user_first_seen_at,
                   ups.last_seen_at AS user_last_seen_at, ups.latest_seen_version_id
            FROM literature_catalog_papers cp
            JOIN literature_user_paper_states ups ON ups.paper_id = cp.paper_id
            WHERE cp.paper_id = ? AND ups.user_id = ?
            """,
            (paper_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError("Paper not found")
        versions = conn.execute(
            "SELECT * FROM literature_paper_versions WHERE paper_id = ? ORDER BY first_seen_at DESC",
            (paper_id,),
        ).fetchall()
        result = self._paper_for_user(conn, user_id, row)
        result["versions"] = [self._version_dict(version) for version in versions]
        return result

    @staticmethod
    def _idempotent_result(
        conn: sqlite3.Connection,
        user_id: str,
        scope: str,
        idempotency_key: str | None,
        request: object,
    ) -> dict[str, Any] | None:
        if idempotency_key is None:
            return None
        row = conn.execute(
            """
            SELECT request_hash, response_json
            FROM literature_idempotency_requests
            WHERE user_id = ? AND scope = ? AND idempotency_key = ?
            """,
            (user_id, scope, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != _fingerprint(request):
            raise LiteratureIdempotencyConflictError(
                "Idempotency-Key was already used for different Literature input"
            )
        payload = json.loads(str(row["response_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("Stored Literature idempotency response is invalid")
        return {str(key): value for key, value in payload.items()}

    @staticmethod
    def _store_idempotency(
        conn: sqlite3.Connection,
        user_id: str,
        scope: str,
        idempotency_key: str | None,
        request: object,
        response: dict[str, Any],
    ) -> None:
        if idempotency_key is None:
            return
        conn.execute(
            """
            INSERT INTO literature_idempotency_requests (
                user_id, scope, idempotency_key, request_hash, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                scope,
                idempotency_key,
                _fingerprint(request),
                json.dumps(response, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )

    @staticmethod
    def _clean_terms(values: Sequence[object]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @staticmethod
    def _validate_topic(label: str, categories: Sequence[object]) -> None:
        if not label.strip():
            raise ValueError("Topic label is required")
        if not categories or not all(
            isinstance(value, str) and value.strip() for value in categories
        ):
            raise ValueError("At least one arXiv category is required")

    @staticmethod
    def _matches(
        paper: sqlite3.Row,
        categories: list[object],
        include_terms: list[object],
        exclude_terms: list[object],
    ) -> tuple[bool, list[str]]:
        paper_categories = set(json.loads(paper["categories_json"]))
        wanted_categories = {str(value) for value in categories}
        if wanted_categories and not (wanted_categories & paper_categories):
            return False, []
        haystack = f"{paper['title']} {paper['abstract']}".casefold()
        included = [str(value) for value in include_terms if str(value).casefold() in haystack]
        excluded = [str(value) for value in exclude_terms if str(value).casefold() in haystack]
        if excluded or (include_terms and not included):
            return False, []
        reasons = [f"分类：{value}" for value in sorted(wanted_categories & paper_categories)]
        reasons.extend(f"关键词：{value}" for value in included)
        return True, reasons or ["分类匹配"]

    @staticmethod
    def _topic_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "topic_id": row["topic_id"],
            "user_id": row["user_id"],
            "label": row["label"],
            "include_terms": json.loads(row["include_terms_json"]),
            "exclude_terms": json.loads(row["exclude_terms_json"]),
            "categories": json.loads(row["categories_json"]),
            "status": row["status"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_matched_at": row["last_matched_at"],
        }

    @staticmethod
    def _catalog_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "paper_id": row["paper_id"],
            "provider": row["provider"],
            "external_id": row["external_id"],
            "title": row["title"],
            "authors": json.loads(row["authors_json"]),
            "abstract": row["abstract"],
            "primary_category": row["primary_category"],
            "categories": json.loads(row["categories_json"]),
            "published_at": row["published_at"],
            "updated_at": row["updated_at"],
            "source_url": row["source_url"],
            "pdf_url": row["pdf_url"],
            "current_version_id": row["current_version_id"],
        }

    def _paper_for_user(
        self, conn: sqlite3.Connection, user_id: str, row: sqlite3.Row
    ) -> dict[str, Any]:
        result = self._catalog_dict(row)
        topics = conn.execute(
            """
            SELECT t.topic_id, t.label, tm.reason_json FROM literature_topic_matches tm
            JOIN literature_topics t ON t.topic_id = tm.topic_id
            WHERE tm.paper_id = ? AND t.user_id = ? ORDER BY t.label
            """,
            (row["paper_id"], user_id),
        ).fetchall()
        result.update(
            {
                "matched_topics": [
                    {
                        "topic_id": topic["topic_id"],
                        "label": topic["label"],
                        "reasons": json.loads(topic["reason_json"]),
                    }
                    for topic in topics
                ],
                "user_state": {
                    "is_read": bool(row["is_read"]),
                    "is_saved": bool(row["is_saved"]),
                    "is_ignored": bool(row["is_ignored"]),
                    "first_seen_at": row["user_first_seen_at"],
                    "last_seen_at": row["user_last_seen_at"],
                    "latest_seen_version_id": row["latest_seen_version_id"],
                },
            }
        )
        return result

    @staticmethod
    def _check_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "check_id": row["check_id"],
            "status": row["status"],
            "trigger": row["trigger"],
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "next_attempt_at": row["next_attempt_at"],
            "error": row["last_error"],
        }

    @staticmethod
    def _summary_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "summary_id": row["summary_id"],
            "status": row["status"],
            "text": row["summary_text"],
            "practice_note": row["practice_note"],
            "error": row["error_message"],
            "version_id": row["version_id"],
        }

    @staticmethod
    def _api_attempt_dict(row: sqlite3.Row) -> ExternalCallAttempt:
        return ExternalCallAttempt(
            attempt_id=str(row["attempt_id"]),
            provider=str(row["provider"]),
            operation=str(row["operation"]),
            request_fingerprint=str(row["request_fingerprint"]),
            attempt_number=int(row["attempt_number"]),
            state=str(row["state"]),
            check_id=str(row["check_id"]) if row["check_id"] is not None else None,
            work_item_id=str(row["work_item_id"]) if row["work_item_id"] is not None else None,
            status_code=int(row["status_code"]) if row["status_code"] is not None else None,
            retry_after_seconds=(
                int(row["retry_after_seconds"]) if row["retry_after_seconds"] is not None else None
            ),
            error_kind=str(row["error_kind"]) if row["error_kind"] is not None else None,
            error_message=str(row["error_message"]) if row["error_message"] is not None else None,
            started_at=str(row["started_at"]),
            response_received_at=(
                str(row["response_received_at"])
                if row["response_received_at"] is not None
                else None
            ),
            response_persisted_at=(
                str(row["response_persisted_at"])
                if row["response_persisted_at"] is not None
                else None
            ),
            completed_at=(str(row["completed_at"]) if row["completed_at"] is not None else None),
            response_hash=(str(row["response_hash"]) if row["response_hash"] is not None else None),
            response_payload=(
                str(row["response_payload"]) if row["response_payload"] is not None else None
            ),
            legacy_state=(str(row["legacy_state"]) if row["legacy_state"] is not None else None),
        )

    @staticmethod
    def _version_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Keep persistence-only version columns behind the presenter Seam."""

        return {
            "version_id": row["version_id"],
            "provider_version": row["provider_version"],
            "published_at": row["published_at"],
            "updated_at": row["updated_at"],
            "first_seen_at": row["first_seen_at"],
        }

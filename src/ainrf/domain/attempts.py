"""Durable TaskAttempt, RuntimeSession, and crash-safe dispatch repositories."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.context import ProjectContextService
from ainrf.domain.service import DomainConflictError, DomainNotFoundError
from ainrf.harness_engine import EngineEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _event_content(event: EngineEvent) -> str:
    payload = event.payload
    content = payload.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_kind(event: EngineEvent) -> str:
    return "lifecycle" if event.event_type in {"status", "system"} else event.event_type


def _event_refs(event: EngineEvent, key: str) -> tuple[str, ...]:
    value = event.payload.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _merge_refs(existing_json: object, additions: tuple[str, ...]) -> str:
    existing: list[str] = []
    if isinstance(existing_json, str):
        try:
            decoded = json.loads(existing_json)
        except json.JSONDecodeError:
            decoded = []
        if isinstance(decoded, list):
            existing = [item for item in decoded if isinstance(item, str) and item]
    merged = list(dict.fromkeys([*existing, *additions]))
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    dispatch_id: str
    task_id: str
    attempt_id: str
    claim_token: str
    runtime_launch_key: str
    claim_expires_at: str
    launch_state: str


@dataclass(frozen=True, slots=True)
class RuntimeLaunchPreparation:
    runtime_session_id: str
    runtime_launch_key: str
    must_probe: bool
    allow_start_after_absent: bool


@dataclass(frozen=True, slots=True)
class DispatchEventResult:
    task_status: str | None
    attempt_status: str | None
    output_sequence: int | None


class DispatchClaimError(DomainConflictError):
    """The worker no longer owns a claimed dispatch row."""


class AttemptService:
    """The SQLite repository used by every durable task dispatcher.

    Claim ownership is always scoped by a fresh opaque token.  An expired
    claim may be recovered only while the row remains in a recoverable state;
    a launch whose side effect cannot be proved becomes ``launch_unknown`` and
    is intentionally never selected for another blind start.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._context_service = ProjectContextService(state_root)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def create_attempt(self, task_id: str, *, trigger: str) -> str:
        with closing(self._connect()) as conn:
            task = conn.execute(
                "SELECT project_context_snapshot_id FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            existing_snapshot_id = task["project_context_snapshot_id"]
            snapshot_id = (
                str(existing_snapshot_id)
                if isinstance(existing_snapshot_id, str) and existing_snapshot_id
                else self._context_service.ensure_task_snapshot_in_transaction(conn, task_id)
            )
            next_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(attempt_seq), 0) + 1 FROM agent_task_attempts WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            attempt_id = f"attempt-{uuid4().hex}"
            dispatch_id = f"dispatch-{uuid4().hex}"
            now = _now()
            conn.execute(
                """INSERT INTO agent_task_attempts (
                       attempt_id, task_id, attempt_seq, trigger, status,
                       context_snapshot_id, created_at
                   ) VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                (attempt_id, task_id, next_seq, trigger, snapshot_id, now),
            )
            conn.execute(
                """INSERT INTO task_dispatch_outbox (
                       dispatch_id, task_id, attempt_id, status, created_at, updated_at
                   ) VALUES (?, ?, ?, 'pending', ?, ?)""",
                (dispatch_id, task_id, attempt_id, now, now),
            )
            conn.execute(
                """UPDATE tasks SET latest_attempt_id = ?, status = 'queued', updated_at = ?
                   WHERE task_id = ?""",
                (attempt_id, now, task_id),
            )
            conn.commit()
            return attempt_id

    def claim_next(self, dispatcher_id: str, *, lease_seconds: int = 30) -> DispatchClaim | None:
        if not dispatcher_id:
            raise ValueError("dispatcher_id is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = _now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT dispatch_id, task_id, attempt_id, runtime_launch_key, launch_state
                   FROM task_dispatch_outbox
                   WHERE (
                       (status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                       OR (status = 'claimed' AND claim_expires_at IS NOT NULL
                           AND claim_expires_at <= ?)
                       OR (status = 'dispatched' AND claim_expires_at IS NOT NULL
                           AND claim_expires_at <= ?)
                   )
                     AND launch_state != 'unknown'
                   ORDER BY created_at, dispatch_id LIMIT 1""",
                (now, now, now),
            ).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            launch_key = (
                str(row["runtime_launch_key"])
                if row["runtime_launch_key"] is not None
                else f"launch-{row['attempt_id']}"
            )
            expires_at = _after(lease_seconds)
            updated = conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'claimed', claim_token = ?, dispatcher_id = ?,
                       claim_expires_at = ?, runtime_launch_key = ?,
                       claimed_at = COALESCE(claimed_at, ?), claim_heartbeat_at = ?,
                       dispatch_attempt_count = dispatch_attempt_count + 1, updated_at = ?
                   WHERE dispatch_id = ?
                     AND (
                         (status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                         OR (status = 'claimed' AND claim_expires_at IS NOT NULL
                             AND claim_expires_at <= ?)
                         OR (status = 'dispatched' AND claim_expires_at IS NOT NULL
                             AND claim_expires_at <= ?)
                     )
                     AND launch_state != 'unknown'""",
                (
                    token,
                    dispatcher_id,
                    expires_at,
                    launch_key,
                    now,
                    now,
                    now,
                    row["dispatch_id"],
                    now,
                    now,
                    now,
                ),
            )
            if updated.rowcount != 1:
                return None
            conn.commit()
            return DispatchClaim(
                dispatch_id=str(row["dispatch_id"]),
                task_id=str(row["task_id"]),
                attempt_id=str(row["attempt_id"]),
                claim_token=token,
                runtime_launch_key=launch_key,
                claim_expires_at=expires_at,
                launch_state=str(row["launch_state"]),
            )

    def heartbeat_claim(self, claim: DispatchClaim, *, lease_seconds: int = 30) -> DispatchClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = _now()
        expires_at = _after(lease_seconds)
        with closing(self._connect()) as conn:
            updated = conn.execute(
                """UPDATE task_dispatch_outbox
                   SET claim_expires_at = ?, claim_heartbeat_at = ?, updated_at = ?
                   WHERE dispatch_id = ? AND status = 'claimed' AND claim_token = ?
                     AND claim_expires_at > ?
                     AND launch_state != 'unknown'""",
                (expires_at, now, now, claim.dispatch_id, claim.claim_token, now),
            )
            if updated.rowcount != 1:
                raise DispatchClaimError("Dispatch claim is no longer current")
            conn.commit()
        return DispatchClaim(
            dispatch_id=claim.dispatch_id,
            task_id=claim.task_id,
            attempt_id=claim.attempt_id,
            claim_token=claim.claim_token,
            runtime_launch_key=claim.runtime_launch_key,
            claim_expires_at=expires_at,
            launch_state=claim.launch_state,
        )

    def prepare_runtime_launch(self, claim: DispatchClaim) -> RuntimeLaunchPreparation:
        """Persist the deterministic launch key before any external side effect."""

        now = _now()
        with closing(self._connect()) as conn:
            dispatch = self._current_claim(conn, claim, require_not_expired=True)
            launch_state = str(dispatch["launch_state"])
            runtime = conn.execute(
                """SELECT runtime_session_id, status FROM agent_runtime_sessions
                   WHERE launch_key = ?""",
                (claim.runtime_launch_key,),
            ).fetchone()
            if launch_state == "unknown":
                raise DispatchClaimError("Dispatch has an unknown prior launch")
            if runtime is not None:
                if launch_state not in {"none", "starting", "launched"}:
                    raise DispatchClaimError("Dispatch launch state cannot be recovered")
                conn.execute(
                    """UPDATE task_dispatch_outbox
                       SET launch_state = CASE WHEN launch_state = 'launched' THEN 'launched'
                                                ELSE 'starting' END,
                           launch_started_at = COALESCE(launch_started_at, ?),
                           updated_at = ? WHERE dispatch_id = ?""",
                    (now, now, claim.dispatch_id),
                )
                conn.commit()
                return RuntimeLaunchPreparation(
                    runtime_session_id=str(runtime["runtime_session_id"]),
                    runtime_launch_key=claim.runtime_launch_key,
                    must_probe=True,
                    allow_start_after_absent=launch_state != "launched",
                )
            runtime_session_id = f"runtime-{uuid4().hex}"
            conn.execute(
                """INSERT INTO agent_runtime_sessions (
                       runtime_session_id, attempt_id, launch_key, status, created_at, started_at
                   ) VALUES (?, ?, ?, 'starting', ?, ?)""",
                (runtime_session_id, claim.attempt_id, claim.runtime_launch_key, now, now),
            )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET launch_state = 'starting', launch_started_at = ?, updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?""",
                (now, now, claim.dispatch_id, claim.claim_token),
            )
            conn.execute(
                """UPDATE agent_task_attempts SET status = 'starting', started_at = COALESCE(started_at, ?)
                   WHERE attempt_id = ?""",
                (now, claim.attempt_id),
            )
            self._project_task_status(conn, claim.attempt_id, "starting", now)
            conn.commit()
            return RuntimeLaunchPreparation(
                runtime_session_id=runtime_session_id,
                runtime_launch_key=claim.runtime_launch_key,
                must_probe=launch_state == "starting",
                allow_start_after_absent=True,
            )

    def mark_runtime_running(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        *,
        adopted: bool = False,
        engine_session_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            self._current_claim(conn, claim, require_not_expired=True)
            runtime = conn.execute(
                """SELECT attempt_id, launch_key FROM agent_runtime_sessions
                   WHERE runtime_session_id = ?""",
                (runtime_session_id,),
            ).fetchone()
            if runtime is None or runtime["attempt_id"] != claim.attempt_id:
                raise DispatchClaimError("Runtime Session does not belong to this dispatch")
            if runtime["launch_key"] != claim.runtime_launch_key:
                raise DispatchClaimError("Runtime Session launch key does not match dispatch")
            conn.execute(
                """UPDATE agent_runtime_sessions
                   SET status = 'running', engine_session_key = COALESCE(?, engine_session_key),
                       runtime_metadata_json = ?, last_probe_at = ?,
                       adopted_at = CASE WHEN ? THEN ? ELSE adopted_at END
                   WHERE runtime_session_id = ?""",
                (
                    engine_session_key,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    int(adopted),
                    now,
                    runtime_session_id,
                ),
            )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'dispatched', launch_state = 'launched', updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?""",
                (now, claim.dispatch_id, claim.claim_token),
            )
            conn.execute(
                """UPDATE agent_task_attempts SET status = 'running', started_at = COALESCE(started_at, ?)
                   WHERE attempt_id = ?""",
                (now, claim.attempt_id),
            )
            self._project_task_status(conn, claim.attempt_id, "running", now)
            conn.commit()

    def adopt_runtime(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        *,
        engine_session_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.mark_runtime_running(
            claim,
            runtime_session_id,
            adopted=True,
            engine_session_key=engine_session_key,
            metadata=metadata,
        )

    def mark_launch_unknown(self, claim: DispatchClaim, *, reason: str) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            self._current_claim(conn, claim, require_not_expired=True)
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'launch_unknown', launch_state = 'unknown', last_error = ?,
                       launch_unknown_at = ?, updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?""",
                (reason, now, now, claim.dispatch_id, claim.claim_token),
            )
            conn.execute(
                """UPDATE agent_runtime_sessions
                   SET status = 'unknown', failure_reason = ?, last_probe_at = ?
                   WHERE launch_key = ?""",
                (reason, now, claim.runtime_launch_key),
            )
            conn.execute(
                """UPDATE agent_task_attempts SET status = 'launch_unknown', failure_reason = ?
                   WHERE attempt_id = ?""",
                (reason, claim.attempt_id),
            )
            self._project_task_status(conn, claim.attempt_id, "launch_unknown", now)
            conn.commit()

    def mark_runtime_completed(self, claim: DispatchClaim, runtime_session_id: str) -> None:
        self._finish_runtime(
            claim,
            runtime_session_id,
            attempt_status="succeeded",
            dispatch_status="completed",
            failure_reason=None,
        )

    def mark_runtime_failed(
        self, claim: DispatchClaim, runtime_session_id: str, *, reason: str
    ) -> None:
        self._finish_runtime(
            claim,
            runtime_session_id,
            attempt_status="failed",
            dispatch_status="failed",
            failure_reason=reason,
        )

    def record_event(self, claim: DispatchClaim, event: EngineEvent) -> DispatchEventResult:
        """Persist one engine event against the claimed Attempt and its Task."""

        now = _now()
        with closing(self._connect()) as conn:
            dispatch = self._current_claim(conn, claim, require_not_expired=True)
            if dispatch["status"] not in {"claimed", "dispatched"}:
                raise DispatchClaimError("Dispatch cannot accept events in its current state")
            if dispatch["status"] == "claimed":
                # The first event is the first durable proof that the external
                # runtime crossed the launch boundary.  Before this point the
                # row stays recoverable as ``starting`` so a crashed worker can
                # probe the deterministic launch key instead of starting twice.
                conn.execute(
                    """UPDATE agent_runtime_sessions
                       SET status = 'running', last_probe_at = ?
                       WHERE launch_key = ? AND status = 'starting'""",
                    (now, claim.runtime_launch_key),
                )
                conn.execute(
                    """UPDATE task_dispatch_outbox
                       SET status = 'dispatched', launch_state = 'launched', updated_at = ?
                       WHERE dispatch_id = ? AND claim_token = ?""",
                    (now, claim.dispatch_id, claim.claim_token),
                )
                conn.execute(
                    """UPDATE agent_task_attempts
                       SET status = 'running', started_at = COALESCE(started_at, ?)
                       WHERE attempt_id = ?""",
                    (now, claim.attempt_id),
                )
                self._project_task_status(conn, claim.attempt_id, "running", now)
            latest = conn.execute(
                "SELECT latest_output_seq FROM tasks WHERE task_id = ?", (claim.task_id,)
            ).fetchone()
            if latest is None:
                raise DomainNotFoundError(claim.task_id)
            sequence = int(latest["latest_output_seq"]) + 1
            conn.execute(
                """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (claim.task_id, sequence, _event_kind(event), _event_content(event), now),
            )
            conn.execute(
                """UPDATE tasks SET latest_output_seq = ?, updated_at = ? WHERE task_id = ?""",
                (sequence, now, claim.task_id),
            )
            usage_json = (
                json.dumps(event.token_usage, sort_keys=True) if event.token_usage else None
            )
            cost = self._cost_from_event(event)
            attempt = conn.execute(
                """SELECT artifact_refs_json, code_refs_json, data_refs_json
                   FROM agent_task_attempts WHERE attempt_id = ?""",
                (claim.attempt_id,),
            ).fetchone()
            if attempt is None:
                raise DomainNotFoundError(claim.attempt_id)
            is_message = event.event_type == "message"
            conn.execute(
                """UPDATE agent_task_attempts
                   SET output_start_seq = COALESCE(output_start_seq, ?), output_end_seq = ?,
                       message_start_seq = CASE WHEN ? THEN COALESCE(message_start_seq, ?)
                                                ELSE message_start_seq END,
                       message_end_seq = CASE WHEN ? THEN ? ELSE message_end_seq END,
                       artifact_refs_json = ?, code_refs_json = ?, data_refs_json = ?,
                       token_usage_json = COALESCE(?, token_usage_json),
                       cost_usd = COALESCE(?, cost_usd)
                   WHERE attempt_id = ?""",
                (
                    sequence,
                    sequence,
                    int(is_message),
                    sequence,
                    int(is_message),
                    sequence,
                    _merge_refs(attempt["artifact_refs_json"], _event_refs(event, "artifact_refs")),
                    _merge_refs(attempt["code_refs_json"], _event_refs(event, "code_refs")),
                    _merge_refs(attempt["data_refs_json"], _event_refs(event, "data_refs")),
                    usage_json,
                    cost,
                    claim.attempt_id,
                ),
            )
            task_status: str | None = None
            attempt_status: str | None = None
            if event.event_type == "status":
                raw_status = event.payload.get("status")
                if raw_status == "succeeded":
                    self._finish_runtime_in_transaction(
                        conn,
                        claim,
                        attempt_status="succeeded",
                        dispatch_status="completed",
                        failure_reason=None,
                        now=now,
                    )
                    task_status = "succeeded"
                    attempt_status = "succeeded"
                elif raw_status == "failed":
                    reason = event.payload.get("error_summary") or event.payload.get("message")
                    self._finish_runtime_in_transaction(
                        conn,
                        claim,
                        attempt_status="failed",
                        dispatch_status="failed",
                        failure_reason=str(reason) if reason is not None else "engine failed",
                        now=now,
                    )
                    task_status = "failed"
                    attempt_status = "failed"
            conn.commit()
            return DispatchEventResult(
                task_status=task_status,
                attempt_status=attempt_status,
                output_sequence=sequence,
            )

    def record_authorization_snapshot(
        self,
        claim: DispatchClaim,
        *,
        environment_id: str,
        grant_version: int,
    ) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            self._current_claim(conn, claim, require_not_expired=True)
            conn.execute(
                """UPDATE agent_task_attempts
                   SET authorization_environment_id = ?, authorization_grant_version = ?,
                       authorization_checked_at = ? WHERE attempt_id = ?""",
                (environment_id, grant_version, now, claim.attempt_id),
            )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET authorization_environment_id = ?, authorization_grant_version = ?,
                       authorization_checked_at = ?, updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?""",
                (environment_id, grant_version, now, now, claim.dispatch_id, claim.claim_token),
            )
            conn.commit()

    def stop_for_permission_revocation(self, claim: DispatchClaim, *, reason: str) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            self._current_claim(conn, claim, require_not_expired=True)
            cancelled = conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'cancelled', cancel_reason = ?, cancelled_at = ?, updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?
                     AND launch_state IN ('none', 'starting')""",
                (reason, now, now, claim.dispatch_id, claim.claim_token),
            ).rowcount
            if cancelled == 1:
                conn.execute(
                    """UPDATE agent_runtime_sessions
                       SET status = 'cancelled', finished_at = ?, failure_reason = ?
                       WHERE launch_key = ? AND status = 'starting'""",
                    (now, reason, claim.runtime_launch_key),
                )
                conn.execute(
                    """UPDATE agent_task_attempts
                       SET status = 'stopped_permission_revoked', stop_reason = ?, finished_at = ?
                       WHERE attempt_id = ?""",
                    (reason, now, claim.attempt_id),
                )
                self._project_task_status(conn, claim.attempt_id, "stopped_permission_revoked", now)
            else:
                conn.execute(
                    """UPDATE task_dispatch_outbox
                       SET status = 'launch_unknown', launch_state = 'unknown', last_error = ?,
                           launch_unknown_at = ?, updated_at = ?
                       WHERE dispatch_id = ? AND claim_token = ?""",
                    (reason, now, now, claim.dispatch_id, claim.claim_token),
                )
                conn.execute(
                    """UPDATE agent_task_attempts
                       SET status = 'launch_unknown', failure_reason = ?
                       WHERE attempt_id = ?""",
                    (reason, claim.attempt_id),
                )
                self._project_task_status(conn, claim.attempt_id, "launch_unknown", now)
            conn.commit()

    def release_unstarted_claim(self, claim: DispatchClaim, *, reason: str) -> None:
        """Return a claim to pending only before an engine side effect exists.

        A maintenance epoch may begin after the dispatcher claimed a row but
        before it invokes an engine.  The ``starting`` RuntimeSession is then
        only a local preparation record, so it is safe to remove and reuse the
        deterministic launch key.  Once the launch state is ``launched`` the
        caller must use probe/adopt instead of this method.
        """

        now = _now()
        with closing(self._connect()) as conn:
            dispatch = self._current_claim(conn, claim, require_not_expired=True)
            if str(dispatch["launch_state"]) not in {"none", "starting"}:
                raise DispatchClaimError("Dispatch has crossed the runtime launch boundary")
            runtime = conn.execute(
                """SELECT runtime_session_id, status FROM agent_runtime_sessions
                   WHERE launch_key = ?""",
                (claim.runtime_launch_key,),
            ).fetchone()
            if runtime is not None:
                if runtime["status"] != "starting":
                    raise DispatchClaimError("Prepared Runtime Session is no longer unstarted")
                conn.execute(
                    "DELETE FROM agent_runtime_sessions WHERE runtime_session_id = ?",
                    (runtime["runtime_session_id"],),
                )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'pending', claim_token = NULL, dispatcher_id = NULL,
                       claim_expires_at = NULL, runtime_launch_key = NULL,
                       launch_state = 'none', last_error = ?, updated_at = ?
                   WHERE dispatch_id = ? AND claim_token = ?""",
                (reason, now, claim.dispatch_id, claim.claim_token),
            )
            conn.execute(
                """UPDATE agent_task_attempts
                   SET status = 'queued', started_at = NULL
                   WHERE attempt_id = ?""",
                (claim.attempt_id,),
            )
            self._project_task_status(conn, claim.attempt_id, "queued", now)
            conn.commit()

    def mark_runtime_started(self, claim: DispatchClaim) -> str:
        """Compatibility helper retained for existing B5 repository callers."""

        preparation = self.prepare_runtime_launch(claim)
        self.mark_runtime_running(claim, preparation.runtime_session_id)
        return preparation.runtime_session_id

    def cancel_pending_for_project(self, project_id: str, *, reason: str) -> int:
        return self.invalidate_unstarted_for_project(project_id, reason=reason)

    def invalidate_unstarted_for_project(self, project_id: str, *, reason: str) -> int:
        """Cancel only work that has not crossed the external-launch boundary."""

        now = _now()
        with closing(self._connect()) as conn:
            updated = conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'cancelled', cancel_reason = ?, cancelled_at = ?, updated_at = ?
                   WHERE status IN ('pending', 'claimed') AND launch_state = 'none'
                     AND task_id IN (SELECT task_id FROM tasks WHERE project_id = ?)""",
                (reason, now, now, project_id),
            )
            conn.commit()
            return updated.rowcount

    def invalidate_unstarted_for_task(self, task_id: str, *, reason: str) -> int:
        now = _now()
        with closing(self._connect()) as conn:
            updated = conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'cancelled', cancel_reason = ?, cancelled_at = ?, updated_at = ?
                   WHERE task_id = ? AND status IN ('pending', 'claimed') AND launch_state = 'none'""",
                (reason, now, now, task_id),
            )
            conn.commit()
            return updated.rowcount

    def dispatch_state(self, dispatch_id: str) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM task_dispatch_outbox WHERE dispatch_id = ?", (dispatch_id,)
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(dispatch_id)
            return dict(row)

    @staticmethod
    def _cost_from_event(event: EngineEvent) -> float | None:
        usage = event.token_usage
        if not isinstance(usage, dict):
            return None
        total = usage.get("total")
        if not isinstance(total, dict):
            return None
        value = total.get("cost_usd")
        return float(value) if isinstance(value, int | float) else None

    @staticmethod
    def _current_claim(
        conn: sqlite3.Connection,
        claim: DispatchClaim,
        *,
        require_not_expired: bool,
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT * FROM task_dispatch_outbox
               WHERE dispatch_id = ? AND claim_token = ?""",
            (claim.dispatch_id, claim.claim_token),
        ).fetchone()
        if row is None or row["status"] not in {"claimed", "dispatched"}:
            raise DispatchClaimError("Dispatch claim is no longer current")
        if require_not_expired and (
            row["claim_expires_at"] is None or str(row["claim_expires_at"]) <= _now()
        ):
            raise DispatchClaimError("Dispatch claim expired")
        if require_not_expired:
            updated = conn.execute(
                """UPDATE task_dispatch_outbox SET updated_at = updated_at
                   WHERE dispatch_id = ? AND claim_token = ?
                     AND status IN ('claimed', 'dispatched')
                     AND claim_expires_at > ?""",
                (claim.dispatch_id, claim.claim_token, _now()),
            )
            if updated.rowcount != 1:
                raise DispatchClaimError("Dispatch claim is no longer current")
        return row

    @staticmethod
    def _project_task_status(
        conn: sqlite3.Connection, attempt_id: str, status: str, now: str
    ) -> None:
        conn.execute(
            """UPDATE tasks SET status = ?, updated_at = ?
               WHERE latest_attempt_id = ?""",
            (status, now, attempt_id),
        )

    def _finish_runtime(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        *,
        attempt_status: str,
        dispatch_status: str,
        failure_reason: str | None,
    ) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            self._current_claim(conn, claim, require_not_expired=True)
            runtime = conn.execute(
                "SELECT attempt_id FROM agent_runtime_sessions WHERE runtime_session_id = ?",
                (runtime_session_id,),
            ).fetchone()
            if runtime is None or runtime["attempt_id"] != claim.attempt_id:
                raise DispatchClaimError("Runtime Session does not belong to this dispatch")
            self._finish_runtime_in_transaction(
                conn,
                claim,
                attempt_status=attempt_status,
                dispatch_status=dispatch_status,
                failure_reason=failure_reason,
                now=now,
            )
            conn.commit()

    def _finish_runtime_in_transaction(
        self,
        conn: sqlite3.Connection,
        claim: DispatchClaim,
        *,
        attempt_status: str,
        dispatch_status: str,
        failure_reason: str | None,
        now: str,
    ) -> None:
        runtime_status = "completed" if attempt_status == "succeeded" else "failed"
        conn.execute(
            """UPDATE agent_runtime_sessions
               SET status = ?, finished_at = ?, failure_reason = ?
               WHERE launch_key = ?""",
            (runtime_status, now, failure_reason, claim.runtime_launch_key),
        )
        conn.execute(
            """UPDATE agent_task_attempts
               SET status = ?, finished_at = ?, failure_reason = ? WHERE attempt_id = ?""",
            (attempt_status, now, failure_reason, claim.attempt_id),
        )
        conn.execute(
            """UPDATE task_dispatch_outbox
               SET status = ?, launch_state = 'launched', completed_at = ?, updated_at = ?
               WHERE dispatch_id = ? AND claim_token = ?""",
            (dispatch_status, now, now, claim.dispatch_id, claim.claim_token),
        )
        self._project_task_status(conn, claim.attempt_id, attempt_status, now)

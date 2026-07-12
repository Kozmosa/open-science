"""Durable TaskAttempt, RuntimeSession, and dispatch-outbox repository."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.context import ProjectContextService
from ainrf.domain.service import DomainNotFoundError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    dispatch_id: str
    task_id: str
    attempt_id: str
    claim_token: str
    runtime_launch_key: str


class AttemptService:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def create_attempt(self, task_id: str, *, trigger: str) -> str:
        with closing(self._connect()) as conn:
            task = conn.execute(
                "SELECT project_id, project_context_version_id FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            context_version_id = task["project_context_version_id"]
            snapshot = (
                conn.execute(
                    "SELECT context_snapshot_id FROM context_snapshots WHERE context_version_id = ? ORDER BY created_at DESC LIMIT 1",
                    (context_version_id,),
                ).fetchone()
                if context_version_id is not None
                else None
            )
            if snapshot is None:
                snapshot_id = ProjectContextService(self._state_root).pin_active_context(
                    task_id, str(task["project_id"])
                )
            else:
                snapshot_id = str(snapshot["context_snapshot_id"])
            next_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(attempt_seq), 0) + 1 FROM agent_task_attempts WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            attempt_id = f"attempt-{uuid4().hex}"
            dispatch_id = f"dispatch-{uuid4().hex}"
            conn.execute(
                "INSERT INTO agent_task_attempts (attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (attempt_id, task_id, next_seq, trigger, snapshot_id, _now()),
            )
            conn.execute(
                "INSERT INTO task_dispatch_outbox (dispatch_id, task_id, attempt_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (dispatch_id, task_id, attempt_id, _now()),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id = ?, status = 'queued', updated_at = ? WHERE task_id = ?",
                (attempt_id, _now(), task_id),
            )
            conn.commit()
            return attempt_id

    def claim_next(self, dispatcher_id: str, *, lease_seconds: int = 30) -> DispatchClaim | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT dispatch_id, task_id, attempt_id FROM task_dispatch_outbox WHERE status = 'pending' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            launch_key = f"launch-{row['attempt_id']}"
            expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
            updated = conn.execute(
                "UPDATE task_dispatch_outbox SET status = 'claimed', claim_token = ?, dispatcher_id = ?, claim_expires_at = ?, runtime_launch_key = ? WHERE dispatch_id = ? AND status = 'pending'",
                (token, dispatcher_id, expires, launch_key, row["dispatch_id"]),
            )
            if updated.rowcount != 1:
                return None
            conn.commit()
            return DispatchClaim(
                str(row["dispatch_id"]),
                str(row["task_id"]),
                str(row["attempt_id"]),
                token,
                launch_key,
            )

    def mark_runtime_started(self, claim: DispatchClaim) -> str:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT status, claim_token FROM task_dispatch_outbox WHERE dispatch_id = ?",
                (claim.dispatch_id,),
            ).fetchone()
            if row is None or row["status"] != "claimed" or row["claim_token"] != claim.claim_token:
                raise ValueError("Dispatch claim is no longer current")
            runtime_session_id = f"runtime-{uuid4().hex}"
            conn.execute(
                "INSERT INTO agent_runtime_sessions (runtime_session_id, attempt_id, launch_key, status, created_at) VALUES (?, ?, ?, 'starting', ?)",
                (runtime_session_id, claim.attempt_id, claim.runtime_launch_key, _now()),
            )
            conn.execute(
                "UPDATE task_dispatch_outbox SET status = 'dispatched' WHERE dispatch_id = ?",
                (claim.dispatch_id,),
            )
            conn.execute(
                "UPDATE agent_task_attempts SET status = 'starting', started_at = ? WHERE attempt_id = ?",
                (_now(), claim.attempt_id),
            )
            conn.commit()
            return runtime_session_id

    def cancel_pending_for_project(self, project_id: str, *, reason: str) -> int:
        with closing(self._connect()) as conn:
            updated = conn.execute(
                "UPDATE task_dispatch_outbox SET status = 'cancelled', cancel_reason = ? WHERE status IN ('pending', 'claimed') AND task_id IN (SELECT task_id FROM tasks WHERE project_id = ?)",
                (reason, project_id),
            )
            conn.commit()
            return updated.rowcount

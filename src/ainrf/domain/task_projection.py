"""Read-only v2 projections for Tasks, Attempts, RuntimeSessions, and dispatch.

The control-plane writer is :class:`TaskApplicationService`.  HTTP routes must
not recover v2 state through the legacy in-process task service, because that
would make the compatibility runtime an accidental second authority.  This
module intentionally contains no mutations and derives every response from the
authoritative SQLite tables.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Mapping

from ainrf.agentic_researcher.models import TaskOutputEvent
from ainrf.db import connect, run_pending
from ainrf.domain.service import DomainNotFoundError


class TaskProjectionService:
    """Query the durable v2 Task model without exposing a write capability."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_tasks(
        self,
        user: Mapping[str, object],
        *,
        project_id: str | None,
        include_archived: bool,
        limit: int,
        sort: str,
    ) -> list[dict[str, object]]:
        clauses: list[str] = ["1 = 1"]
        params: list[object] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if user.get("role") != "admin":
            user_id = user.get("id")
            if not isinstance(user_id, str) or not user_id:
                return []
            clauses.append("owner_user_id = ?")
            params.append(user_id)
        if not include_archived:
            clauses.append("archived_at IS NULL")

        order_by = {
            "updated": "updated_at DESC, task_id ASC",
            "created": "created_at DESC, task_id ASC",
            "status": "status ASC, updated_at DESC, task_id ASC",
        }.get(sort, "updated_at DESC, task_id ASC")
        query = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY {order_by} LIMIT ?"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, (*params, limit)).fetchall()
        return [self._task_dict(row) for row in rows]

    def task(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise DomainNotFoundError(task_id)
        self._require_visible(row, user)
        return self._task_dict(row)

    def attempts(self, task_id: str, user: Mapping[str, object]) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(task, user)
            rows = conn.execute(
                """SELECT * FROM agent_task_attempts
                   WHERE task_id = ? ORDER BY attempt_seq ASC, created_at ASC""",
                (task_id,),
            ).fetchall()
            return [self._attempt_dict(conn, row) for row in rows]

    def attempt(self, attempt_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT attempt.*, task.owner_user_id
                   FROM agent_task_attempts AS attempt
                   JOIN tasks AS task ON task.task_id = attempt.task_id
                   WHERE attempt.attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(attempt_id)
            self._require_visible(row, user)
            return self._attempt_dict(conn, row)

    def dispatch(self, dispatch_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT dispatch.*, task.owner_user_id
                   FROM task_dispatch_outbox AS dispatch
                   JOIN tasks AS task ON task.task_id = dispatch.task_id
                   WHERE dispatch.dispatch_id = ?""",
                (dispatch_id,),
            ).fetchone()
        if row is None:
            raise DomainNotFoundError(dispatch_id)
        self._require_visible(row, user)
        return self._dispatch_dict(row)

    def outputs(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        after_seq: int,
        limit: int,
    ) -> list[TaskOutputEvent]:
        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(task, user)
            rows = conn.execute(
                """SELECT task_id, seq, kind, content, created_at FROM task_outputs
                   WHERE task_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?""",
                (task_id, after_seq, limit),
            ).fetchall()
        return [
            TaskOutputEvent(
                task_id=str(row["task_id"]),
                seq=int(row["seq"]),
                kind=str(row["kind"]),
                content=str(row["content"]),
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
            for row in rows
        ]

    @staticmethod
    def _require_visible(row: sqlite3.Row, user: Mapping[str, object]) -> None:
        if user.get("role") == "admin":
            return
        if row["owner_user_id"] != user.get("id"):
            # Task ownership is also Task visibility.  Do not distinguish an
            # unauthorized guessed ID from an absent Task.
            raise DomainNotFoundError(str(row["task_id"]))

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "task_id": str(row["task_id"]),
            "project_id": str(row["project_id"]),
            "workspace_id": str(row["workspace_id"]),
            "environment_id": str(row["environment_id"]),
            "researcher_type": str(row["researcher_type"]),
            "harness_engine": str(row["harness_engine"]),
            "status": str(row["status"]),
            "title": str(row["title"]),
            "prompt": str(row["prompt"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "started_at": TaskProjectionService._optional_str(row["started_at"]),
            "completed_at": TaskProjectionService._optional_str(row["completed_at"]),
            "owner_user_id": str(row["owner_user_id"]),
            "latest_output_seq": int(row["latest_output_seq"] or 0),
            "exit_code": int(row["exit_code"]) if row["exit_code"] is not None else None,
            "error_summary": TaskProjectionService._optional_str(row["error_summary"]),
            "working_directory": None,
            "command": [],
            "token_usage_json": TaskProjectionService._optional_str(row["token_usage_json"]),
        }

    def _attempt_dict(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
        runtime_rows = conn.execute(
            """SELECT * FROM agent_runtime_sessions
               WHERE attempt_id = ? ORDER BY created_at ASC""",
            (row["attempt_id"],),
        ).fetchall()
        dispatch_row = conn.execute(
            """SELECT * FROM task_dispatch_outbox
               WHERE attempt_id = ? ORDER BY created_at DESC LIMIT 1""",
            (row["attempt_id"],),
        ).fetchone()
        return {
            "attempt_id": str(row["attempt_id"]),
            "task_id": str(row["task_id"]),
            "attempt_seq": int(row["attempt_seq"]),
            "trigger": str(row["trigger"]),
            "status": str(row["status"]),
            "context_snapshot_id": self._optional_str(row["context_snapshot_id"]),
            "created_at": str(row["created_at"]),
            "started_at": self._optional_str(row["started_at"]),
            "finished_at": self._optional_str(row["finished_at"]),
            "message_start_seq": self._optional_int(row["message_start_seq"]),
            "message_end_seq": self._optional_int(row["message_end_seq"]),
            "output_start_seq": self._optional_int(row["output_start_seq"]),
            "output_end_seq": self._optional_int(row["output_end_seq"]),
            "artifact_refs": self._string_list(row["artifact_refs_json"]),
            "code_refs": self._string_list(row["code_refs_json"]),
            "data_refs": self._string_list(row["data_refs_json"]),
            "token_usage_json": self._optional_str(row["token_usage_json"]),
            "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
            "failure_reason": self._optional_str(row["failure_reason"]),
            "stop_reason": self._optional_str(row["stop_reason"]),
            "authorization_environment_id": self._optional_str(row["authorization_environment_id"]),
            "authorization_grant_version": self._optional_int(row["authorization_grant_version"]),
            "authorization_checked_at": self._optional_str(row["authorization_checked_at"]),
            "stop_requested_at": self._optional_str(row["stop_requested_at"]),
            "stop_requested_reason": self._optional_str(row["stop_requested_reason"]),
            "runtime_sessions": [self._runtime_session_dict(item) for item in runtime_rows],
            "dispatch": self._dispatch_dict(dispatch_row) if dispatch_row is not None else None,
        }

    @staticmethod
    def _runtime_session_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "runtime_session_id": str(row["runtime_session_id"]),
            "attempt_id": str(row["attempt_id"]),
            "status": str(row["status"]),
            "engine_name": TaskProjectionService._optional_str(row["engine_name"]),
            "engine_session_key": TaskProjectionService._optional_str(row["engine_session_key"]),
            "created_at": str(row["created_at"]),
            "started_at": TaskProjectionService._optional_str(row["started_at"]),
            "finished_at": TaskProjectionService._optional_str(row["finished_at"]),
            "last_probe_at": TaskProjectionService._optional_str(row["last_probe_at"]),
            "adopted_at": TaskProjectionService._optional_str(row["adopted_at"]),
            "failure_reason": TaskProjectionService._optional_str(row["failure_reason"]),
        }

    @staticmethod
    def _dispatch_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "dispatch_id": str(row["dispatch_id"]),
            "task_id": str(row["task_id"]),
            "attempt_id": str(row["attempt_id"]),
            "status": str(row["status"]),
            "launch_state": str(row["launch_state"]),
            "runtime_launch_key": TaskProjectionService._optional_str(row["runtime_launch_key"]),
            "dispatcher_id": TaskProjectionService._optional_str(row["dispatcher_id"]),
            "claimed_at": TaskProjectionService._optional_str(row["claimed_at"]),
            "claim_expires_at": TaskProjectionService._optional_str(row["claim_expires_at"]),
            "claim_heartbeat_at": TaskProjectionService._optional_str(row["claim_heartbeat_at"]),
            "created_at": str(row["created_at"]),
            "updated_at": TaskProjectionService._optional_str(row["updated_at"]),
            "completed_at": TaskProjectionService._optional_str(row["completed_at"]),
            "cancelled_at": TaskProjectionService._optional_str(row["cancelled_at"]),
            "cancel_reason": TaskProjectionService._optional_str(row["cancel_reason"]),
            "last_error": TaskProjectionService._optional_str(row["last_error"]),
        }

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return int(value) if isinstance(value, int | float) else None

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        return [item for item in decoded if isinstance(item, str)]

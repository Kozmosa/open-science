"""Read-only v2 projections for Tasks, Attempts, RuntimeSessions, and dispatch.

The control-plane writer is :class:`TaskApplicationService`.  HTTP routes must
not recover v2 state through the legacy in-process task service, because that
would make the compatibility runtime an accidental second authority.  This
module intentionally contains no mutations and derives every response from the
authoritative SQLite tables.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import cast

from ainrf.agentic_researcher.models import TaskOutputEvent
from ainrf.db import connect, run_pending
from ainrf.domain.attempt_projection import AttemptProjectionService
from ainrf.domain.service import DomainNotFoundError


class TaskProjectionService:
    """Query the durable v2 Task model without exposing a write capability."""

    def __init__(
        self,
        state_root: Path,
        *,
        attempt_projection: AttemptProjectionService | None = None,
    ) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._attempt_projection = attempt_projection or AttemptProjectionService(state_root)

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
            attempts_by_task = self._attempt_projection.attempts_for_tasks(
                conn,
                [str(row["task_id"]) for row in rows],
            )
        return [self._task_dict(row, attempts_by_task[str(row["task_id"])]) for row in rows]

    def task(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(row, user)
            attempts = self._attempt_projection.attempts_for_tasks(conn, [task_id])[task_id]
        return self._task_dict(row, attempts)

    def attempts(self, task_id: str, user: Mapping[str, object]) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(task, user)
            return self._attempt_projection.attempts_for_tasks(conn, [task_id])[task_id]

    def attempt(self, attempt_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT attempt.attempt_id, attempt.task_id, task.owner_user_id
                   FROM agent_task_attempts AS attempt
                   JOIN tasks AS task ON task.task_id = attempt.task_id
                   WHERE attempt.attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(attempt_id)
            self._require_visible(row, user)
            attempt = self._attempt_projection.attempt(conn, attempt_id)
            if attempt is None:
                raise DomainNotFoundError(attempt_id)
            return attempt

    def dispatch(self, dispatch_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT dispatch.dispatch_id, dispatch.attempt_id, task.task_id, task.owner_user_id
                   FROM task_dispatch_outbox AS dispatch
                   JOIN tasks AS task ON task.task_id = dispatch.task_id
                   WHERE dispatch.dispatch_id = ?""",
                (dispatch_id,),
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(dispatch_id)
            self._require_visible(row, user)
            attempt = self._attempt_projection.attempt(conn, str(row["attempt_id"]))
        if attempt is None:
            raise DomainNotFoundError(dispatch_id)
        dispatch = attempt.get("dispatch")
        if not isinstance(dispatch, Mapping):
            raise DomainNotFoundError(dispatch_id)
        dispatch_summary = cast(Mapping[str, object], dispatch)
        if dispatch_summary.get("dispatch_id") != dispatch_id:
            raise DomainNotFoundError(dispatch_id)
        return dict(dispatch_summary)

    def token_usage_summary(
        self,
        user: Mapping[str, object],
        *,
        include_archived: bool,
    ) -> dict[str, object]:
        """Return v2 usage derived from Attempt rows, never the legacy Task cache."""

        return self._attempt_projection.task_usage_summary(
            user,
            include_archived=include_archived,
        )

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
    def _task_dict(
        row: sqlite3.Row,
        attempts: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        # The legacy Task timestamps are compatibility caches and can be stale
        # after an Attempt is recovered or adopted by another dispatcher.  The
        # Timeline and every v2 Task response must therefore expose execution
        # bounds derived from the authoritative Attempt/Runtime projection.
        started_at, completed_at = TaskProjectionService._attempt_time_bounds(attempts)
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
            "started_at": started_at,
            "completed_at": completed_at,
            "owner_user_id": str(row["owner_user_id"]),
            "latest_output_seq": int(row["latest_output_seq"] or 0),
            "exit_code": int(row["exit_code"]) if row["exit_code"] is not None else None,
            "error_summary": TaskProjectionService._optional_str(row["error_summary"]),
            "working_directory": None,
            "command": [],
            "token_usage_json": AttemptProjectionService.usage_json(attempts),
        }

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _attempt_time_bounds(
        attempts: Sequence[Mapping[str, object]],
    ) -> tuple[str | None, str | None]:
        """Return Task execution bounds solely from durable Attempt facts.

        An Attempt can derive its timestamps from an adopted RuntimeSession,
        so the already-normalized projection is deliberately used instead of
        reading Task cache columns.  A queued Task has no execution bounds;
        callers retain ``created_at``/``updated_at`` only as display fallbacks.
        """

        started_values = [
            value
            for attempt in attempts
            if isinstance((value := attempt.get("started_at")), str) and value
        ]
        completed_values = [
            value
            for attempt in attempts
            if isinstance((value := attempt.get("finished_at")), str) and value
        ]
        return (
            min(started_values) if started_values else None,
            max(completed_values) if completed_values else None,
        )

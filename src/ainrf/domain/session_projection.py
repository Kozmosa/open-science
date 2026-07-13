"""Read-only legacy Session API projections from Tasks and durable Attempts."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path

from ainrf.db import connect, run_pending
from ainrf.domain.attempt_projection import AttemptProjectionService
from ainrf.domain.service import DomainAuthorizationService, DomainNotFoundError


class SessionProjectionService:
    """Expose compatibility Session shapes without opening ``sessions.sqlite3``.

    A v2 Session ID is a Task ID.  Its attempt list, duration, cost, and
    runtime-derived timestamps are all immutable read projections from the
    authoritative control-plane database.
    """

    def __init__(
        self,
        state_root: Path,
        *,
        attempt_projection: AttemptProjectionService | None = None,
    ) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._attempt_projection = attempt_projection or AttemptProjectionService(state_root)

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_sessions(
        self,
        *,
        project_id: str | None,
        user: Mapping[str, object],
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, object]], int, bool, str | None]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        elif user.get("role") != "admin":
            visibility_clause, visibility_params = self._global_visibility_clause(user)
            if visibility_clause is None:
                return [], 0, False, None
            clauses.append(visibility_clause)
            params.extend(visibility_params)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if cursor is not None:
            clauses.append("task_id < ?")
            params.append(cursor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with closing(self._connect()) as conn:
            if project_id is not None:
                DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM tasks {where}",
                    tuple(params),
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""SELECT * FROM tasks {where}
                     ORDER BY task_id DESC LIMIT ?""",
                (*params, limit + 1),
            ).fetchall()
            visible_rows = rows[:limit]
            task_ids = [str(row["task_id"]) for row in visible_rows]
            attempts_by_task = self._attempt_projection.attempts_for_tasks(conn, task_ids)

        items = [
            self._session_dict(row, attempts_by_task[str(row["task_id"])]) for row in visible_rows
        ]
        has_more = len(rows) > limit
        next_cursor = str(visible_rows[-1]["task_id"]) if has_more and visible_rows else None
        return items, total, has_more, next_cursor

    def get_session(
        self, task_id: str, user: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise DomainNotFoundError(task_id)
            DomainAuthorizationService(conn).require_task_viewer(task_id, dict(user))
            attempts_by_task = self._attempt_projection.attempts_for_tasks(conn, [task_id])
        attempts = attempts_by_task[task_id]
        return self._session_dict(row, attempts), [
            self._legacy_attempt_dict(item) for item in attempts
        ]

    def batch_details(
        self,
        task_ids: Sequence[str],
        user: dict[str, object],
    ) -> dict[str, list[dict[str, object]]]:
        unique_task_ids = tuple(dict.fromkeys(task_id for task_id in task_ids if task_id))
        result: dict[str, list[dict[str, object]]] = {task_id: [] for task_id in unique_task_ids}
        if not unique_task_ids:
            return result
        placeholders = ", ".join("?" for _ in unique_task_ids)
        with closing(self._connect()) as conn:
            task_rows = conn.execute(
                f"SELECT * FROM tasks WHERE task_id IN ({placeholders})",
                unique_task_ids,
            ).fetchall()
            visible_task_ids: list[str] = []
            for row in task_rows:
                try:
                    DomainAuthorizationService(conn).require_task_viewer(
                        str(row["task_id"]), dict(user)
                    )
                except DomainNotFoundError:
                    # Preserve the legacy batch shape without confirming that
                    # an invisible Task exists.
                    continue
                visible_task_ids.append(str(row["task_id"]))
            attempts_by_task = self._attempt_projection.attempts_for_tasks(conn, visible_task_ids)

        for task_id in visible_task_ids:
            result[task_id] = [
                self._legacy_attempt_dict(attempt) for attempt in attempts_by_task[task_id]
            ]
        return result

    @staticmethod
    def _global_visibility_clause(user: Mapping[str, object]) -> tuple[str | None, list[object]]:
        """Return the B3 Task/Project viewer predicate before pagination."""

        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            return None, []
        return (
            """(
                owner_user_id = ?
                OR EXISTS (
                    SELECT 1 FROM projects AS visible_project
                    WHERE visible_project.project_id = tasks.project_id
                      AND (
                          visible_project.owner_user_id = ?
                          OR EXISTS (
                              SELECT 1 FROM project_members AS visible_member
                              WHERE visible_member.project_id = tasks.project_id
                                AND visible_member.user_id = ?
                          )
                      )
                )
            )""",
            [user_id, user_id, user_id],
        )

    @staticmethod
    def _session_dict(
        row: sqlite3.Row,
        attempts: Sequence[dict[str, object]],
    ) -> dict[str, object]:
        aggregate = AttemptProjectionService.aggregate(attempts)
        return {
            "id": str(row["task_id"]),
            "project_id": str(row["project_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "task_count": aggregate.attempt_count,
            "total_duration_ms": aggregate.duration_ms,
            "total_cost_usd": aggregate.cost_usd,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "owner_user_id": str(row["owner_user_id"]),
        }

    @staticmethod
    def _legacy_attempt_dict(attempt: dict[str, object]) -> dict[str, object]:
        attempt_seq = attempt.get("attempt_seq")
        return {
            "id": str(attempt["attempt_id"]),
            "session_id": str(attempt["task_id"]),
            "task_id": str(attempt["task_id"]),
            "parent_attempt_id": None,
            "attempt_seq": int(attempt_seq) if isinstance(attempt_seq, int | float) else 0,
            "intervention_reason": str(attempt["trigger"]),
            "status": str(attempt["status"]),
            "started_at": attempt.get("started_at"),
            "finished_at": attempt.get("finished_at"),
            "duration_ms": attempt.get("duration_ms"),
            "token_usage_json": attempt.get("token_usage_json"),
            "created_at": str(attempt["created_at"]),
        }

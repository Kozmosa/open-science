"""Read-only legacy Session API projections from Task and TaskAttempt."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from ainrf.db import connect, run_pending
from ainrf.domain.service import DomainNotFoundError, DomainPermissionError


class SessionProjectionService:
    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_sessions(
        self, *, project_id: str | None, owner_user_id: str | None, limit: int
    ) -> tuple[list[dict[str, object]], int]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id is not None:
            clauses.append("t.project_id = ?")
            params.append(project_id)
        if owner_user_id is not None:
            clauses.append("t.owner_user_id = ?")
            params.append(owner_user_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as conn:
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM tasks t {where}", tuple(params)).fetchone()[0]
            )
            rows = conn.execute(
                f"""SELECT t.task_id, t.project_id, t.title, t.status, t.owner_user_id, t.created_at, t.updated_at,
                           COUNT(a.attempt_id) AS attempt_count
                    FROM tasks t LEFT JOIN agent_task_attempts a ON a.task_id = t.task_id
                    {where} GROUP BY t.task_id ORDER BY t.updated_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [self._session_dict(row) for row in rows], total

    def get_session(
        self, task_id: str, user: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT t.task_id, t.project_id, t.title, t.status, t.owner_user_id, t.created_at, t.updated_at,
                           COUNT(a.attempt_id) AS attempt_count
                    FROM tasks t LEFT JOIN agent_task_attempts a ON a.task_id = t.task_id
                    WHERE t.task_id = ? GROUP BY t.task_id""",
                (task_id,),
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(task_id)
            if user.get("role") != "admin" and row["owner_user_id"] != user.get("id"):
                raise DomainPermissionError("Session projection is not visible")
            attempts = conn.execute(
                "SELECT * FROM agent_task_attempts WHERE task_id = ? ORDER BY attempt_seq",
                (task_id,),
            ).fetchall()
        return self._session_dict(row), [self._attempt_dict(item) for item in attempts]

    @staticmethod
    def _session_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["task_id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "status": row["status"],
            "task_count": int(row["attempt_count"]),
            "total_duration_ms": 0,
            "total_cost_usd": 0.0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _attempt_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["attempt_id"],
            "session_id": row["task_id"],
            "task_id": row["task_id"],
            "parent_attempt_id": None,
            "attempt_seq": row["attempt_seq"],
            "intervention_reason": row["trigger"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": None,
            "token_usage_json": None,
            "created_at": row["created_at"],
        }

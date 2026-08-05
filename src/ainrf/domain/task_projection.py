"""Read-only queries over the canonical Conversation Task model."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_projection import (
    ConversationProjectionService,
    ConversationTaskProjection,
)
from ainrf.domain.service import DomainAuthorizationService, DomainNotFoundError


class TaskProjectionService:
    """Expose Task summaries from the canonical Conversation projection."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._conversation_projection = ConversationProjectionService()

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
        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses = ["1 = 1"]
        params: list[object] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        elif user.get("role") != "admin":
            visibility, visibility_params = self._global_visibility_clause(user)
            if visibility is None:
                return []
            clauses.append(visibility)
            params.extend(visibility_params)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        order_by = {
            "updated": "updated_at DESC, task_id ASC",
            "created": "created_at DESC, task_id ASC",
            "status": "status ASC, updated_at DESC, task_id ASC",
        }.get(sort, "updated_at DESC, task_id ASC")
        query = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY {order_by} LIMIT ?"
        with closing(self._connect()) as conn:
            if project_id:
                DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            rows = conn.execute(query, (*params, limit)).fetchall()
            projections = self._projection_inputs(conn, rows)
        return [
            self._task_dict(
                row,
                conversation=projections.get(str(row["task_id"])),
                include_private_task_diagnostics=self._can_view_unredacted_output(row, user),
            )
            for row in rows
        ]

    def list_project_tasks(
        self,
        project_id: str,
        user: Mapping[str, object],
        *,
        include_archived: bool,
        limit: int,
        sort: str,
    ) -> dict[str, object]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        order_by = {
            "updated": "updated_at DESC, task_id ASC",
            "created": "created_at DESC, task_id ASC",
            "status": "status ASC, updated_at DESC, task_id ASC",
        }.get(sort, "updated_at DESC, task_id ASC")
        clauses = ["project_id = ?"]
        params: list[object] = [project_id]
        if not include_archived:
            clauses.append("archived_at IS NULL")
        where = " AND ".join(clauses)
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM tasks WHERE {where}", params
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {where} ORDER BY {order_by} LIMIT ?",
                (*params, limit),
            ).fetchall()
            projections = self._projection_inputs(conn, rows)
        return {
            "items": [
                self._task_dict(
                    row,
                    conversation=projections.get(str(row["task_id"])),
                    include_private_task_diagnostics=self._can_view_unredacted_output(row, user),
                )
                for row in rows
            ],
            "total": 0 if total_row is None else int(total_row["count"]),
        }

    def task(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(conn, task_id, user)
            projection = self._projection_inputs(conn, [row]).get(task_id)
        return self._task_dict(
            row,
            conversation=projection,
            include_private_task_diagnostics=self._can_view_unredacted_output(row, user),
        )

    def health(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        """Return durable execution health from canonical projections."""

        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(conn, task_id, user)
            projection = self._projection_inputs(conn, [task]).get(task_id)
        if projection is None:
            return {
                "task_id": task_id,
                "status": str(task["status"]),
                "engine_alive": False,
                "last_event_at": str(task["updated_at"]),
            }
        return {
            "task_id": task_id,
            "status": projection.status,
            "engine_alive": projection.execution_alive,
            "last_event_at": projection.last_event_at,
        }

    def token_usage_summary(
        self,
        user: Mapping[str, object],
        *,
        include_archived: bool,
    ) -> dict[str, object]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if user.get("role") != "admin":
            visibility, visibility_params = self._global_visibility_clause(user)
            if visibility is None:
                return ConversationProjectionService.usage_summary_for_tasks((), {})
            clauses.append(visibility)
            params.extend(visibility_params)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)}", tuple(params)
            ).fetchall()
            projections = self._projection_inputs(conn, rows)
        return ConversationProjectionService.usage_summary_for_tasks(rows, projections)

    def project_usage_summary(
        self, project_id: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY task_id", (project_id,)
            ).fetchall()
            projections = self._projection_inputs(conn, rows)
        usage = ConversationProjectionService.usage_summary_for_tasks(rows, projections)
        return {
            "project_id": project_id,
            "task_count": len(rows),
            "attempt_count": sum(len(projection.turns) for projection in projections.values()),
            "total_duration_ms": usage["total_duration_ms"],
            "total_cost_usd": usage["total_cost_usd"],
            "total_tokens": usage["total_tokens"],
            "by_model": usage["by_model"],
        }

    @staticmethod
    def _require_visible(
        conn: sqlite3.Connection, task_id: str, user: Mapping[str, object]
    ) -> None:
        DomainAuthorizationService(conn).require_task_viewer(task_id, dict(user))

    @staticmethod
    def _can_view_unredacted_output(
        task: sqlite3.Row, user: Mapping[str, object]
    ) -> bool:
        return user.get("role") == "admin" or user.get("id") == task["owner_user_id"]

    @staticmethod
    def _global_visibility_clause(user: Mapping[str, object]) -> tuple[str | None, list[object]]:
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
    def _task_dict(
        row: sqlite3.Row,
        *,
        conversation: ConversationTaskProjection | None,
        include_private_task_diagnostics: bool,
    ) -> dict[str, object]:
        return {
            "task_id": str(row["task_id"]),
            "project_id": str(row["project_id"]),
            "workspace_id": str(row["workspace_id"]),
            "environment_id": str(row["environment_id"]),
            "researcher_type": str(row["researcher_type"]),
            "harness_engine": str(row["harness_engine"]),
            "status": conversation.status if conversation is not None else str(row["status"]),
            "title": str(row["title"]),
            "prompt": str(row["prompt"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "started_at": (
                conversation.started_at if conversation is not None else row["started_at"]
            ),
            "completed_at": (
                conversation.completed_at if conversation is not None else row["completed_at"]
            ),
            "owner_user_id": str(row["owner_user_id"]),
            "archived_at": row["archived_at"] if isinstance(row["archived_at"], str) else None,
            "archive_reason": (
                row["archive_reason"] if isinstance(row["archive_reason"], str) else None
            ),
            "project_context_version_id": (
                row["project_context_version_id"]
                if isinstance(row["project_context_version_id"], str)
                else None
            ),
            "latest_output_seq": 0 if conversation is None else conversation.latest_item_seq,
            "exit_code": int(row["exit_code"]) if row["exit_code"] is not None else None,
            "error_summary": (
                conversation.error_summary
                if conversation is not None and include_private_task_diagnostics
                else (
                    row["error_summary"]
                    if include_private_task_diagnostics
                    and isinstance(row["error_summary"], str)
                    else None
                )
            ),
            "working_directory": None,
            "command": [],
            "token_usage_json": (
                ConversationProjectionService.usage_json(conversation)
                if conversation is not None
                else None
            ),
        }

    def _projection_inputs(
        self, conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]
    ) -> dict[str, ConversationTaskProjection]:
        return self._conversation_projection.projections_for_tasks(
            conn, [str(row["task_id"]) for row in rows]
        )

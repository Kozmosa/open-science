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
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ainrf.agentic_researcher.models import TaskOutputEvent
from ainrf.db import connect, run_pending
from ainrf.domain.attempt_projection import AttemptProjectionService
from ainrf.domain.output_redaction import redact_task_output_for_viewer
from ainrf.domain.service import DomainAuthorizationService, DomainNotFoundError


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
        elif user.get("role") != "admin":
            visibility_clause, visibility_params = self._global_visibility_clause(user)
            if visibility_clause is None:
                return []
            clauses.append(visibility_clause)
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
            attempts_by_task = self._attempt_projection.attempts_for_tasks(
                conn,
                [str(row["task_id"]) for row in rows],
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )
        return [
            self._task_dict(
                row,
                attempts_by_task[str(row["task_id"])],
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
        """List every Task visible through a Project collaboration membership.

        Project membership deliberately differs from the global Task list:
        an editor or viewer may inspect the Project's shared work even where
        they are not the Task owner.  The caller still receives the same
        Attempt-derived serialization used everywhere else in v2; this method
        is only the authorization and scope-specific query boundary.
        """

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
            attempts_by_task = self._attempt_projection.attempts_for_tasks(
                conn,
                [str(row["task_id"]) for row in rows],
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )
        total = int(total_row["count"]) if total_row is not None else 0
        return {
            "items": [
                self._task_dict(
                    row,
                    attempts_by_task[str(row["task_id"])],
                    include_private_task_diagnostics=self._can_view_unredacted_output(row, user),
                )
                for row in rows
            ],
            "total": total,
        }

    def task(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(conn, task_id, user)
            attempts = self._attempt_projection.attempts_for_tasks(
                conn,
                [task_id],
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )[task_id]
        return self._task_dict(
            row,
            attempts,
            include_private_task_diagnostics=self._can_view_unredacted_output(row, user),
        )

    def attempts(self, task_id: str, user: Mapping[str, object]) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(conn, task_id, user)
            return self._attempt_projection.attempts_for_tasks(
                conn,
                [task_id],
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )[task_id]

    def health(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        """Return Task health from the durable Attempt/Runtime projection.

        The v2 API must not ask the legacy in-process engine registry whether a
        Task is alive: after a dispatcher restart that registry is neither
        authoritative nor necessarily present.  RuntimeSession status is the
        last durable liveness observation, and Task output or runtime probe
        timestamps provide the last known activity without creating a probe as
        a side effect of this read endpoint.
        """

        with closing(self._connect()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            self._require_visible(conn, task_id, user)
            attempts = self._attempt_projection.attempts_for_tasks(
                conn,
                [task_id],
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )[task_id]
            output_row = conn.execute(
                """SELECT created_at FROM task_outputs
                   WHERE task_id = ?
                   ORDER BY created_at DESC, seq DESC
                   LIMIT 1""",
                (task_id,),
            ).fetchone()

        runtime_sessions: list[Mapping[str, object]] = []
        for attempt in attempts:
            raw_runtime_sessions = attempt.get("runtime_sessions")
            if not isinstance(raw_runtime_sessions, Sequence):
                continue
            for runtime in raw_runtime_sessions:
                if isinstance(runtime, Mapping):
                    runtime_sessions.append(cast(Mapping[str, object], runtime))
        runtime_alive = any(
            runtime.get("status") in {"starting", "running", "paused"}
            for runtime in runtime_sessions
        )
        observed_at: list[str] = []
        if output_row is not None and isinstance(output_row["created_at"], str):
            observed_at.append(output_row["created_at"])
        observed_at.extend(
            value
            for runtime in runtime_sessions
            for value in (runtime.get("last_probe_at"),)
            if isinstance(value, str) and value
        )
        return {
            "task_id": task_id,
            "status": str(task["status"]),
            "engine_alive": runtime_alive,
            "last_event_at": self._latest_timestamp(observed_at),
        }

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
            self._require_visible(conn, str(row["task_id"]), user)
            attempt = self._attempt_projection.attempt(
                conn,
                attempt_id,
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )
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
            self._require_visible(conn, str(row["task_id"]), user)
            attempt = self._attempt_projection.attempt(
                conn,
                str(row["attempt_id"]),
                include_runtime_diagnostics=self._can_view_runtime_diagnostics(user),
            )
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
            self._require_visible(conn, task_id, user)
            redact_output = not self._can_view_unredacted_output(task, user)
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
                content=(
                    redact_task_output_for_viewer(str(row["content"]))
                    if redact_output
                    else str(row["content"])
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
            for row in rows
        ]

    @staticmethod
    def _require_visible(
        conn: sqlite3.Connection,
        task_id: str,
        user: Mapping[str, object],
    ) -> None:
        """Apply the B3 Project-viewer matrix to Task/Attempt reads."""

        DomainAuthorizationService(conn).require_task_viewer(task_id, dict(user))

    @staticmethod
    def _can_view_runtime_diagnostics(user: Mapping[str, object]) -> bool:
        """Only a management/troubleshooting administrator sees raw runtime IDs."""

        return user.get("role") == "admin"

    @staticmethod
    def _can_view_unredacted_output(
        task: sqlite3.Row,
        user: Mapping[str, object],
    ) -> bool:
        """Keep raw output within the Task-owner or admin troubleshooting scope.

        Project membership makes a Task visible, but does not grant the
        Workspace/tenant authority that may have produced credentials or
        filesystem locations in an engine event.  This mirrors the existing
        runtime-diagnostics projection while retaining raw evidence for the
        Task owner and the administrator-only troubleshooting surface.
        """

        return user.get("role") == "admin" or user.get("id") == task["owner_user_id"]

    @staticmethod
    def _global_visibility_clause(user: Mapping[str, object]) -> tuple[str | None, list[object]]:
        """Return the shared-project visibility predicate for collection reads.

        Detail reads delegate to :class:`DomainAuthorizationService`; list
        reads need the equivalent SQL predicate before pagination so an owner
        cannot accidentally receive a partial page that omits shared Tasks.
        A Project link never grants Workspace access: this predicate only
        exposes the Task/Attempt projection explicitly allowed to viewers.
        """

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
        attempts: Sequence[Mapping[str, object]],
        *,
        include_private_task_diagnostics: bool,
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
            "archived_at": TaskProjectionService._optional_str(row["archived_at"]),
            "archive_reason": TaskProjectionService._optional_str(row["archive_reason"]),
            "project_context_version_id": TaskProjectionService._optional_str(
                row["project_context_version_id"]
            ),
            "latest_output_seq": int(row["latest_output_seq"] or 0),
            "exit_code": int(row["exit_code"]) if row["exit_code"] is not None else None,
            # Engine error summaries are durable operational diagnostics and
            # can contain a tenant-private path.  A shared Project viewer can
            # inspect status plus redacted output, but only the Task owner or
            # an admin troubleshooting surface gets this raw summary.
            "error_summary": (
                TaskProjectionService._optional_str(row["error_summary"])
                if include_private_task_diagnostics
                else None
            ),
            "working_directory": None,
            "command": [],
            "token_usage_json": AttemptProjectionService.usage_json(attempts),
        }

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _latest_timestamp(values: Sequence[str]) -> str | None:
        """Choose the latest well-formed ISO-8601 timestamp deterministically."""

        parsed: list[tuple[datetime, str]] = []
        for value in values:
            try:
                observed_at = datetime.fromisoformat(value)
            except ValueError:
                continue
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            parsed.append((observed_at, value))
        return max(parsed, key=lambda item: item[0])[1] if parsed else None

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

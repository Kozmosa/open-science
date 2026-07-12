"""Standard v2 Task application service with one transactional write path."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.service import (
    DomainAuthorizationService,
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskApplicationService:
    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _user_id(user: dict[str, object]) -> str:
        value = user.get("id")
        if not isinstance(value, str) or not value:
            raise DomainPermissionError("Authenticated user ID is required")
        return value

    def create_task(
        self,
        user: dict[str, object],
        *,
        project_id: str,
        workspace_id: str,
        title: str,
        prompt: str,
        researcher_type: str,
        harness_engine: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        with closing(self._connect()) as conn:
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            cached = self._cached(conn, "task.create", idempotency_key)
            if cached is not None:
                return cached
            link = conn.execute(
                "SELECT 1 FROM project_workspace_links WHERE project_id = ? AND workspace_id = ? AND status = 'active'",
                (project_id, workspace_id),
            ).fetchone()
            workspace = conn.execute(
                "SELECT environment_id FROM workspaces WHERE workspace_id = ? AND status = 'active'",
                (workspace_id,),
            ).fetchone()
            context = conn.execute(
                "SELECT context_version_id, content, fingerprint FROM project_context_versions WHERE project_id = ? AND is_active = 1",
                (project_id,),
            ).fetchone()
            if link is None or workspace is None:
                raise DomainConflictError("Task Workspace must be an active Project link")
            if context is None:
                raise DomainConflictError("Project requires an active Context Version")
            task_id = uuid4().hex[:12]
            snapshot_id = f"snapshot-{uuid4().hex}"
            attempt_id = f"attempt-{uuid4().hex}"
            dispatch_id = f"dispatch-{uuid4().hex}"
            now = _now()
            conn.execute(
                "INSERT INTO context_snapshots(context_snapshot_id, context_version_id, fingerprint, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    context["context_version_id"],
                    context["fingerprint"],
                    context["content"],
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, workspace_id, environment_id, researcher_type, harness_engine, user_skills, user_mcp_servers, status, title, prompt, created_at, updated_at, owner_user_id, project_context_version_id, latest_attempt_id) VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', 'queued', ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    project_id,
                    workspace_id,
                    workspace["environment_id"],
                    researcher_type,
                    harness_engine,
                    title,
                    prompt,
                    now,
                    now,
                    self._user_id(user),
                    context["context_version_id"],
                    attempt_id,
                ),
            )
            conn.execute(
                "INSERT INTO agent_task_attempts(attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at) VALUES (?, ?, 1, 'initial', 'queued', ?, ?)",
                (attempt_id, task_id, snapshot_id, now),
            )
            conn.execute(
                "INSERT INTO task_dispatch_outbox(dispatch_id, task_id, attempt_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (dispatch_id, task_id, attempt_id, now),
            )
            result = {"task_id": task_id, "attempt_id": attempt_id, "dispatch_id": dispatch_id}
            self._store(conn, "task.create", idempotency_key, result)
            self._audit(conn, self._user_id(user), "task.created", "task", task_id)
            conn.commit()
            return result

    def retry_task(
        self, task_id: str, user: dict[str, object], *, idempotency_key: str
    ) -> dict[str, str]:
        with closing(self._connect()) as conn:
            task = conn.execute(
                "SELECT project_id, owner_user_id, project_context_version_id FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            if task["owner_user_id"] != user.get("id"):
                raise DomainPermissionError("Only the Task owner can retry a Task")
            cached = self._cached(conn, "task.retry", idempotency_key)
            if cached is not None:
                return cached
            snapshot = conn.execute(
                "SELECT context_snapshot_id FROM context_snapshots WHERE context_version_id = ? ORDER BY created_at DESC LIMIT 1",
                (task["project_context_version_id"],),
            ).fetchone()
            if snapshot is None:
                raise DomainConflictError("Task has no Context snapshot")
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(attempt_seq), 0) + 1 FROM agent_task_attempts WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            attempt_id = f"attempt-{uuid4().hex}"
            dispatch_id = f"dispatch-{uuid4().hex}"
            now = _now()
            conn.execute(
                "INSERT INTO agent_task_attempts(attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at) VALUES (?, ?, ?, 'retry', 'queued', ?, ?)",
                (attempt_id, task_id, sequence, snapshot["context_snapshot_id"], now),
            )
            conn.execute(
                "INSERT INTO task_dispatch_outbox(dispatch_id, task_id, attempt_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (dispatch_id, task_id, attempt_id, now),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id = ?, status = 'queued', updated_at = ? WHERE task_id = ?",
                (attempt_id, now, task_id),
            )
            result = {"task_id": task_id, "attempt_id": attempt_id, "dispatch_id": dispatch_id}
            self._store(conn, "task.retry", idempotency_key, result)
            self._audit(conn, self._user_id(user), "task.retried", "task", task_id)
            conn.commit()
            return result

    def archive_project(self, project_id: str, user: dict[str, object], *, reason: str) -> int:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            project = conn.execute(
                "SELECT is_default FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise DomainNotFoundError(project_id)
            if bool(project["is_default"]):
                raise DomainConflictError("Default projects cannot be archived")
            now = _now()
            cancelled = conn.execute(
                "UPDATE task_dispatch_outbox SET status = 'cancelled', cancel_reason = ? WHERE status IN ('pending', 'claimed') AND task_id IN (SELECT task_id FROM tasks WHERE project_id = ?)",
                (reason, project_id),
            ).rowcount
            conn.execute(
                "UPDATE agent_task_attempts SET status = 'cancelled', finished_at = ? WHERE status = 'queued' AND task_id IN (SELECT task_id FROM tasks WHERE project_id = ?)",
                (now, project_id),
            )
            conn.execute(
                "UPDATE tasks SET status = 'cancelled', archived_at = ?, archive_reason = ?, updated_at = ? WHERE project_id = ? AND status = 'queued'",
                (now, reason, now, project_id),
            )
            conn.execute(
                "UPDATE projects SET status = 'archived', archived_at = ?, archive_reason = ?, updated_at = ? WHERE project_id = ?",
                (now, reason, now, project_id),
            )
            self._audit(conn, self._user_id(user), "project.archived", "project", project_id)
            conn.commit()
            return cancelled

    @staticmethod
    def _cached(conn: sqlite3.Connection, scope: str, key: str) -> dict[str, str] | None:
        if not key:
            raise DomainConflictError("idempotency_key is required")
        row = conn.execute(
            "SELECT response_json FROM domain_idempotency_requests WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        return (
            {str(k): str(v) for k, v in json.loads(row["response_json"]).items()}
            if row is not None
            else None
        )

    @staticmethod
    def _store(conn: sqlite3.Connection, scope: str, key: str, result: dict[str, str]) -> None:
        request_hash = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        conn.execute(
            "INSERT INTO domain_idempotency_requests(scope, idempotency_key, request_hash, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, key, request_hash, json.dumps(result, sort_keys=True), _now()),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection, actor_id: str, event_type: str, subject_type: str, subject_id: str
    ) -> None:
        conn.execute(
            "INSERT INTO domain_audit_events(event_id, actor_id, event_type, subject_type, subject_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )

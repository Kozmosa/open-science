"""Project Context draft, version, snapshot, and Task pin services."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.service import (
    DomainAuthorizationService,
    DomainNotFoundError,
    DomainPermissionError,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ProjectContextService:
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

    def save_draft(self, project_id: str, content: str, user: dict[str, object]) -> None:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            conn.execute(
                """INSERT INTO project_context_drafts(project_id, content, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET content = excluded.content,
                       updated_by_user_id = excluded.updated_by_user_id, updated_at = excluded.updated_at""",
                (project_id, content, self._user_id(user), _now()),
            )
            conn.commit()

    def publish(self, project_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            draft = conn.execute(
                "SELECT content FROM project_context_drafts WHERE project_id = ?", (project_id,)
            ).fetchone()
            if draft is None:
                raise DomainNotFoundError("project context draft")
            version_id = f"context-{uuid4().hex}"
            content = str(draft["content"])
            conn.execute(
                "UPDATE project_context_versions SET is_active = 0 WHERE project_id = ?",
                (project_id,),
            )
            conn.execute(
                """INSERT INTO project_context_versions
                   (context_version_id, project_id, content, fingerprint, is_active, created_by_user_id, created_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (
                    version_id,
                    project_id,
                    content,
                    _fingerprint(content),
                    self._user_id(user),
                    _now(),
                ),
            )
            conn.commit()
            return {"context_version_id": version_id, "fingerprint": _fingerprint(content)}

    def pin_active_context(self, task_id: str, project_id: str) -> str:
        with closing(self._connect()) as conn:
            version = conn.execute(
                "SELECT context_version_id, content, fingerprint FROM project_context_versions WHERE project_id = ? AND is_active = 1",
                (project_id,),
            ).fetchone()
            if version is None:
                raise DomainNotFoundError("active project context version")
            snapshot_id = self._create_snapshot(conn, version)
            conn.execute(
                "UPDATE tasks SET project_context_version_id = ? WHERE task_id = ?",
                (version["context_version_id"], task_id),
            )
            conn.commit()
            return snapshot_id

    def update_task_context(self, task_id: str, project_id: str, user: dict[str, object]) -> str:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            task = conn.execute(
                "SELECT owner_user_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            if user.get("role") != "admin" and task["owner_user_id"] != user.get("id"):
                raise DomainPermissionError("Only the Task owner can update Task context")
        return self.pin_active_context(task_id, project_id)

    @staticmethod
    def _create_snapshot(conn: sqlite3.Connection, version: sqlite3.Row) -> str:
        snapshot_id = f"snapshot-{uuid4().hex}"
        conn.execute(
            "INSERT INTO context_snapshots(context_snapshot_id, context_version_id, fingerprint, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                snapshot_id,
                version["context_version_id"],
                version["fingerprint"],
                version["content"],
                _now(),
            ),
        )
        return snapshot_id

"""SQLite repositories and application services for the v2 control plane."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending


class DomainNotFoundError(LookupError):
    pass


class DomainPermissionError(PermissionError):
    pass


class DomainConflictError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainAuthorizationService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def project_role(self, project_id: str, user: dict[str, object]) -> str | None:
        if user.get("role") == "admin":
            return "admin"
        row = self._conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        if row["owner_user_id"] == user.get("id"):
            return "owner"
        member = self._conn.execute(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user.get("id")),
        ).fetchone()
        return str(member["role"]) if member is not None else None

    def require_project_editor(self, project_id: str, user: dict[str, object]) -> None:
        if self.project_role(project_id, user) not in {"admin", "owner", "editor"}:
            raise DomainPermissionError("Project editor permission is required")

    def require_project_owner(self, project_id: str, user: dict[str, object]) -> None:
        if self.project_role(project_id, user) not in {"admin", "owner"}:
            raise DomainPermissionError("Project owner permission is required")

    def require_workspace_owner(self, workspace_id: str, user: dict[str, object]) -> None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise DomainNotFoundError(workspace_id)
        # Administration does not confer Linux tenant execution rights.
        if row["owner_user_id"] != user.get("id"):
            raise DomainPermissionError("Workspace owner permission is required")


class DomainService:
    """All v2 writes are transactionally routed through this application service."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def v2_ready(self) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT constraints_ready, cutover_ready FROM domain_cutover_state WHERE singleton = 1"
            ).fetchone()
        return row is not None and bool(row["constraints_ready"]) and bool(row["cutover_ready"])

    def create_project(
        self,
        user: dict[str, object],
        *,
        name: str,
        description: str | None = None,
        is_default: bool = False,
    ) -> dict[str, object]:
        owner_id = self._user_id(user)
        project_id = f"project-{uuid4().hex[:12]}"
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO projects (project_id, owner_user_id, name, description, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, owner_id, name, description, int(is_default), now, now),
            )
            self._audit(conn, owner_id, "project.created", "project", project_id)
            conn.commit()
        return self.project(project_id, user)

    def create_environment(
        self,
        user: dict[str, object],
        *,
        alias: str,
        display_name: str,
        connection: dict[str, object],
        credential_ref: str | None = None,
    ) -> dict[str, object]:
        if user.get("role") != "admin":
            raise DomainPermissionError("Only admins can register environments")
        environment_id = f"env-{uuid4().hex}"
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO environments (environment_id, alias, owner_user_id, display_name, connection_json, credential_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    environment_id,
                    alias,
                    self._user_id(user),
                    display_name,
                    json.dumps(connection, sort_keys=True),
                    credential_ref,
                    now,
                    now,
                ),
            )
            self._audit(
                conn, self._user_id(user), "environment.created", "environment", environment_id
            )
            conn.commit()
        return self.environment(environment_id, user)

    def disable_environment(self, environment_id: str, user: dict[str, object]) -> None:
        if user.get("role") != "admin":
            raise DomainPermissionError("Only admins can disable environments")
        with closing(self._connect()) as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)
                ).fetchone()
                is None
            ):
                raise DomainNotFoundError(environment_id)
            conn.execute(
                "UPDATE environments SET status = 'disabled', updated_at = ? WHERE environment_id = ?",
                (_now(), environment_id),
            )
            self._audit(
                conn, self._user_id(user), "environment.disabled", "environment", environment_id
            )
            conn.commit()

    def create_workspace(
        self,
        user: dict[str, object],
        *,
        environment_id: str,
        canonical_path: str,
        label: str,
        description: str | None = None,
    ) -> dict[str, object]:
        owner_id = self._user_id(user)
        path = str(Path(canonical_path).expanduser().resolve())
        workspace_id = f"workspace-{uuid4().hex[:12]}"
        now = _now()
        with closing(self._connect()) as conn:
            environment = conn.execute(
                "SELECT status FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
            if environment is None or environment["status"] != "active":
                raise DomainConflictError("Workspace requires an active environment")
            conn.execute(
                "INSERT INTO workspaces (workspace_id, owner_user_id, environment_id, canonical_path, label, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (workspace_id, owner_id, environment_id, path, label, description, now, now),
            )
            self._audit(conn, owner_id, "workspace.created", "workspace", workspace_id)
            conn.commit()
        return self.workspace(workspace_id, user)

    def attach_workspace(
        self, project_id: str, workspace_id: str, user: dict[str, object], *, idempotency_key: str
    ) -> dict[str, object]:
        return self._link_operation(
            project_id, workspace_id, user, idempotency_key=idempotency_key, make_primary=False
        )

    def set_primary_workspace(
        self, project_id: str, workspace_id: str, user: dict[str, object], *, idempotency_key: str
    ) -> dict[str, object]:
        return self._link_operation(
            project_id, workspace_id, user, idempotency_key=idempotency_key, make_primary=True
        )

    def detach_workspace(
        self,
        project_id: str,
        workspace_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
        allow_no_primary: bool = False,
    ) -> None:
        with closing(self._connect()) as conn:
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            cached = self._idempotent_result(conn, "workspace.detach", idempotency_key)
            if cached is not None:
                return
            link = conn.execute(
                "SELECT is_primary FROM project_workspace_links WHERE project_id = ? AND workspace_id = ? AND status = 'active'",
                (project_id, workspace_id),
            ).fetchone()
            if link is None:
                raise DomainNotFoundError("project workspace link")
            if bool(link["is_primary"]) and not allow_no_primary:
                raise DomainConflictError("Detach primary requires replacement or allow_no_primary")
            conn.execute(
                "UPDATE project_workspace_links SET status = 'retired', is_primary = 0, updated_at = ? WHERE project_id = ? AND workspace_id = ?",
                (_now(), project_id, workspace_id),
            )
            self._store_idempotency(conn, "workspace.detach", idempotency_key, {"detached": True})
            self._audit(conn, self._user_id(user), "workspace.detached", "workspace", workspace_id)
            conn.commit()

    def add_member(
        self,
        project_id: str,
        member_user_id: str,
        role: str,
        can_publish: bool,
        user: dict[str, object],
    ) -> None:
        if role not in {"viewer", "editor"}:
            raise DomainConflictError("Unknown project role")
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            conn.execute(
                "INSERT INTO project_members (project_id, user_id, role, can_publish, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role, can_publish = excluded.can_publish, updated_at = excluded.updated_at",
                (project_id, member_user_id, role, int(can_publish), _now(), _now()),
            )
            self._audit(conn, self._user_id(user), "project.member.updated", "project", project_id)
            conn.commit()

    def archive_project(self, project_id: str, user: dict[str, object], *, reason: str) -> None:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            row = conn.execute(
                "SELECT is_default FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(project_id)
            if bool(row["is_default"]):
                raise DomainConflictError("Default projects cannot be archived")
            conn.execute(
                "UPDATE projects SET status = 'archived', archived_at = ?, archive_reason = ?, updated_at = ? WHERE project_id = ?",
                (_now(), reason, _now(), project_id),
            )
            self._audit(conn, self._user_id(user), "project.archived", "project", project_id)
            conn.commit()

    def unregister_workspace(self, workspace_id: str, user: dict[str, object]) -> None:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_workspace_owner(workspace_id, user)
            active_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE workspace_id = ? AND status IN ('queued', 'starting', 'running')",
                (workspace_id,),
            ).fetchone()
            if active_tasks is not None and int(active_tasks[0]) > 0:
                raise DomainConflictError(
                    "Cannot unregister a workspace with queued or running tasks"
                )
            conn.execute(
                "UPDATE workspaces SET status = 'unregistered', updated_at = ? WHERE workspace_id = ?",
                (_now(), workspace_id),
            )
            conn.execute(
                "UPDATE project_workspace_links SET status = 'retired', is_primary = 0, updated_at = ? WHERE workspace_id = ?",
                (_now(), workspace_id),
            )
            self._audit(
                conn, self._user_id(user), "workspace.unregistered", "workspace", workspace_id
            )
            conn.commit()

    def project(self, project_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            if DomainAuthorizationService(conn).project_role(project_id, user) is None:
                raise DomainNotFoundError(project_id)
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row is not None else {}

    def workspace(self, workspace_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_workspace_owner(workspace_id, user)
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
        return dict(row) if row is not None else {}

    def environment(self, environment_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
        if row is None or (
            user.get("role") != "admin" and row["owner_user_id"] not in {None, user.get("id")}
        ):
            raise DomainNotFoundError(environment_id)
        result = dict(row)
        result.pop("credential_ref", None)
        return result

    def _link_operation(
        self,
        project_id: str,
        workspace_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
        make_primary: bool,
    ) -> dict[str, object]:
        scope = "workspace.primary" if make_primary else "workspace.attach"
        with closing(self._connect()) as conn:
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            cached = self._idempotent_result(conn, scope, idempotency_key)
            if cached is not None:
                return cached
            if make_primary:
                conn.execute(
                    "UPDATE project_workspace_links SET is_primary = 0, updated_at = ? WHERE project_id = ? AND status = 'active'",
                    (_now(), project_id),
                )
            conn.execute(
                "INSERT INTO project_workspace_links (project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at) VALUES (?, ?, 'active', ?, ?, ?, ?) ON CONFLICT(project_id, workspace_id) DO UPDATE SET status = 'active', is_primary = excluded.is_primary, actor_id = excluded.actor_id, updated_at = excluded.updated_at",
                (project_id, workspace_id, int(make_primary), self._user_id(user), _now(), _now()),
            )
            result: dict[str, object] = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "is_primary": make_primary,
            }
            self._store_idempotency(conn, scope, idempotency_key, result)
            self._audit(
                conn,
                self._user_id(user),
                "workspace.primary_set" if make_primary else "workspace.attached",
                "workspace",
                workspace_id,
            )
            conn.commit()
            return result

    @staticmethod
    def _user_id(user: dict[str, object]) -> str:
        value = user.get("id")
        if not isinstance(value, str) or not value:
            raise DomainPermissionError("Authenticated user ID is required")
        return value

    @staticmethod
    def _audit(
        conn: sqlite3.Connection, actor_id: str, event_type: str, subject_type: str, subject_id: str
    ) -> None:
        conn.execute(
            "INSERT INTO domain_audit_events (event_id, actor_id, event_type, subject_type, subject_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )

    @staticmethod
    def _idempotent_result(
        conn: sqlite3.Connection, scope: str, key: str
    ) -> dict[str, object] | None:
        if not key:
            raise DomainConflictError("idempotency_key is required")
        row = conn.execute(
            "SELECT response_json FROM domain_idempotency_requests WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        return json.loads(row["response_json"]) if row is not None else None

    @staticmethod
    def _store_idempotency(
        conn: sqlite3.Connection, scope: str, key: str, result: dict[str, object]
    ) -> None:
        conn.execute(
            "INSERT INTO domain_idempotency_requests (scope, idempotency_key, request_hash, response_json, created_at) VALUES (?, ?, '', ?, ?)",
            (scope, key, json.dumps(result, sort_keys=True), _now()),
        )

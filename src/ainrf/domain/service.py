"""SQLite repositories and application services for the v2 control plane."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain_control import MaintenanceModeError
from ainrf.domain.write_fence import DomainWriteFence


class DomainNotFoundError(LookupError):
    pass


class DomainPermissionError(PermissionError):
    pass


class DomainConflictError(ValueError):
    pass


class _Unset:
    """A typed sentinel for optional compatibility fields."""


_UNSET = _Unset()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainAuthorizationService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def project_role(self, project_id: str, user: dict[str, object]) -> str | None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        if user.get("role") == "admin":
            return "admin"
        if row["owner_user_id"] == user.get("id"):
            return "owner"
        member = self._conn.execute(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user.get("id")),
        ).fetchone()
        return str(member["role"]) if member is not None else None

    def require_project_editor(self, project_id: str, user: dict[str, object]) -> None:
        role = self.project_role(project_id, user)
        if role is None:
            raise DomainNotFoundError(project_id)
        if role not in {"admin", "owner", "editor"}:
            raise DomainPermissionError("Project editor permission is required")

    def require_project_owner(self, project_id: str, user: dict[str, object]) -> None:
        role = self.project_role(project_id, user)
        if role is None:
            raise DomainNotFoundError(project_id)
        if role not in {"admin", "owner"}:
            raise DomainPermissionError("Project owner permission is required")

    def require_project_viewer(self, project_id: str, user: dict[str, object]) -> str:
        role = self.project_role(project_id, user)
        if role is None:
            # Project membership is also its visibility policy.  Do not
            # disclose the resource merely because the caller guessed an ID.
            raise DomainNotFoundError(project_id)
        return role

    def require_project_publisher(self, project_id: str, user: dict[str, object]) -> None:
        role = self.require_project_viewer(project_id, user)
        if role in {"admin", "owner"}:
            return
        row = self._conn.execute(
            """
            SELECT can_publish FROM project_members
            WHERE project_id = ? AND user_id = ? AND role = 'editor'
            """,
            (project_id, user.get("id")),
        ).fetchone()
        if row is None or not bool(row["can_publish"]):
            raise DomainPermissionError("Project publish permission is required")

    def require_workspace_viewer(self, workspace_id: str, user: dict[str, object]) -> None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise DomainNotFoundError(workspace_id)
        if user.get("role") == "admin" or row["owner_user_id"] == user.get("id"):
            return
        # A Workspace can point into a tenant-private filesystem.  Unlike a
        # Project link, guessing its ID must not disclose it to another user.
        raise DomainNotFoundError(workspace_id)

    def require_workspace_owner(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        resource_visible: bool = False,
    ) -> None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise DomainNotFoundError(workspace_id)
        # Administration does not confer Linux tenant execution rights.
        if row["owner_user_id"] == user.get("id"):
            return
        if user.get("role") == "admin":
            raise DomainPermissionError("Workspace owner permission is required")
        if resource_visible:
            raise DomainPermissionError("Workspace owner permission is required")
        raise DomainNotFoundError(workspace_id)

    def require_task_owner(self, task_id: str, user: dict[str, object]) -> None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise DomainNotFoundError(task_id)
        if user.get("role") == "admin" or row["owner_user_id"] == user.get("id"):
            return
        raise DomainPermissionError("Task owner permission is required")


class DomainService:
    """All v2 writes are transactionally routed through this application service."""

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._write_fence = DomainWriteFence(state_root, artifact_sha=artifact_sha)

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _begin_write(conn: sqlite3.Connection) -> None:
        """Acquire the v2 write fence before mutating the control plane.

        Keeping the barrier beside the SQLite transaction makes direct
        application-service callers fail closed during maintenance too.  The
        cutover controller may add a stronger runtime fence here without
        changing the public ``DomainService`` constructor.
        """

        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if state is None or bool(state["is_active"]):
            raise MaintenanceModeError("domain writes are paused for maintenance")

    def _has_environment_access(
        self, *, environment_id: str, user: dict[str, object], owner_user_id: object
    ) -> bool:
        """Read the durable auth grant without inventing a cross-DB transaction."""

        user_id = self._user_id(user)
        if user.get("role") == "admin" or owner_user_id == user_id:
            return True
        if not self._auth_db_path.is_file():
            return False
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                grant = conn.execute(
                    """
                    SELECT 1 FROM environment_access
                    WHERE environment_id = ? AND user_id = ? AND status = 'active'
                    """,
                    (environment_id, user_id),
                ).fetchone()
        except sqlite3.OperationalError:
            return False
        return grant is not None

    def _require_known_auth_user(self, user_id: str) -> None:
        if not self._auth_db_path.is_file():
            raise DomainConflictError("A durable auth user is required for this operation")
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise DomainNotFoundError(f"auth user {user_id}")

    def v2_ready(self) -> bool:
        return self._write_fence.v2_ready()

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
            self._begin_write(conn)
            conn.execute(
                "INSERT INTO projects (project_id, owner_user_id, name, description, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, owner_id, name, description, int(is_default), now, now),
            )
            self._audit(conn, owner_id, "project.created", "project", project_id)
            conn.commit()
        return self.project(project_id, user)

    def update_project(
        self,
        project_id: str,
        user: dict[str, object],
        *,
        name: str | None = None,
        description: str | None | _Unset = _UNSET,
    ) -> dict[str, object]:
        """Update mutable Project metadata without inventing default fields.

        The old API exposed independent default Workspace and Environment
        columns.  In v2 those values are a read projection of the active
        Primary link, so this method intentionally accepts neither field.
        """

        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            updates: list[str] = ["updated_at = ?"]
            params: list[object] = [_now()]
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if not isinstance(description, _Unset):
                updates.append("description = ?")
                params.append(description)
            params.append(project_id)
            conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?", params)
            self._audit(conn, self._user_id(user), "project.updated", "project", project_id)
            conn.commit()
        return self.project(project_id, user)

    def create_environment(
        self,
        user: dict[str, object],
        *,
        alias: str,
        display_name: str,
        connection: dict[str, object],
        description: str | None = None,
        credential_ref: str | None = None,
    ) -> dict[str, object]:
        if user.get("role") != "admin":
            raise DomainPermissionError("Only admins can register environments")
        environment_id = f"env-{uuid4().hex}"
        now = _now()
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            conn.execute(
                "INSERT INTO environments (environment_id, alias, owner_user_id, display_name, description, connection_json, credential_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    environment_id,
                    alias,
                    self._user_id(user),
                    display_name,
                    description,
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
            self._begin_write(conn)
            if (
                conn.execute(
                    "SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)
                ).fetchone()
                is None
            ):
                raise DomainNotFoundError(environment_id)
            conn.execute(
                """
                UPDATE environments
                SET status = 'disabled', disabled_at = ?, disabled_reason = ?, updated_at = ?
                WHERE environment_id = ?
                """,
                (_now(), "disabled by administrator", _now(), environment_id),
            )
            self._audit(
                conn, self._user_id(user), "environment.disabled", "environment", environment_id
            )
            conn.commit()

    def update_environment(
        self,
        environment_id: str,
        user: dict[str, object],
        *,
        alias: str | None = None,
        display_name: str | None = None,
        description: str | None | _Unset = _UNSET,
        connection: dict[str, object] | None = None,
        credential_ref: str | None | _Unset = _UNSET,
    ) -> dict[str, object]:
        if user.get("role") != "admin":
            raise DomainPermissionError("Only admins can update environments")
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            existing = conn.execute(
                "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
            if existing is None:
                raise DomainNotFoundError(environment_id)
            updates: list[str] = ["updated_at = ?"]
            params: list[object] = [_now()]
            if alias is not None:
                updates.append("alias = ?")
                params.append(alias)
            if display_name is not None:
                updates.append("display_name = ?")
                params.append(display_name)
            if not isinstance(description, _Unset):
                updates.append("description = ?")
                params.append(description)
            if connection is not None:
                updates.append("connection_json = ?")
                params.append(json.dumps(connection, sort_keys=True))
            if not isinstance(credential_ref, _Unset):
                updates.append("credential_ref = ?")
                params.append(credential_ref)
            params.append(environment_id)
            try:
                conn.execute(
                    f"UPDATE environments SET {', '.join(updates)} WHERE environment_id = ?", params
                )
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Environment alias already exists") from exc
            self._audit(
                conn, self._user_id(user), "environment.updated", "environment", environment_id
            )
            conn.commit()
        return self.environment(environment_id, user)

    def create_workspace(
        self,
        user: dict[str, object],
        *,
        environment_id: str,
        canonical_path: str,
        label: str,
        description: str | None = None,
        workspace_prompt: str | None = None,
        legacy_project_id: str | None = None,
    ) -> dict[str, object]:
        owner_id = self._user_id(user)
        path = str(Path(canonical_path).expanduser().resolve())
        workspace_id = f"workspace-{uuid4().hex[:12]}"
        now = _now()
        context_metadata = (
            {"workspace_prompt": workspace_prompt} if workspace_prompt is not None else {}
        )
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            environment = conn.execute(
                "SELECT status, owner_user_id FROM environments WHERE environment_id = ?",
                (environment_id,),
            ).fetchone()
            if environment is None:
                raise DomainNotFoundError(environment_id)
            if environment["status"] != "active":
                raise DomainConflictError("Workspace requires an active environment")
            if not self._has_environment_access(
                environment_id=environment_id,
                user=user,
                owner_user_id=environment["owner_user_id"],
            ):
                raise DomainNotFoundError(environment_id)
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, owner_user_id, environment_id, canonical_path, label,
                    description, context_metadata_json, workspace_context, legacy_project_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    owner_id,
                    environment_id,
                    path,
                    label,
                    description,
                    json.dumps(context_metadata, sort_keys=True),
                    workspace_prompt,
                    legacy_project_id,
                    now,
                    now,
                ),
            )
            self._audit(conn, owner_id, "workspace.created", "workspace", workspace_id)
            conn.commit()
        return self.workspace(workspace_id, user)

    def update_workspace(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        label: str | None = None,
        description: str | None | _Unset = _UNSET,
        canonical_path: str | _Unset = _UNSET,
        workspace_prompt: str | None | _Unset = _UNSET,
    ) -> dict[str, object]:
        """Update Workspace metadata without changing its Environment or links."""

        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_workspace_owner(workspace_id, user)
            existing = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if existing is None:
                raise DomainNotFoundError(workspace_id)
            updates: list[str] = ["updated_at = ?"]
            params: list[object] = [_now()]
            if label is not None:
                updates.append("label = ?")
                params.append(label)
            if not isinstance(description, _Unset):
                updates.append("description = ?")
                params.append(description)
            if not isinstance(canonical_path, _Unset):
                updates.append("canonical_path = ?")
                params.append(str(Path(canonical_path).expanduser().resolve()))
            if not isinstance(workspace_prompt, _Unset):
                try:
                    metadata = json.loads(str(existing["context_metadata_json"]))
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["workspace_prompt"] = workspace_prompt
                updates.extend(("context_metadata_json = ?", "workspace_context = ?"))
                params.extend((json.dumps(metadata, sort_keys=True), workspace_prompt))
            params.append(workspace_id)
            try:
                conn.execute(
                    f"UPDATE workspaces SET {', '.join(updates)} WHERE workspace_id = ?", params
                )
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Workspace canonical path is already registered") from exc
            self._audit(conn, self._user_id(user), "workspace.updated", "workspace", workspace_id)
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

    def replace_primary_workspace(
        self,
        project_id: str,
        previous_workspace_id: str,
        workspace_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Atomically replace a Primary Workspace after checking both endpoints."""

        with closing(self._connect()) as conn:
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "previous_workspace_id": previous_workspace_id,
                "workspace_id": workspace_id,
            }
            cached = self._idempotent_result(
                conn, actor_user_id, "workspace.primary.replace", idempotency_key, request
            )
            if cached is not None:
                return cached
            previous = conn.execute(
                """
                SELECT 1 FROM project_workspace_links
                WHERE project_id = ? AND workspace_id = ? AND status = 'active' AND is_primary = 1
                """,
                (project_id, previous_workspace_id),
            ).fetchone()
            if previous is None:
                raise DomainConflictError("Specified previous Workspace is not the active Primary")
            replacement = self._link_operation_in_transaction(
                conn,
                project_id=project_id,
                workspace_id=workspace_id,
                user=user,
                actor_user_id=actor_user_id,
            )
            self._store_idempotency(
                conn,
                actor_user_id,
                "workspace.primary.replace",
                idempotency_key,
                request,
                replacement,
            )
            self._audit(
                conn, actor_user_id, "workspace.primary.replaced", "workspace", workspace_id
            )
            conn.commit()
            return replacement

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
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "allow_no_primary": allow_no_primary,
            }
            cached = self._idempotent_result(
                conn, actor_user_id, "workspace.detach", idempotency_key, request
            )
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
            self._store_idempotency(
                conn,
                actor_user_id,
                "workspace.detach",
                idempotency_key,
                request,
                {"detached": True},
            )
            self._audit(conn, actor_user_id, "workspace.detached", "workspace", workspace_id)
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
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            conn.execute(
                "INSERT INTO project_members (project_id, user_id, role, can_publish, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role, can_publish = excluded.can_publish, updated_at = excluded.updated_at",
                (project_id, member_user_id, role, int(can_publish), _now(), _now()),
            )
            self._audit(conn, self._user_id(user), "project.member.updated", "project", project_id)
            conn.commit()

    def remove_member(self, project_id: str, member_user_id: str, user: dict[str, object]) -> None:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            owner = conn.execute(
                "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if owner is None:
                raise DomainNotFoundError(project_id)
            if owner["owner_user_id"] == member_user_id:
                raise DomainConflictError("Project owner cannot be removed as a member")
            deleted = conn.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, member_user_id),
            )
            if deleted.rowcount != 1:
                raise DomainNotFoundError("project member")
            self._audit(conn, self._user_id(user), "project.member.removed", "project", project_id)
            conn.commit()

    def list_project_members(
        self, project_id: str, user: dict[str, object]
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            rows = conn.execute(
                """
                SELECT user_id, role, can_publish, created_at, updated_at
                FROM project_members
                WHERE project_id = ?
                ORDER BY created_at, user_id
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_task_relationships(
        self, project_id: str, user: dict[str, object]
    ) -> list[dict[str, object]]:
        """Expose legacy task edges as typed ``related_to`` relationships."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            rows = conn.execute(
                """
                SELECT relationship.relationship_id, relationship.source_task_id,
                       relationship.target_task_id, relationship.created_at
                FROM task_relationships AS relationship
                JOIN tasks AS source ON source.task_id = relationship.source_task_id
                JOIN tasks AS target ON target.task_id = relationship.target_task_id
                WHERE source.project_id = ?
                  AND target.project_id = ?
                  AND relationship.relationship_type = 'related_to'
                ORDER BY relationship.created_at, relationship.relationship_id
                """,
                (project_id, project_id),
            ).fetchall()
        return [
            {
                "edge_id": str(row["relationship_id"]),
                "project_id": project_id,
                "source_task_id": str(row["source_task_id"]),
                "target_task_id": str(row["target_task_id"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def create_task_relationship(
        self,
        project_id: str,
        user: dict[str, object],
        *,
        source_task_id: str,
        target_task_id: str,
    ) -> dict[str, object]:
        """Create the compatibility ``related_to`` edge in SQLite."""

        relationship_type = "related_to"
        relationship_id = self._relationship_id(source_task_id, target_task_id, relationship_type)
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            task_count = conn.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE project_id = ? AND task_id IN (?, ?)
                """,
                (project_id, source_task_id, target_task_id),
            ).fetchone()
            if task_count is None or int(task_count[0]) != 2:
                raise DomainNotFoundError("project task")
            now = _now()
            conn.execute(
                """
                INSERT INTO task_relationships (
                    source_task_id, target_task_id, relationship_type,
                    relationship_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, '{}', ?)
                ON CONFLICT(source_task_id, target_task_id, relationship_type) DO NOTHING
                """,
                (source_task_id, target_task_id, relationship_type, relationship_id, now),
            )
            row = conn.execute(
                """
                SELECT relationship_id, created_at FROM task_relationships
                WHERE source_task_id = ? AND target_task_id = ? AND relationship_type = ?
                """,
                (source_task_id, target_task_id, relationship_type),
            ).fetchone()
            if row is None:
                raise DomainConflictError("Task relationship was not created")
            self._audit(
                conn, self._user_id(user), "task.relationship.created", "task", source_task_id
            )
            conn.commit()
        return {
            "edge_id": str(row["relationship_id"]),
            "project_id": project_id,
            "source_task_id": source_task_id,
            "target_task_id": target_task_id,
            "created_at": str(row["created_at"]),
        }

    def delete_task_relationship(self, relationship_id: str, user: dict[str, object]) -> None:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            row = conn.execute(
                """
                SELECT relationship.source_task_id, source.project_id
                FROM task_relationships AS relationship
                JOIN tasks AS source ON source.task_id = relationship.source_task_id
                WHERE relationship.relationship_id = ?
                  AND relationship.relationship_type = 'related_to'
                """,
                (relationship_id,),
            ).fetchone()
            if row is None:
                raise DomainNotFoundError(relationship_id)
            project_id = str(row["project_id"])
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            conn.execute(
                "DELETE FROM task_relationships WHERE relationship_id = ?", (relationship_id,)
            )
            self._audit(
                conn,
                self._user_id(user),
                "task.relationship.deleted",
                "task",
                str(row["source_task_id"]),
            )
            conn.commit()

    def transfer_project_owner(
        self, project_id: str, new_owner_user_id: str, user: dict[str, object]
    ) -> None:
        if not new_owner_user_id:
            raise DomainConflictError("new_owner_user_id is required")
        self._require_known_auth_user(new_owner_user_id)
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_owner(project_id, user)
            project = conn.execute(
                "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise DomainNotFoundError(project_id)
            old_owner_user_id = str(project["owner_user_id"])
            if old_owner_user_id == new_owner_user_id:
                return
            now = _now()
            conn.execute(
                "UPDATE projects SET owner_user_id = ?, updated_at = ? WHERE project_id = ?",
                (new_owner_user_id, now, project_id),
            )
            conn.execute(
                """
                INSERT INTO project_members (
                    project_id, user_id, role, can_publish, created_at, updated_at
                ) VALUES (?, ?, 'editor', 1, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET
                    role = 'editor', can_publish = 1, updated_at = excluded.updated_at
                """,
                (project_id, old_owner_user_id, now, now),
            )
            conn.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, new_owner_user_id),
            )
            self._audit(
                conn, self._user_id(user), "project.owner.transferred", "project", project_id
            )
            conn.commit()

    def archive_project(
        self,
        project_id: str,
        user: dict[str, object],
        *,
        reason: str,
        idempotency_key: str | None = None,
    ) -> None:
        """Compatibility facade for the transactional Task lifecycle writer.

        Project archival affects queued dispatches and paused Attempts, so it
        must not retain an independent lightweight write path here.  The
        import stays local to avoid the intentional service/tasks dependency
        cycle at module import time.
        """

        from ainrf.domain.tasks import TaskApplicationService

        TaskApplicationService(self._state_root).archive_project(
            project_id,
            user,
            reason=reason,
            idempotency_key=idempotency_key or f"legacy-project-archive-{uuid4().hex}",
        )

    def unarchive_project(
        self,
        project_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> None:
        """Compatibility facade; it never recreates stopped Attempts."""

        from ainrf.domain.tasks import TaskApplicationService

        TaskApplicationService(self._state_root).unarchive_project(
            project_id,
            user,
            idempotency_key=idempotency_key or f"legacy-project-unarchive-{uuid4().hex}",
        )

    def unregister_workspace(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
        allow_no_primary: bool = False,
    ) -> None:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_workspace_owner(workspace_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "workspace_id": workspace_id,
                "allow_no_primary": allow_no_primary,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "workspace.unregister", idempotency_key, request
                )
                if cached is not None:
                    return
            active_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE workspace_id = ? AND status IN ('queued', 'starting', 'running')",
                (workspace_id,),
            ).fetchone()
            if active_tasks is not None and int(active_tasks[0]) > 0:
                raise DomainConflictError(
                    "Cannot unregister a workspace with queued or running tasks"
                )
            primary = conn.execute(
                """
                SELECT 1 FROM project_workspace_links
                WHERE workspace_id = ? AND status = 'active' AND is_primary = 1
                """,
                (workspace_id,),
            ).fetchone()
            if primary is not None and not allow_no_primary:
                raise DomainConflictError("Replace the Primary Workspace before unregistering it")
            conn.execute(
                "UPDATE workspaces SET status = 'unregistered', updated_at = ? WHERE workspace_id = ?",
                (_now(), workspace_id),
            )
            conn.execute(
                "UPDATE project_workspace_links SET status = 'retired', is_primary = 0, updated_at = ? WHERE workspace_id = ?",
                (_now(), workspace_id),
            )
            self._audit(conn, actor_user_id, "workspace.unregistered", "workspace", workspace_id)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "workspace.unregister",
                    idempotency_key,
                    request,
                    {"unregistered": True},
                )
            conn.commit()

    def project(self, project_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row is not None else {}

    def require_project_editor(self, project_id: str, user: dict[str, object]) -> None:
        """Expose the v2 Project capability check to compatibility adapters."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, user)

    def list_projects(
        self, user: dict[str, object], *, include_archived: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            if user.get("role") == "admin":
                rows = conn.execute(
                    "SELECT * FROM projects WHERE ? OR status = 'active' ORDER BY updated_at DESC, project_id",
                    (int(include_archived),),
                ).fetchall()
            else:
                user_id = self._user_id(user)
                rows = conn.execute(
                    """
                    SELECT DISTINCT project.* FROM projects AS project
                    LEFT JOIN project_members AS member ON member.project_id = project.project_id
                    WHERE (project.owner_user_id = ? OR member.user_id = ?)
                      AND (? OR project.status = 'active')
                    ORDER BY project.updated_at DESC, project.project_id
                    """,
                    (user_id, user_id, int(include_archived)),
                ).fetchall()
        return [dict(row) for row in rows]

    def workspace(self, workspace_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_workspace_viewer(workspace_id, user)
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
        return dict(row) if row is not None else {}

    def list_workspaces(
        self, user: dict[str, object], *, include_unregistered: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            user_id = self._user_id(user)
            if user.get("role") == "admin":
                rows = conn.execute(
                    "SELECT * FROM workspaces WHERE ? OR status = 'active' ORDER BY updated_at DESC, workspace_id",
                    (int(include_unregistered),),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM workspaces
                    WHERE owner_user_id = ? AND (? OR status = 'active')
                    ORDER BY updated_at DESC, workspace_id
                    """,
                    (user_id, int(include_unregistered)),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_environments(
        self, user: dict[str, object], *, include_disabled: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM environments WHERE ? OR status = 'active' ORDER BY alias, environment_id",
                (int(include_disabled),),
            ).fetchall()
        visible: list[dict[str, object]] = []
        for row in rows:
            if self._has_environment_access(
                environment_id=str(row["environment_id"]),
                user=user,
                owner_user_id=row["owner_user_id"],
            ):
                item = dict(row)
                item.pop("credential_ref", None)
                visible.append(item)
        return visible

    def workspace_links(self, project_id: str, user: dict[str, object]) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            rows = conn.execute(
                """
                SELECT link.project_id, link.workspace_id, link.status, link.is_primary,
                       workspace.environment_id, workspace.owner_user_id, workspace.status AS workspace_status,
                       environment.status AS environment_status,
                       environment.owner_user_id AS environment_owner_user_id
                FROM project_workspace_links AS link
                JOIN workspaces AS workspace ON workspace.workspace_id = link.workspace_id
                JOIN environments AS environment ON environment.environment_id = workspace.environment_id
                WHERE link.project_id = ?
                ORDER BY link.is_primary DESC, link.created_at, link.workspace_id
                """,
                (project_id,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            reason: str | None = None
            can_execute = bool(row["status"] == "active" and row["workspace_status"] == "active")
            if not can_execute:
                reason = (
                    "workspace link is inactive"
                    if row["status"] != "active"
                    else "workspace is unregistered"
                )
            elif row["environment_status"] != "active":
                can_execute = False
                reason = "derived Environment is disabled"
            elif not self._has_environment_access(
                environment_id=str(row["environment_id"]),
                user=user,
                owner_user_id=row["environment_owner_user_id"],
            ):
                can_execute = False
                reason = "active Environment grant is required"
            result.append(
                {
                    "project_id": str(row["project_id"]),
                    "workspace_id": str(row["workspace_id"]),
                    "status": str(row["status"]),
                    "is_primary": bool(row["is_primary"]),
                    "environment_id": str(row["environment_id"]),
                    "can_execute": can_execute,
                    "cannot_execute_reason": reason,
                }
            )
        return result

    def environment(
        self,
        environment_id: str,
        user: dict[str, object],
        *,
        include_disabled: bool = True,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
        if row is None:
            raise DomainNotFoundError(environment_id)
        if not self._has_environment_access(
            environment_id=environment_id,
            user=user,
            owner_user_id=row["owner_user_id"],
        ):
            raise DomainNotFoundError(environment_id)
        if not include_disabled and row["status"] != "active":
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
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            auth.require_workspace_owner(workspace_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "make_primary": make_primary,
            }
            cached = self._idempotent_result(conn, actor_user_id, scope, idempotency_key, request)
            if cached is not None:
                return cached
            project = conn.execute(
                "SELECT status FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            workspace = conn.execute(
                """
                SELECT workspace.environment_id, workspace.status AS workspace_status,
                       environment.status AS environment_status, environment.owner_user_id
                FROM workspaces AS workspace
                JOIN environments AS environment ON environment.environment_id = workspace.environment_id
                WHERE workspace.workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()
            if project is None or str(project["status"]) != "active":
                raise DomainConflictError("Workspace links require an active Project")
            if workspace is None or str(workspace["workspace_status"]) != "active":
                raise DomainConflictError("Workspace links require an active Workspace")
            if str(workspace["environment_status"]) != "active":
                raise DomainConflictError("Workspace links require an active Environment")
            if not self._has_environment_access(
                environment_id=str(workspace["environment_id"]),
                user=user,
                owner_user_id=workspace["owner_user_id"],
            ):
                raise DomainPermissionError("Active Environment access is required")
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
                "environment_id": str(workspace["environment_id"]),
                "can_execute": True,
                "cannot_execute_reason": None,
            }
            self._store_idempotency(conn, actor_user_id, scope, idempotency_key, request, result)
            self._audit(
                conn,
                actor_user_id,
                "workspace.primary_set" if make_primary else "workspace.attached",
                "workspace",
                workspace_id,
            )
            conn.commit()
            return result

    def _link_operation_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        user: dict[str, object],
        actor_user_id: str,
    ) -> dict[str, object]:
        project = conn.execute(
            "SELECT status FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        workspace = conn.execute(
            """
            SELECT workspace.environment_id, workspace.status AS workspace_status,
                   environment.status AS environment_status, environment.owner_user_id
            FROM workspaces AS workspace
            JOIN environments AS environment ON environment.environment_id = workspace.environment_id
            WHERE workspace.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if project is None or str(project["status"]) != "active":
            raise DomainConflictError("Workspace links require an active Project")
        if workspace is None or str(workspace["workspace_status"]) != "active":
            raise DomainConflictError("Workspace links require an active Workspace")
        if str(workspace["environment_status"]) != "active":
            raise DomainConflictError("Workspace links require an active Environment")
        if not self._has_environment_access(
            environment_id=str(workspace["environment_id"]),
            user=user,
            owner_user_id=workspace["owner_user_id"],
        ):
            raise DomainPermissionError("Active Environment access is required")
        now = _now()
        conn.execute(
            """
            UPDATE project_workspace_links SET is_primary = 0, updated_at = ?
            WHERE project_id = ? AND status = 'active'
            """,
            (now, project_id),
        )
        conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES (?, ?, 'active', 1, ?, ?, ?)
            ON CONFLICT(project_id, workspace_id) DO UPDATE SET
                status = 'active', is_primary = 1, actor_id = excluded.actor_id,
                updated_at = excluded.updated_at
            """,
            (project_id, workspace_id, actor_user_id, now, now),
        )
        return {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "is_primary": True,
            "environment_id": str(workspace["environment_id"]),
            "can_execute": True,
            "cannot_execute_reason": None,
        }

    @staticmethod
    def _user_id(user: dict[str, object]) -> str:
        value = user.get("id")
        if not isinstance(value, str) or not value:
            raise DomainPermissionError("Authenticated user ID is required")
        return value

    def _audit(
        self,
        conn: sqlite3.Connection,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
    ) -> None:
        self._write_fence.record_first_v2_write(conn, actor_id=actor_id)
        conn.execute(
            "INSERT INTO domain_audit_events (event_id, actor_id, event_type, subject_type, subject_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )

    @staticmethod
    def _request_hash(request: dict[str, object]) -> str:
        payload = json.dumps(
            request, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _relationship_id(source_task_id: str, target_task_id: str, relationship_type: str) -> str:
        return (
            f"{len(source_task_id)}:{source_task_id}{len(target_task_id)}:{target_task_id}"
            f"{len(relationship_type)}:{relationship_type}"
        )

    @classmethod
    def _idempotent_result(
        cls,
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        key: str,
        request: dict[str, object],
    ) -> dict[str, object] | None:
        if not key:
            raise DomainConflictError("idempotency_key is required")
        row = conn.execute(
            """
            SELECT request_hash, response_json FROM domain_idempotency_requests
            WHERE actor_user_id = ? AND scope = ? AND idempotency_key = ?
            """,
            (actor_user_id, scope, key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != cls._request_hash(request):
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        value = json.loads(row["response_json"])
        if not isinstance(value, dict):
            raise DomainConflictError("Stored idempotency response is invalid")
        return {str(item_key): item for item_key, item in value.items()}

    @classmethod
    def _store_idempotency(
        cls,
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        key: str,
        request: dict[str, object],
        result: dict[str, object],
    ) -> None:
        conn.execute(
            """
            INSERT INTO domain_idempotency_requests (
                actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor_user_id,
                scope,
                key,
                cls._request_hash(request),
                json.dumps(result, ensure_ascii=True, sort_keys=True),
                _now(),
            ),
        )

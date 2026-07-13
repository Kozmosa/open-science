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
from ainrf.domain.environment_identity import (
    canonical_connection_json,
    canonical_connection_object,
    environment_connection_fingerprint,
)
from ainrf.domain.repositories import SqliteDomainRepository
from ainrf.domain_telemetry import record_durable_idempotency_event, record_permission_denied
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
        self._repository = SqliteDomainRepository(conn)

    def project_role(self, project_id: str, user: dict[str, object]) -> str | None:
        owner_user_id = self._repository.project_owner(project_id)
        if owner_user_id is None:
            return None
        if user.get("role") == "admin":
            return "admin"
        if owner_user_id == user.get("id"):
            return "owner"
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            return None
        member = self._repository.project_member(project_id, user_id)
        return str(member["role"]) if member is not None else None

    @staticmethod
    def _record_denial(
        *,
        resource: str,
        reason: str,
        user: dict[str, object],
        project_id: str | None = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        user_id = user.get("id")
        record_permission_denied(
            resource=resource,
            reason=reason,
            user_id=user_id if isinstance(user_id, str) else None,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
        )

    def require_project_editor(self, project_id: str, user: dict[str, object]) -> None:
        role = self.project_role(project_id, user)
        if role is None:
            self._record_denial(
                resource="project", reason="not_visible", user=user, project_id=project_id
            )
            raise DomainNotFoundError(project_id)
        if role not in {"admin", "owner", "editor"}:
            self._record_denial(
                resource="project", reason="editor_required", user=user, project_id=project_id
            )
            raise DomainPermissionError("Project editor permission is required")

    def require_project_owner(self, project_id: str, user: dict[str, object]) -> None:
        role = self.project_role(project_id, user)
        if role is None:
            self._record_denial(
                resource="project", reason="not_visible", user=user, project_id=project_id
            )
            raise DomainNotFoundError(project_id)
        if role not in {"admin", "owner"}:
            self._record_denial(
                resource="project", reason="owner_required", user=user, project_id=project_id
            )
            raise DomainPermissionError("Project owner permission is required")

    def require_project_viewer(self, project_id: str, user: dict[str, object]) -> str:
        role = self.project_role(project_id, user)
        if role is None:
            # Project membership is also its visibility policy.  Do not
            # disclose the resource merely because the caller guessed an ID.
            self._record_denial(
                resource="project", reason="not_visible", user=user, project_id=project_id
            )
            raise DomainNotFoundError(project_id)
        return role

    def require_project_publisher(self, project_id: str, user: dict[str, object]) -> None:
        role = self.require_project_viewer(project_id, user)
        if role in {"admin", "owner"}:
            return
        user_id = user.get("id")
        member = (
            self._repository.project_member(project_id, user_id)
            if isinstance(user_id, str)
            else None
        )
        if member is None or str(member["role"]) != "editor" or not bool(member["can_publish"]):
            self._record_denial(
                resource="project", reason="publish_required", user=user, project_id=project_id
            )
            raise DomainPermissionError("Project publish permission is required")

    def require_workspace_viewer(self, workspace_id: str, user: dict[str, object]) -> None:
        owner_user_id = self._repository.workspace_owner(workspace_id)
        if owner_user_id is None:
            self._record_denial(
                resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
            )
            raise DomainNotFoundError(workspace_id)
        if user.get("role") == "admin" or owner_user_id == user.get("id"):
            return
        # A Workspace can point into a tenant-private filesystem.  Unlike a
        # Project link, guessing its ID must not disclose it to another user.
        self._record_denial(
            resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
        )
        raise DomainNotFoundError(workspace_id)

    def require_workspace_owner(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        resource_visible: bool = False,
    ) -> None:
        owner_user_id = self._repository.workspace_owner(workspace_id)
        if owner_user_id is None:
            self._record_denial(
                resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
            )
            raise DomainNotFoundError(workspace_id)
        # Administration does not confer Linux tenant execution rights.
        if owner_user_id == user.get("id"):
            return
        if user.get("role") == "admin":
            self._record_denial(
                resource="workspace",
                reason="tenant_owner_required",
                user=user,
                workspace_id=workspace_id,
            )
            raise DomainPermissionError("Workspace owner permission is required")
        if resource_visible:
            self._record_denial(
                resource="workspace", reason="owner_required", user=user, workspace_id=workspace_id
            )
            raise DomainPermissionError("Workspace owner permission is required")
        self._record_denial(
            resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
        )
        raise DomainNotFoundError(workspace_id)

    def require_workspace_registry_manager(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        resource_visible: bool = False,
    ) -> None:
        """Authorize durable registry metadata changes without granting execution.

        Administrators may repair or manage product control-plane records, but
        this capability is deliberately separate from ``require_workspace_owner``.
        Task, runtime, terminal, and tenant-file call sites continue to require
        the latter so an admin role never becomes Linux tenant authority.
        """

        owner_user_id = self._repository.workspace_owner(workspace_id)
        if owner_user_id is None:
            self._record_denial(
                resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
            )
            raise DomainNotFoundError(workspace_id)
        if owner_user_id == user.get("id") or user.get("role") == "admin":
            return
        if resource_visible:
            self._record_denial(
                resource="workspace",
                reason="registry_manager_required",
                user=user,
                workspace_id=workspace_id,
            )
            raise DomainPermissionError("Workspace owner permission is required")
        self._record_denial(
            resource="workspace", reason="not_visible", user=user, workspace_id=workspace_id
        )
        raise DomainNotFoundError(workspace_id)

    def require_task_viewer(self, task_id: str, user: dict[str, object]) -> None:
        """Authorize an inspect-only Task read without leaking private Tasks.

        A Project collaborator can inspect the shared Task/Attempt projection,
        but a guessed Task outside every visible Project remains indistinguish-
        able from an absent record.  Mutation callers use
        :meth:`require_task_owner` below and receive 403 only after this
        visibility check has established that the Task is visible to them.
        """

        row = self._repository.task_owner_and_project(task_id)
        if row is None:
            self._record_denial(resource="task", reason="not_visible", user=user, task_id=task_id)
            raise DomainNotFoundError(task_id)
        if user.get("role") == "admin" or row["owner_user_id"] == user.get("id"):
            return
        project_id = row["project_id"]
        if not isinstance(project_id, str) or self.project_role(project_id, user) is None:
            self._record_denial(resource="task", reason="not_visible", user=user, task_id=task_id)
            raise DomainNotFoundError(task_id)

    def require_task_owner(self, task_id: str, user: dict[str, object]) -> None:
        """Authorize a Task mutation with stable 404/403 semantics."""

        row = self._repository.task_owner_and_project(task_id)
        if row is None:
            self._record_denial(resource="task", reason="not_visible", user=user, task_id=task_id)
            raise DomainNotFoundError(task_id)
        if user.get("role") == "admin" or row["owner_user_id"] == user.get("id"):
            return
        project_id = row["project_id"]
        if not isinstance(project_id, str) or self.project_role(project_id, user) is None:
            self._record_denial(resource="task", reason="not_visible", user=user, task_id=task_id)
            raise DomainNotFoundError(task_id)
        self._record_denial(resource="task", reason="owner_required", user=user, task_id=task_id)
        raise DomainPermissionError("Task owner permission is required")


class DomainService:
    """All v2 writes are transactionally routed through this application service."""

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._state_root = state_root
        self._artifact_sha = artifact_sha
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
        """Return registry visibility (which administrators may manage)."""

        user_id = self._user_id(user)
        if user.get("role") == "admin" or owner_user_id == user_id:
            return True
        return self._has_active_environment_grant(environment_id=environment_id, user_id=user_id)

    def _has_environment_execution_access(
        self, *, environment_id: str, user: dict[str, object]
    ) -> bool:
        """Return only an explicit active grant for a tenant execution action.

        Registry administration and Environment ownership are deliberately not
        Linux tenant execution authority.  A caller that wants to register or
        inspect an Environment may be an admin; a caller that creates, links,
        or runs a Workspace must hold its own active durable grant.
        """

        return self._has_active_environment_grant(
            environment_id=environment_id,
            user_id=self._user_id(user),
        )

    def _has_active_environment_grant(self, *, environment_id: str, user_id: str) -> bool:
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

    def _require_known_auth_user(
        self, user_id: str, *, allow_api_key_principal: bool = False
    ) -> None:
        if allow_api_key_principal and user_id == "api-key-user":
            # API keys authenticate a deliberately restricted, stable
            # compatibility principal. It still gains no visibility unless a
            # Project owner explicitly grants this exact membership.
            return
        if not self._auth_db_path.is_file():
            raise DomainConflictError("A durable auth user is required for this operation")
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise DomainConflictError("Target user is not a durable auth user")

    @staticmethod
    def _environment_is_referenced(conn: sqlite3.Connection, environment_id: str) -> bool:
        """Return whether a durable execution reference has fixed this Environment ID."""

        return SqliteDomainRepository(conn).environment_is_referenced(environment_id)

    @staticmethod
    def _repository(conn: sqlite3.Connection) -> SqliteDomainRepository:
        """Create the persistence boundary for one caller-owned transaction."""

        return SqliteDomainRepository(conn)

    @staticmethod
    def _connection_from_stored_json(value: object) -> dict[str, object]:
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): item for key, item in parsed.items()}

    def v2_ready(self) -> bool:
        return self._write_fence.v2_ready()

    def create_project(
        self,
        user: dict[str, object],
        *,
        name: str,
        description: str | None = None,
        is_default: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        owner_id = self._user_id(user)
        request: dict[str, object] = {
            "name": name,
            "description": description,
            "is_default": is_default,
        }
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            repository = self._repository(conn)
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, owner_id, "project.create", idempotency_key, request
                )
                if cached is not None:
                    return cached
            project_id = f"project-{uuid4().hex[:12]}"
            now = _now()
            repository.insert_project(
                project_id=project_id,
                owner_user_id=owner_id,
                name=name,
                description=description,
                status="active",
                is_default=is_default,
                created_at=now,
                updated_at=now,
            )
            # Context is part of the Project's authoritative lifecycle: a
            # fresh Project always has the empty Draft and immutable initial
            # Active Version that Task creation is allowed to pin.
            from ainrf.domain.context import ProjectContextService

            ProjectContextService.initialize_project_context_in_transaction(
                conn,
                project_id=project_id,
                owner_user_id=owner_id,
                created_at=now,
            )
            created = repository.project(project_id)
            if created is None:  # pragma: no cover - INSERT invariant
                raise DomainConflictError("Project creation did not persist")
            result = dict(created)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    owner_id,
                    "project.create",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, owner_id, "project.created", "project", project_id)
            conn.commit()
        return result

    def provision_default_project(self, *, user_id: str, username: str) -> dict[str, object]:
        """Idempotently create or recover one user's authoritative default Project.

        Registration commits in ``auth.sqlite3`` before this method opens the
        separate domain database.  The caller may therefore replay this method
        after a crash at any point; the active-default unique index and this
        ``BEGIN IMMEDIATE`` transaction make every replay return the same
        Project rather than creating a second one.
        """

        if not user_id or not username:
            raise DomainConflictError(
                "user_id and username are required for default Project provisioning"
            )
        self._require_known_auth_user(user_id)
        now = _now()
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            repository = self._repository(conn)
            rows = repository.default_projects_for_owner(user_id)
            active = next((row for row in rows if str(row["status"]) == "active"), None)
            if active is not None:
                conn.commit()
                return dict(active)
            if rows:
                raise DomainConflictError(
                    "Archived default Project requires explicit reconciliation"
                )

            project_id = (
                f"project-default-{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:24]}"
            )
            try:
                repository.insert_project(
                    project_id=project_id,
                    owner_user_id=user_id,
                    name=f"{username}'s Project",
                    description=None,
                    status="active",
                    is_default=True,
                    created_at=now,
                    updated_at=now,
                )
            except sqlite3.IntegrityError as exc:
                # A database upgraded from a legacy registry can already have
                # an active default with a different retained ID.  Return that
                # durable winner rather than attempting a non-authoritative
                # cross-database repair.
                active = next(
                    (
                        row
                        for row in repository.default_projects_for_owner(user_id)
                        if str(row["status"]) == "active"
                    ),
                    None,
                )
                if active is None:
                    raise DomainConflictError("Default Project provisioning conflicted") from exc
                conn.commit()
                return dict(active)
            from ainrf.domain.context import ProjectContextService

            ProjectContextService.initialize_project_context_in_transaction(
                conn,
                project_id=project_id,
                owner_user_id=user_id,
                created_at=now,
            )
            self._audit(conn, user_id, "project.default_provisioned", "project", project_id)
            created = repository.project(project_id)
            conn.commit()
        if created is None:  # pragma: no cover - INSERT/SELECT invariant
            raise DomainConflictError("Default Project provisioning did not persist")
        return dict(created)

    def update_project(
        self,
        project_id: str,
        user: dict[str, object],
        *,
        name: str | None = None,
        description: str | None | _Unset = _UNSET,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Update mutable Project metadata without inventing default fields.

        The old API exposed independent default Workspace and Environment
        columns.  In v2 those values are a read projection of the active
        Primary link, so this method intentionally accepts neither field.
        """

        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {"project_id": project_id, "name": name}
            if not isinstance(description, _Unset):
                request["description"] = description
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "project.update", idempotency_key, request
                )
                if cached is not None:
                    return cached
            updates: dict[str, object] = {"updated_at": _now()}
            if name is not None:
                updates["name"] = name
            if not isinstance(description, _Unset):
                updates["description"] = description
            repository = self._repository(conn)
            if repository.update_project(project_id, updates) != 1:
                raise DomainNotFoundError(project_id)
            updated = repository.project(project_id)
            if updated is None:  # pragma: no cover - UPDATE invariant
                raise DomainNotFoundError(project_id)
            result = dict(updated)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.update",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project.updated", "project", project_id)
            conn.commit()
        return result

    def create_environment(
        self,
        user: dict[str, object],
        *,
        alias: str,
        display_name: str,
        connection: dict[str, object],
        description: str | None = None,
        credential_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if user.get("role") != "admin":
            raise DomainPermissionError("Only admins can register environments")
        actor_user_id = self._user_id(user)
        canonical_connection = canonical_connection_object(connection)
        connection_json = canonical_connection_json(canonical_connection)
        connection_fingerprint = environment_connection_fingerprint(canonical_connection)
        request: dict[str, object] = {
            "alias": alias,
            "display_name": display_name,
            "description": description,
            "connection": canonical_connection,
            "credential_ref": credential_ref,
        }
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "environment.create", idempotency_key, request
                )
                if cached is not None:
                    return cached
            environment_id = f"env-{uuid4().hex}"
            now = _now()
            repository = self._repository(conn)
            repository.insert_environment(
                environment_id=environment_id,
                alias=alias,
                owner_user_id=actor_user_id,
                display_name=display_name,
                description=description,
                connection_json=connection_json,
                connection_fingerprint=connection_fingerprint,
                credential_ref=credential_ref,
                created_at=now,
                updated_at=now,
            )
            created = repository.environment(environment_id)
            if created is None:  # pragma: no cover - INSERT invariant
                raise DomainConflictError("Environment creation did not persist")
            result = dict(created)
            result.pop("credential_ref", None)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "environment.create",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "environment.created", "environment", environment_id)
            conn.commit()
        return result

    def disable_environment(
        self,
        environment_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            actor_user_id = self._user_id(user)
            repository = self._repository(conn)
            environment = repository.environment(environment_id)
            if environment is None:
                raise DomainNotFoundError(environment_id)
            if not self._has_environment_access(
                environment_id=environment_id,
                user=user,
                owner_user_id=environment["owner_user_id"],
            ):
                raise DomainNotFoundError(environment_id)
            if user.get("role") != "admin":
                raise DomainPermissionError("Only admins can disable environments")
            request: dict[str, object] = {"environment_id": environment_id}
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "environment.disable", idempotency_key, request
                )
                if cached is not None:
                    return
            now = _now()
            repository.update_environment(
                environment_id,
                {
                    "status": "disabled",
                    "disabled_at": now,
                    "disabled_reason": "disabled by administrator",
                    "updated_at": now,
                },
            )
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "environment.disable",
                    idempotency_key,
                    request,
                    {"environment_id": environment_id, "disabled": True},
                )
            self._audit(conn, actor_user_id, "environment.disabled", "environment", environment_id)
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
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            actor_user_id = self._user_id(user)
            repository = self._repository(conn)
            existing = repository.environment(environment_id)
            if existing is None:
                raise DomainNotFoundError(environment_id)
            if not self._has_environment_access(
                environment_id=environment_id,
                user=user,
                owner_user_id=existing["owner_user_id"],
            ):
                raise DomainNotFoundError(environment_id)
            if user.get("role") != "admin":
                raise DomainPermissionError("Only admins can update environments")
            request: dict[str, object] = {"environment_id": environment_id}
            if alias is not None:
                request["alias"] = alias
            if display_name is not None:
                request["display_name"] = display_name
            if not isinstance(description, _Unset):
                request["description"] = description
            if connection is not None:
                request["connection"] = canonical_connection_object(connection)
            if not isinstance(credential_ref, _Unset):
                request["credential_ref"] = credential_ref
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "environment.update", idempotency_key, request
                )
                if cached is not None:
                    return cached
            updates: dict[str, object] = {"updated_at": _now()}
            if alias is not None:
                updates["alias"] = alias
            if display_name is not None:
                updates["display_name"] = display_name
            if not isinstance(description, _Unset):
                updates["description"] = description
            if connection is not None:
                current_connection = self._connection_from_stored_json(existing["connection_json"])
                proposed_connection = canonical_connection_object(connection)
                current_fingerprint = (
                    str(existing["connection_fingerprint"])
                    if existing["connection_fingerprint"] is not None
                    else environment_connection_fingerprint(current_connection)
                )
                proposed_fingerprint = environment_connection_fingerprint(proposed_connection)
                if current_fingerprint != proposed_fingerprint and self._environment_is_referenced(
                    conn, environment_id
                ):
                    raise DomainConflictError(
                        "A referenced Environment cannot be repointed to a different endpoint"
                    )
                updates["connection_json"] = canonical_connection_json(proposed_connection)
                updates["connection_fingerprint"] = proposed_fingerprint
            elif existing["connection_fingerprint"] is None:
                updates["connection_fingerprint"] = environment_connection_fingerprint(
                    self._connection_from_stored_json(existing["connection_json"])
                )
            if not isinstance(credential_ref, _Unset):
                updates["credential_ref"] = credential_ref
            try:
                if repository.update_environment(environment_id, updates) != 1:
                    raise DomainNotFoundError(environment_id)
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Environment alias already exists") from exc
            updated = repository.environment(environment_id)
            if updated is None:  # pragma: no cover - UPDATE invariant
                raise DomainNotFoundError(environment_id)
            result = dict(updated)
            result.pop("credential_ref", None)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "environment.update",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "environment.updated", "environment", environment_id)
            conn.commit()
        return result

    def create_workspace(
        self,
        user: dict[str, object],
        *,
        environment_id: str,
        canonical_path: str,
        label: str,
        description: str | None = None,
        workspace_prompt: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        owner_id = self._user_id(user)
        path = str(Path(canonical_path).expanduser().resolve())
        context_metadata = (
            {"workspace_prompt": workspace_prompt} if workspace_prompt is not None else {}
        )
        request: dict[str, object] = {
            "environment_id": environment_id,
            "canonical_path": path,
            "label": label,
            "description": description,
            "workspace_prompt": workspace_prompt,
        }
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            repository = self._repository(conn)
            environment = repository.environment(environment_id)
            if environment is None:
                raise DomainNotFoundError(environment_id)
            if environment["status"] != "active":
                raise DomainConflictError("Workspace requires an active environment")
            if user.get("role") != "admin" and not self._has_environment_execution_access(
                environment_id=environment_id, user=user
            ):
                raise DomainNotFoundError(environment_id)
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, owner_id, "workspace.create", idempotency_key, request
                )
                if cached is not None:
                    return cached
            workspace_id = f"workspace-{uuid4().hex[:12]}"
            now = _now()
            try:
                repository.insert_workspace(
                    workspace_id=workspace_id,
                    owner_user_id=owner_id,
                    environment_id=environment_id,
                    canonical_path=path,
                    label=label,
                    description=description,
                    context_metadata_json=json.dumps(context_metadata, sort_keys=True),
                    workspace_context=workspace_prompt,
                    # This compatibility field belongs to the importer only.
                    # A normal v2 write must never create a second project
                    # authority beside project_workspace_links.
                    legacy_project_id=None,
                    created_at=now,
                    updated_at=now,
                )
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Workspace canonical path is already registered") from exc
            created = repository.workspace(workspace_id)
            if created is None:  # pragma: no cover - INSERT invariant
                raise DomainConflictError("Workspace creation did not persist")
            result = dict(created)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    owner_id,
                    "workspace.create",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, owner_id, "workspace.created", "workspace", workspace_id)
            conn.commit()
        return result

    def create_workspace_and_attach(
        self,
        *,
        project_id: str,
        user: dict[str, object],
        environment_id: str,
        canonical_path: str,
        label: str,
        description: str | None = None,
        workspace_prompt: str | None = None,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Create one Workspace and its authoritative Project link atomically.

        The former compatibility adapter created a registry row first and then
        attached it in a second transaction.  A permission or link failure left
        an orphan record behind.  This operation is intentionally the only
        create-and-link entry point exposed to that adapter.
        """

        owner_id = self._user_id(user)
        path = str(Path(canonical_path).expanduser().resolve())
        context_metadata = (
            {"workspace_prompt": workspace_prompt} if workspace_prompt is not None else {}
        )
        request: dict[str, object] = {
            "project_id": project_id,
            "environment_id": environment_id,
            "canonical_path": path,
            "label": label,
            "description": description,
            "workspace_prompt": workspace_prompt,
        }
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, user)
            repository = self._repository(conn)
            project = repository.project(project_id)
            if project is None or str(project["status"]) != "active":
                raise DomainConflictError("Workspace links require an active Project")
            environment = repository.environment(environment_id)
            if environment is None:
                raise DomainNotFoundError(environment_id)
            if str(environment["status"]) != "active":
                raise DomainConflictError("Workspace requires an active environment")
            if user.get("role") != "admin" and not self._has_environment_execution_access(
                environment_id=environment_id, user=user
            ):
                raise DomainNotFoundError(environment_id)
            cached = self._idempotent_result(
                conn, owner_id, "workspace.create_and_attach", idempotency_key, request
            )
            if cached is not None:
                return cached
            now = _now()
            workspace_id = f"workspace-{uuid4().hex[:12]}"
            try:
                repository.insert_workspace(
                    workspace_id=workspace_id,
                    owner_user_id=owner_id,
                    environment_id=environment_id,
                    canonical_path=path,
                    label=label,
                    description=description,
                    context_metadata_json=json.dumps(context_metadata, sort_keys=True),
                    workspace_context=workspace_prompt,
                    legacy_project_id=None,
                    created_at=now,
                    updated_at=now,
                )
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Workspace canonical path is already registered") from exc
            repository.upsert_project_workspace_link(
                project_id=project_id,
                workspace_id=workspace_id,
                is_primary=False,
                actor_id=owner_id,
                now=now,
            )
            created = repository.workspace(workspace_id)
            if created is None:  # pragma: no cover - INSERT invariant
                raise DomainConflictError("Workspace creation did not persist")
            result = dict(created)
            self._store_idempotency(
                conn,
                owner_id,
                "workspace.create_and_attach",
                idempotency_key,
                request,
                result,
            )
            self._audit(conn, owner_id, "workspace.created", "workspace", workspace_id)
            self._audit(
                conn,
                owner_id,
                "workspace.attached",
                "workspace",
                workspace_id,
                metadata={
                    "project_id": project_id,
                    "idempotency_key": idempotency_key,
                    "old_link": None,
                    "new_link": {
                        "status": "active",
                        "is_primary": False,
                        "workspace_id": workspace_id,
                    },
                },
            )
            conn.commit()
            return result

    def update_workspace(
        self,
        workspace_id: str,
        user: dict[str, object],
        *,
        label: str | None = None,
        description: str | None | _Unset = _UNSET,
        canonical_path: str | _Unset = _UNSET,
        workspace_prompt: str | None | _Unset = _UNSET,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Update Workspace metadata without changing its Environment or links."""

        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_workspace_registry_manager(workspace_id, user)
            actor_user_id = self._user_id(user)
            repository = self._repository(conn)
            existing = repository.workspace(workspace_id)
            if existing is None:
                raise DomainNotFoundError(workspace_id)
            normalized_path = (
                str(Path(canonical_path).expanduser().resolve())
                if not isinstance(canonical_path, _Unset)
                else None
            )
            request: dict[str, object] = {"workspace_id": workspace_id}
            if label is not None:
                request["label"] = label
            if not isinstance(description, _Unset):
                request["description"] = description
            if normalized_path is not None:
                request["canonical_path"] = normalized_path
            if not isinstance(workspace_prompt, _Unset):
                request["workspace_prompt"] = workspace_prompt
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "workspace.update", idempotency_key, request
                )
                if cached is not None:
                    return cached
            updates: dict[str, object] = {"updated_at": _now()}
            if label is not None:
                updates["label"] = label
            if not isinstance(description, _Unset):
                updates["description"] = description
            if normalized_path is not None:
                updates["canonical_path"] = normalized_path
            if not isinstance(workspace_prompt, _Unset):
                try:
                    metadata = json.loads(str(existing["context_metadata_json"]))
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["workspace_prompt"] = workspace_prompt
                updates["context_metadata_json"] = json.dumps(metadata, sort_keys=True)
                updates["workspace_context"] = workspace_prompt
            try:
                if repository.update_workspace(workspace_id, updates) != 1:
                    raise DomainNotFoundError(workspace_id)
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError("Workspace canonical path is already registered") from exc
            updated = repository.workspace(workspace_id)
            if updated is None:  # pragma: no cover - UPDATE invariant
                raise DomainNotFoundError(workspace_id)
            result = dict(updated)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "workspace.update",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "workspace.updated", "workspace", workspace_id)
            conn.commit()
        return result

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
            auth.require_workspace_registry_manager(workspace_id, user)
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
            repository = self._repository(conn)
            previous = repository.project_workspace_link(project_id, previous_workspace_id)
            if (
                previous is None
                or str(previous["status"]) != "active"
                or not bool(previous["is_primary"])
            ):
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
                conn,
                actor_user_id,
                "workspace.primary.replaced",
                "workspace",
                workspace_id,
                metadata={
                    "project_id": project_id,
                    "idempotency_key": idempotency_key,
                    "old_link": self._link_audit_value(previous),
                    "new_link": self._link_audit_value(
                        repository.project_workspace_link(project_id, workspace_id)
                    ),
                },
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
            auth.require_workspace_registry_manager(workspace_id, user)
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
            repository = self._repository(conn)
            link = repository.project_workspace_link(project_id, workspace_id)
            if link is None or str(link["status"]) != "active":
                raise DomainNotFoundError("project workspace link")
            if bool(link["is_primary"]) and not allow_no_primary:
                raise DomainConflictError("Detach primary requires replacement or allow_no_primary")
            old_link = self._link_audit_value(link)
            repository.retire_project_workspace_link(
                project_id=project_id,
                workspace_id=workspace_id,
                now=_now(),
            )
            self._store_idempotency(
                conn,
                actor_user_id,
                "workspace.detach",
                idempotency_key,
                request,
                {"detached": True},
            )
            self._audit(
                conn,
                actor_user_id,
                "workspace.detached",
                "workspace",
                workspace_id,
                metadata={
                    "project_id": project_id,
                    "idempotency_key": idempotency_key,
                    "old_link": old_link,
                    "new_link": self._link_audit_value(
                        repository.project_workspace_link(project_id, workspace_id)
                    ),
                },
            )
            conn.commit()

    def add_member(
        self,
        project_id: str,
        member_user_id: str,
        role: str,
        can_publish: bool,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if role not in {"viewer", "editor"}:
            raise DomainConflictError("Unknown project role")
        if can_publish and role != "editor":
            raise DomainConflictError("Only editors may receive project publish permission")
        self._require_known_auth_user(member_user_id, allow_api_key_principal=True)
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "member_user_id": member_user_id,
                "role": role,
                "can_publish": can_publish,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "project.member.upsert", idempotency_key, request
                )
                if cached is not None:
                    return cached
            repository = self._repository(conn)
            project = repository.project(project_id)
            if project is None:
                raise DomainNotFoundError(project_id)
            if str(project["owner_user_id"]) == member_user_id:
                raise DomainConflictError("Project owner is not a project member")
            repository.upsert_project_member(
                project_id=project_id,
                user_id=member_user_id,
                role=role,
                can_publish=can_publish,
                now=_now(),
            )
            result: dict[str, object] = {
                "project_id": project_id,
                "user_id": member_user_id,
                "role": role,
                "can_publish": can_publish,
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.member.upsert",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project.member.updated", "project", project_id)
            conn.commit()
            return result

    def remove_member(
        self,
        project_id: str,
        member_user_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_owner(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "member_user_id": member_user_id,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "project.member.remove", idempotency_key, request
                )
                if cached is not None:
                    return cached
            repository = self._repository(conn)
            owner = repository.project(project_id)
            if owner is None:
                raise DomainNotFoundError(project_id)
            if owner["owner_user_id"] == member_user_id:
                raise DomainConflictError("Project owner cannot be removed as a member")
            if repository.remove_project_member(project_id, member_user_id) != 1:
                raise DomainNotFoundError("project member")
            result: dict[str, object] = {
                "project_id": project_id,
                "user_id": member_user_id,
                "removed": True,
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.member.remove",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project.member.removed", "project", project_id)
            conn.commit()
            return result

    def list_project_members(
        self, project_id: str, user: dict[str, object]
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            rows = self._repository(conn).list_project_members(project_id)
        return [dict(row) for row in rows]

    def list_task_relationships(
        self, project_id: str, user: dict[str, object]
    ) -> list[dict[str, object]]:
        """Expose legacy task edges as typed ``related_to`` relationships."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, user)
            rows = self._repository(conn).list_related_task_relationships(project_id)
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
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Create the compatibility ``related_to`` edge in SQLite."""

        relationship_type = "related_to"
        relationship_id = self._relationship_id(source_task_id, target_task_id, relationship_type)
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "source_task_id": source_task_id,
                "target_task_id": target_task_id,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "task.relationship.create",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            repository = self._repository(conn)
            if not repository.project_tasks_exist(
                project_id=project_id,
                source_task_id=source_task_id,
                target_task_id=target_task_id,
            ):
                raise DomainNotFoundError("project task")
            now = _now()
            repository.insert_task_relationship(
                source_task_id=source_task_id,
                target_task_id=target_task_id,
                relationship_type=relationship_type,
                relationship_id=relationship_id,
                metadata_json="{}",
                created_at=now,
            )
            row = repository.task_relationship_for_pair(
                source_task_id=source_task_id,
                target_task_id=target_task_id,
                relationship_type=relationship_type,
            )
            if row is None:
                raise DomainConflictError("Task relationship was not created")
            result: dict[str, object] = {
                "edge_id": str(row["relationship_id"]),
                "project_id": project_id,
                "source_task_id": source_task_id,
                "target_task_id": target_task_id,
                "created_at": str(row["created_at"]),
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "task.relationship.create",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "task.relationship.created", "task", source_task_id)
            conn.commit()
        return result

    def delete_task_relationship(
        self,
        relationship_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            repository = self._repository(conn)
            row = repository.related_task_relationship(relationship_id)
            if row is None:
                raise DomainNotFoundError(relationship_id)
            project_id = str(row["project_id"])
            DomainAuthorizationService(conn).require_project_editor(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "relationship_id": relationship_id,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "task.relationship.delete",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return
            if repository.delete_task_relationship(relationship_id) != 1:
                raise DomainNotFoundError(relationship_id)
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "task.relationship.delete",
                    idempotency_key,
                    request,
                    {"relationship_id": relationship_id, "deleted": True},
                )
            self._audit(
                conn,
                actor_user_id,
                "task.relationship.deleted",
                "task",
                str(row["source_task_id"]),
            )
            conn.commit()

    def transfer_project_owner(
        self,
        project_id: str,
        new_owner_user_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if not new_owner_user_id:
            raise DomainConflictError("new_owner_user_id is required")
        self._require_known_auth_user(new_owner_user_id)
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_owner(project_id, user)
            actor_user_id = self._user_id(user)
            request: dict[str, object] = {
                "project_id": project_id,
                "new_owner_user_id": new_owner_user_id,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "project.owner.transfer", idempotency_key, request
                )
                if cached is not None:
                    return cached
            repository = self._repository(conn)
            project = repository.project(project_id)
            if project is None:
                raise DomainNotFoundError(project_id)
            if bool(project["is_default"]):
                raise DomainConflictError("Default Project ownership cannot be transferred")
            old_owner_user_id = str(project["owner_user_id"])
            if old_owner_user_id == new_owner_user_id:
                result: dict[str, object] = {
                    "project_id": project_id,
                    "owner_user_id": new_owner_user_id,
                    "transferred": False,
                }
                if idempotency_key is not None:
                    self._store_idempotency(
                        conn,
                        actor_user_id,
                        "project.owner.transfer",
                        idempotency_key,
                        request,
                        result,
                    )
                conn.commit()
                return result
            now = _now()
            if (
                repository.update_project(
                    project_id,
                    {"owner_user_id": new_owner_user_id, "updated_at": now},
                )
                != 1
            ):
                raise DomainNotFoundError(project_id)
            repository.upsert_project_member(
                project_id=project_id,
                user_id=old_owner_user_id,
                role="editor",
                can_publish=True,
                now=now,
            )
            repository.remove_project_member(project_id, new_owner_user_id)
            result: dict[str, object] = {
                "project_id": project_id,
                "owner_user_id": new_owner_user_id,
                "transferred": True,
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.owner.transfer",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project.owner.transferred", "project", project_id)
            conn.commit()
            return result

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

        TaskApplicationService(self._state_root, artifact_sha=self._artifact_sha).archive_project(
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

        TaskApplicationService(self._state_root, artifact_sha=self._artifact_sha).unarchive_project(
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
            DomainAuthorizationService(conn).require_workspace_registry_manager(workspace_id, user)
            actor_user_id = self._user_id(user)
            repository = self._repository(conn)
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
            if repository.workspace_active_task_count(workspace_id) > 0:
                raise DomainConflictError(
                    "Cannot unregister a workspace with queued or running tasks"
                )
            primary = repository.active_primary_for_workspace(workspace_id)
            if primary is not None and not allow_no_primary:
                raise DomainConflictError("Replace the Primary Workspace before unregistering it")
            previous_links = [
                self._link_audit_value(link)
                for link in repository.list_project_links_for_workspace(workspace_id)
            ]
            repository.unregister_workspace_and_retire_links(workspace_id, now=_now())
            self._audit(
                conn,
                actor_user_id,
                "workspace.unregistered",
                "workspace",
                workspace_id,
                metadata={
                    "idempotency_key": idempotency_key,
                    "old_links": previous_links,
                    "new_links": [
                        self._link_audit_value(link)
                        for link in repository.list_project_links_for_workspace(workspace_id)
                    ],
                },
            )
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
            row = self._repository(conn).project(project_id)
        return dict(row) if row is not None else {}

    def require_project_editor(self, project_id: str, user: dict[str, object]) -> None:
        """Expose the v2 Project capability check to compatibility adapters."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, user)

    def require_project_owner(self, project_id: str, user: dict[str, object]) -> None:
        """Expose owner-only Project actions without a route-local SQL query."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_owner(project_id, user)

    def require_project_publisher(self, project_id: str, user: dict[str, object]) -> None:
        """Expose Context publication capability to the API adapter layer."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_publisher(project_id, user)

    def require_task_owner(self, task_id: str, user: dict[str, object]) -> None:
        """Expose the mutation capability while preserving 404/403 semantics."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_owner(task_id, user)

    def list_projects(
        self, user: dict[str, object], *, include_archived: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            rows = self._repository(conn).list_projects_visible(
                user_id=self._user_id(user),
                is_admin=user.get("role") == "admin",
                include_archived=include_archived,
            )
        return [dict(row) for row in rows]

    def workspace(self, workspace_id: str, user: dict[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_workspace_viewer(workspace_id, user)
            row = self._repository(conn).workspace(workspace_id)
        return dict(row) if row is not None else {}

    def list_workspaces(
        self,
        user: dict[str, object],
        *,
        include_unregistered: bool = False,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        """List only registry records the caller may inspect.

        A Project link is authoritative for filtering by ``project_id`` but
        never grants access to a tenant-private Workspace path.  Therefore a
        collaborator first needs Project visibility and then sees only their
        own linked Workspaces (an admin sees all registry records for product
        administration, but still cannot execute a different tenant's path).
        """

        with closing(self._connect()) as conn:
            repository = self._repository(conn)
            if project_id is not None:
                DomainAuthorizationService(conn).require_project_viewer(project_id, user)
                rows = repository.list_workspaces_linked_to_project(
                    project_id=project_id,
                    owner_user_id=None if user.get("role") == "admin" else self._user_id(user),
                    include_unregistered=include_unregistered,
                )
            else:
                rows = repository.list_workspaces_owned(
                    user_id=None if user.get("role") == "admin" else self._user_id(user),
                    include_unregistered=include_unregistered,
                )
        return [dict(row) for row in rows]

    def list_environments(
        self, user: dict[str, object], *, include_disabled: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            rows = self._repository(conn).list_environments(include_disabled=include_disabled)
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
            rows = self._repository(conn).list_workspace_links(project_id)
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
            elif not self._has_environment_execution_access(
                environment_id=str(row["environment_id"]),
                user=user,
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
            row = self._repository(conn).environment(environment_id)
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
            auth.require_workspace_registry_manager(workspace_id, user)
            actor_user_id = self._user_id(user)
            repository = self._repository(conn)
            request: dict[str, object] = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "make_primary": make_primary,
            }
            cached = self._idempotent_result(conn, actor_user_id, scope, idempotency_key, request)
            if cached is not None:
                return cached
            project = repository.project(project_id)
            workspace = repository.linked_workspace_state(workspace_id)
            if project is None or str(project["status"]) != "active":
                raise DomainConflictError("Workspace links require an active Project")
            if workspace is None or str(workspace["workspace_status"]) != "active":
                raise DomainConflictError("Workspace links require an active Workspace")
            if str(workspace["environment_status"]) != "active":
                raise DomainConflictError("Workspace links require an active Environment")
            can_execute = self._has_environment_execution_access(
                environment_id=str(workspace["environment_id"]), user=user
            )
            if user.get("role") != "admin" and not can_execute:
                raise DomainPermissionError("Active Environment access is required")
            existing_link = repository.project_workspace_link(project_id, workspace_id)
            if make_primary and (existing_link is None or str(existing_link["status"]) != "active"):
                raise DomainConflictError(
                    "Primary Workspace must already be an active Project link"
                )
            old_link = self._link_audit_value(existing_link)
            active_primary = repository.active_primary_for_project(project_id)
            old_primary = self._link_audit_value(active_primary)
            if (
                make_primary
                and active_primary is not None
                and str(active_primary["workspace_id"]) != workspace_id
            ):
                raise DomainConflictError(
                    "Replace the active Primary Workspace with the replace operation"
                )
            now = _now()
            if make_primary:
                repository.clear_active_primary(project_id, now=now)
            repository.upsert_project_workspace_link(
                project_id=project_id,
                workspace_id=workspace_id,
                is_primary=make_primary,
                actor_id=actor_user_id,
                now=now,
            )
            result: dict[str, object] = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "is_primary": make_primary,
                "environment_id": str(workspace["environment_id"]),
                "can_execute": can_execute,
                "cannot_execute_reason": None
                if can_execute
                else "active Environment grant is required",
            }
            self._store_idempotency(conn, actor_user_id, scope, idempotency_key, request, result)
            self._audit(
                conn,
                actor_user_id,
                "workspace.primary_set" if make_primary else "workspace.attached",
                "workspace",
                workspace_id,
                metadata={
                    "project_id": project_id,
                    "idempotency_key": idempotency_key,
                    "old_link": old_link,
                    "old_primary": old_primary,
                    "new_link": self._link_audit_value(
                        repository.project_workspace_link(project_id, workspace_id)
                    ),
                },
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
        repository = self._repository(conn)
        project = repository.project(project_id)
        workspace = repository.linked_workspace_state(workspace_id)
        if project is None or str(project["status"]) != "active":
            raise DomainConflictError("Workspace links require an active Project")
        if workspace is None or str(workspace["workspace_status"]) != "active":
            raise DomainConflictError("Workspace links require an active Workspace")
        if str(workspace["environment_status"]) != "active":
            raise DomainConflictError("Workspace links require an active Environment")
        can_execute = self._has_environment_execution_access(
            environment_id=str(workspace["environment_id"]), user=user
        )
        if user.get("role") != "admin" and not can_execute:
            raise DomainPermissionError("Active Environment access is required")
        target_link = repository.project_workspace_link(project_id, workspace_id)
        if target_link is None or str(target_link["status"]) != "active":
            raise DomainConflictError("Primary Workspace must already be an active Project link")
        now = _now()
        repository.clear_active_primary(project_id, now=now)
        repository.upsert_project_workspace_link(
            project_id=project_id,
            workspace_id=workspace_id,
            is_primary=True,
            actor_id=actor_user_id,
            now=now,
        )
        return {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "is_primary": True,
            "environment_id": str(workspace["environment_id"]),
            "can_execute": can_execute,
            "cannot_execute_reason": None
            if can_execute
            else "active Environment grant is required",
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
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._write_fence.record_first_v2_write(conn, actor_id=actor_id)
        self._repository(conn).insert_audit_event(
            event_id=uuid4().hex,
            actor_id=actor_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True),
            created_at=_now(),
        )

    @staticmethod
    def _link_audit_value(link: sqlite3.Row | None) -> dict[str, object] | None:
        if link is None:
            return None
        return {
            "project_id": str(link["project_id"]),
            "workspace_id": str(link["workspace_id"]),
            "status": str(link["status"]),
            "is_primary": bool(link["is_primary"]),
        }

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
        row = SqliteDomainRepository(conn).idempotency_record(
            actor_user_id=actor_user_id,
            scope=scope,
            key=key,
        )
        if row is None:
            return None
        if str(row["request_hash"]) != cls._request_hash(request):
            record_durable_idempotency_event(
                "conflict",
                actor_user_id=actor_user_id,
                scope=scope,
                idempotency_key=key,
                request=request,
            )
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        value = json.loads(row["response_json"])
        if not isinstance(value, dict):
            raise DomainConflictError("Stored idempotency response is invalid")
        result = {str(item_key): item for item_key, item in value.items()}
        record_durable_idempotency_event(
            "reused",
            actor_user_id=actor_user_id,
            scope=scope,
            idempotency_key=key,
            request=request,
            response=result,
        )
        return result

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
        SqliteDomainRepository(conn).insert_idempotency_record(
            actor_user_id=actor_user_id,
            scope=scope,
            key=key,
            request_hash=cls._request_hash(request),
            response_json=json.dumps(result, ensure_ascii=True, sort_keys=True),
            created_at=_now(),
        )

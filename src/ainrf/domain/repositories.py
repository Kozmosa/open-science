"""SQLite repository boundary for the authoritative domain registry.

Routes never receive a repository.  Application services own transactions and
authorization, while this module owns the SQL that persists Project,
Workspace, Environment, membership, link, and idempotency records.  Keeping
the boundary explicit is important during the legacy-to-v2 compatibility
window: a compatibility adapter must not grow a second direct SQLite writer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping


class SqliteDomainRepository:
    """Persistence operations for the v2 Project/Workspace control plane."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Project and membership
    # ------------------------------------------------------------------
    def project(self, project_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()

    def project_owner(self, project_id: str) -> object | None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return None if row is None else row["owner_user_id"]

    def default_projects_for_owner(self, owner_user_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM projects
            WHERE owner_user_id = ? AND is_default = 1
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, created_at, project_id
            """,
            (owner_user_id,),
        ).fetchall()

    def insert_project(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        name: str,
        description: str | None,
        status: str,
        is_default: bool,
        created_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, description, status, is_default,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                owner_user_id,
                name,
                description,
                status,
                int(is_default),
                created_at,
                updated_at,
            ),
        )

    def update_project(self, project_id: str, changes: Mapping[str, object]) -> int:
        return self._update(
            "projects",
            "project_id",
            project_id,
            changes,
            frozenset(
                {
                    "name",
                    "description",
                    "owner_user_id",
                    "status",
                    "archived_at",
                    "archive_reason",
                    "updated_at",
                }
            ),
        )

    def list_projects_visible(
        self, *, user_id: str, is_admin: bool, include_archived: bool
    ) -> list[sqlite3.Row]:
        if is_admin:
            return self._conn.execute(
                """
                SELECT * FROM projects
                WHERE ? OR status = 'active'
                ORDER BY updated_at DESC, project_id
                """,
                (int(include_archived),),
            ).fetchall()
        return self._conn.execute(
            """
            SELECT DISTINCT project.* FROM projects AS project
            LEFT JOIN project_members AS member ON member.project_id = project.project_id
            WHERE (project.owner_user_id = ? OR member.user_id = ?)
              AND (? OR project.status = 'active')
            ORDER BY project.updated_at DESC, project.project_id
            """,
            (user_id, user_id, int(include_archived)),
        ).fetchall()

    def project_member(self, project_id: str, user_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT role, can_publish, created_at, updated_at
            FROM project_members WHERE project_id = ? AND user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()

    def upsert_project_member(
        self,
        *,
        project_id: str,
        user_id: str,
        role: str,
        can_publish: bool,
        now: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO project_members (
                project_id, user_id, role, can_publish, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, user_id) DO UPDATE SET
                role = excluded.role,
                can_publish = excluded.can_publish,
                updated_at = excluded.updated_at
            """,
            (project_id, user_id, role, int(can_publish), now, now),
        )

    def remove_project_member(self, project_id: str, user_id: str) -> int:
        return self._conn.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).rowcount

    def list_project_members(self, project_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT user_id, role, can_publish, created_at, updated_at
            FROM project_members
            WHERE project_id = ?
            ORDER BY created_at, user_id
            """,
            (project_id,),
        ).fetchall()

    def project_activity_summary(self, project_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS task_count,
                   COALESCE(SUM(CASE
                       WHEN archived_at IS NULL
                        AND status IN ('queued', 'starting', 'running', 'paused')
                       THEN 1 ELSE 0 END), 0) AS active_task_count,
                   COALESCE(SUM(CASE
                       WHEN archived_at IS NULL AND status IN ('starting', 'running')
                       THEN 1 ELSE 0 END), 0) AS running_task_count,
                   COALESCE(SUM(CASE
                       WHEN archived_at IS NULL AND status = 'failed'
                       THEN 1 ELSE 0 END), 0) AS failed_task_count,
                   MAX(updated_at) AS latest_task_activity_at
            FROM tasks
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - aggregate queries always return one row
            raise RuntimeError("Project activity summary query returned no row")
        return row

    def project_tasks_exist(
        self,
        *,
        project_id: str,
        source_task_id: str,
        target_task_id: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS task_count FROM tasks
            WHERE project_id = ? AND task_id IN (?, ?)
            """,
            (project_id, source_task_id, target_task_id),
        ).fetchone()
        return row is not None and int(row["task_count"]) == 2

    def list_related_task_relationships(self, project_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT relationship.relationship_id, relationship.source_task_id,
                   relationship.target_task_id, relationship.relationship_type,
                   relationship.created_at
            FROM task_relationships AS relationship
            JOIN tasks AS source ON source.task_id = relationship.source_task_id
            JOIN tasks AS target ON target.task_id = relationship.target_task_id
            WHERE source.project_id = ?
              AND target.project_id = ?
            ORDER BY relationship.created_at, relationship.relationship_id
            """,
            (project_id, project_id),
        ).fetchall()

    def insert_task_relationship(
        self,
        *,
        source_task_id: str,
        target_task_id: str,
        relationship_type: str,
        relationship_id: str,
        metadata_json: str,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO task_relationships (
                source_task_id, target_task_id, relationship_type,
                relationship_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_task_id, target_task_id, relationship_type) DO NOTHING
            """,
            (
                source_task_id,
                target_task_id,
                relationship_type,
                relationship_id,
                metadata_json,
                created_at,
            ),
        )

    def task_relationship_for_pair(
        self,
        *,
        source_task_id: str,
        target_task_id: str,
        relationship_type: str,
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT relationship_id, created_at FROM task_relationships
            WHERE source_task_id = ? AND target_task_id = ? AND relationship_type = ?
            """,
            (source_task_id, target_task_id, relationship_type),
        ).fetchone()

    def related_task_relationship(self, relationship_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT relationship.source_task_id, source.project_id
            FROM task_relationships AS relationship
            JOIN tasks AS source ON source.task_id = relationship.source_task_id
            WHERE relationship.relationship_id = ?
              AND relationship.relationship_type = 'related_to'
            """,
            (relationship_id,),
        ).fetchone()

    def delete_task_relationship(self, relationship_id: str) -> int:
        return self._conn.execute(
            "DELETE FROM task_relationships WHERE relationship_id = ?", (relationship_id,)
        ).rowcount

    # ------------------------------------------------------------------
    # Environment registry
    # ------------------------------------------------------------------
    def environment(self, environment_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
        ).fetchone()

    def insert_environment(
        self,
        *,
        environment_id: str,
        alias: str,
        owner_user_id: str,
        display_name: str,
        description: str | None,
        connection_json: str,
        connection_fingerprint: str,
        credential_ref: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, connection_fingerprint, credential_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                environment_id,
                alias,
                owner_user_id,
                display_name,
                description,
                connection_json,
                connection_fingerprint,
                credential_ref,
                created_at,
                updated_at,
            ),
        )

    def update_environment(self, environment_id: str, changes: Mapping[str, object]) -> int:
        return self._update(
            "environments",
            "environment_id",
            environment_id,
            changes,
            frozenset(
                {
                    "alias",
                    "display_name",
                    "description",
                    "connection_json",
                    "connection_fingerprint",
                    "credential_ref",
                    "status",
                    "disabled_at",
                    "disabled_reason",
                    "updated_at",
                }
            ),
        )

    def environment_is_referenced(self, environment_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM workspaces WHERE environment_id = ?
            ) OR EXISTS(
                SELECT 1 FROM tasks WHERE environment_id = ?
            )
            """,
            (environment_id, environment_id),
        ).fetchone()
        return row is not None and bool(row[0])

    def list_environments(self, *, include_disabled: bool) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM environments
            WHERE ? OR status = 'active'
            ORDER BY alias, environment_id
            """,
            (int(include_disabled),),
        ).fetchall()

    # ------------------------------------------------------------------
    # Workspace registry and Project links
    # ------------------------------------------------------------------
    def workspace(self, workspace_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()

    def workspace_owner(self, workspace_id: str) -> object | None:
        row = self._conn.execute(
            "SELECT owner_user_id FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        return None if row is None else row["owner_user_id"]

    def insert_workspace(
        self,
        *,
        workspace_id: str,
        owner_user_id: str,
        environment_id: str,
        canonical_path: str,
        label: str,
        description: str | None,
        context_metadata_json: str,
        workspace_context: str | None,
        legacy_project_id: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                description, context_metadata_json, workspace_context, legacy_project_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                owner_user_id,
                environment_id,
                canonical_path,
                label,
                description,
                context_metadata_json,
                workspace_context,
                legacy_project_id,
                created_at,
                updated_at,
            ),
        )

    def update_workspace(self, workspace_id: str, changes: Mapping[str, object]) -> int:
        return self._update(
            "workspaces",
            "workspace_id",
            workspace_id,
            changes,
            frozenset(
                {
                    "label",
                    "description",
                    "canonical_path",
                    "context_metadata_json",
                    "workspace_context",
                    "status",
                    "updated_at",
                }
            ),
        )

    def list_workspaces_owned(
        self, *, user_id: str | None, include_unregistered: bool
    ) -> list[sqlite3.Row]:
        if user_id is None:
            return self._conn.execute(
                """
                SELECT * FROM workspaces
                WHERE ? OR status = 'active'
                ORDER BY updated_at DESC, workspace_id
                """,
                (int(include_unregistered),),
            ).fetchall()
        return self._conn.execute(
            """
            SELECT * FROM workspaces
            WHERE owner_user_id = ? AND (? OR status = 'active')
            ORDER BY updated_at DESC, workspace_id
            """,
            (user_id, int(include_unregistered)),
        ).fetchall()

    def list_workspaces_linked_to_project(
        self,
        *,
        project_id: str,
        owner_user_id: str | None,
        include_unregistered: bool,
    ) -> list[sqlite3.Row]:
        clauses = ["link.project_id = ?", "link.status = 'active'"]
        parameters: list[object] = [project_id]
        if owner_user_id is not None:
            clauses.append("workspace.owner_user_id = ?")
            parameters.append(owner_user_id)
        if not include_unregistered:
            clauses.append("workspace.status = 'active'")
        return self._conn.execute(
            f"""
            SELECT workspace.* FROM project_workspace_links AS link
            JOIN workspaces AS workspace ON workspace.workspace_id = link.workspace_id
            WHERE {" AND ".join(clauses)}
            ORDER BY link.is_primary DESC, workspace.updated_at DESC, workspace.workspace_id
            """,
            parameters,
        ).fetchall()

    def workspace_active_task_count(self, workspace_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE workspace_id = ? AND status IN ('queued', 'starting', 'running')
            """,
            (workspace_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def workspace_activity_summary(self, workspace_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS task_count,
                   COALESCE(SUM(CASE
                       WHEN archived_at IS NULL
                        AND status IN ('queued', 'starting', 'running', 'paused')
                       THEN 1 ELSE 0 END), 0) AS active_task_count,
                   MAX(updated_at) AS latest_task_activity_at
            FROM tasks
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - aggregate queries always return one row
            raise RuntimeError("Workspace activity summary query returned no row")
        return row

    def project_workspace_link(self, project_id: str, workspace_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM project_workspace_links
            WHERE project_id = ? AND workspace_id = ?
            """,
            (project_id, workspace_id),
        ).fetchone()

    def active_primary_for_workspace(self, workspace_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT project_id FROM project_workspace_links
            WHERE workspace_id = ? AND status = 'active' AND is_primary = 1
            """,
            (workspace_id,),
        ).fetchone()

    def active_primary_for_project(self, project_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM project_workspace_links
            WHERE project_id = ? AND status = 'active' AND is_primary = 1
            """,
            (project_id,),
        ).fetchone()

    def list_workspace_links(self, project_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT link.project_id, link.workspace_id, link.status, link.is_primary,
                   workspace.environment_id, workspace.owner_user_id, workspace.label,
                   workspace.canonical_path,
                   workspace.status AS workspace_status,
                   environment.status AS environment_status, environment.alias AS environment_alias,
                   environment.display_name AS environment_display_name,
                   environment.owner_user_id AS environment_owner_user_id
            FROM project_workspace_links AS link
            JOIN workspaces AS workspace ON workspace.workspace_id = link.workspace_id
            JOIN environments AS environment ON environment.environment_id = workspace.environment_id
            WHERE link.project_id = ?
            ORDER BY link.is_primary DESC, link.created_at, link.workspace_id
            """,
            (project_id,),
        ).fetchall()

    def list_project_links_for_workspace(self, workspace_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT link.project_id, link.workspace_id, link.status, link.is_primary,
                   link.created_at, link.updated_at,
                   project.name AS project_name, project.status AS project_status,
                   project.owner_user_id AS project_owner_user_id,
                   project.is_default AS project_is_default
            FROM project_workspace_links AS link
            JOIN projects AS project ON project.project_id = link.project_id
            WHERE link.workspace_id = ?
            ORDER BY link.is_primary DESC, project.name, link.project_id
            """,
            (workspace_id,),
        ).fetchall()

    def linked_workspace_state(self, workspace_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT workspace.environment_id, workspace.status AS workspace_status,
                   environment.status AS environment_status, environment.owner_user_id
            FROM workspaces AS workspace
            JOIN environments AS environment ON environment.environment_id = workspace.environment_id
            WHERE workspace.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()

    def clear_active_primary(self, project_id: str, *, now: str) -> None:
        self._conn.execute(
            """
            UPDATE project_workspace_links
            SET is_primary = 0, updated_at = ?
            WHERE project_id = ? AND status = 'active'
            """,
            (now, project_id),
        )

    def upsert_project_workspace_link(
        self,
        *,
        project_id: str,
        workspace_id: str,
        is_primary: bool,
        actor_id: str,
        now: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES (?, ?, 'active', ?, ?, ?, ?)
            ON CONFLICT(project_id, workspace_id) DO UPDATE SET
                status = 'active', is_primary = excluded.is_primary,
                actor_id = excluded.actor_id, updated_at = excluded.updated_at
            """,
            (project_id, workspace_id, int(is_primary), actor_id, now, now),
        )

    def retire_project_workspace_link(self, *, project_id: str, workspace_id: str, now: str) -> int:
        return self._conn.execute(
            """
            UPDATE project_workspace_links
            SET status = 'retired', is_primary = 0, updated_at = ?
            WHERE project_id = ? AND workspace_id = ?
            """,
            (now, project_id, workspace_id),
        ).rowcount

    def unregister_workspace_and_retire_links(self, workspace_id: str, *, now: str) -> None:
        self._conn.execute(
            "UPDATE workspaces SET status = 'unregistered', updated_at = ? WHERE workspace_id = ?",
            (now, workspace_id),
        )
        self._conn.execute(
            """
            UPDATE project_workspace_links
            SET status = 'retired', is_primary = 0, updated_at = ?
            WHERE workspace_id = ?
            """,
            (now, workspace_id),
        )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def insert_audit_event(
        self,
        *,
        event_id: str,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
        metadata_json: str,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO domain_audit_events (
                event_id, actor_id, event_type, subject_type, subject_id,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                actor_id,
                event_type,
                subject_type,
                subject_id,
                metadata_json,
                created_at,
            ),
        )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------
    def idempotency_record(self, *, actor_user_id: str, scope: str, key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT request_hash, response_json FROM domain_idempotency_requests
            WHERE actor_user_id = ? AND scope = ? AND idempotency_key = ?
            """,
            (actor_user_id, scope, key),
        ).fetchone()

    def insert_idempotency_record(
        self,
        *,
        actor_user_id: str,
        scope: str,
        key: str,
        request_hash: str,
        response_json: str,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO domain_idempotency_requests (
                actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (actor_user_id, scope, key, request_hash, response_json, created_at),
        )

    def task_owner_and_project(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT owner_user_id, project_id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()

    def _update(
        self,
        table: str,
        key_column: str,
        key_value: str,
        changes: Mapping[str, object],
        allowed_columns: frozenset[str],
    ) -> int:
        if not changes:
            return 0
        unknown = set(changes).difference(allowed_columns)
        if unknown:
            raise ValueError(f"Unsupported {table} columns: {', '.join(sorted(unknown))}")
        assignments = ", ".join(f"{column} = ?" for column in changes)
        return self._conn.execute(
            f"UPDATE {table} SET {assignments} WHERE {key_column} = ?",
            (*changes.values(), key_value),
        ).rowcount

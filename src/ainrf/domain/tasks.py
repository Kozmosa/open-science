"""Transactional v2 Task lifecycle application service."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.context import ProjectContextService
from ainrf.domain.service import (
    DomainAuthorizationService,
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
)
from ainrf.domain_control import MaintenanceModeError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _request_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class TaskApplicationService:
    """The only v2 writer for Task lifecycle mutations.

    Each public mutation opens an ``IMMEDIATE`` SQLite transaction before
    reading state.  This deliberately serializes Task creation, retry,
    archive, and dispatcher-facing invalidation around the same control-plane
    database instead of relying on best-effort process-local scheduling.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._context_service = ProjectContextService(state_root)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _user_id(user: Mapping[str, object]) -> str:
        value = user.get("id")
        if not isinstance(value, str) or not value:
            raise DomainPermissionError("Authenticated user ID is required")
        return value

    def _begin(self, conn: sqlite3.Connection) -> None:
        """Acquire the SQLite write fence and reject a maintenance epoch.

        ``BEGIN IMMEDIATE`` serializes this check with ``maintenance.enter``:
        a mutation that acquired the database writer first completes before
        maintenance becomes active; a later mutation observes the active
        epoch and fails closed.  This also covers direct callers such as the
        Literature saga that do not pass through HTTP middleware.
        """

        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if state is None or bool(state["is_active"]):
            raise MaintenanceModeError("domain writes are paused for maintenance")

    # ------------------------------------------------------------------
    # Creation and retry
    # ------------------------------------------------------------------
    def create_task(
        self,
        user: Mapping[str, object],
        *,
        project_id: str,
        workspace_id: str,
        title: str,
        prompt: str,
        researcher_type: str,
        harness_engine: str,
        idempotency_key: str,
        environment_id: str | None = None,
        user_skills: list[str] | None = None,
        user_mcp_servers: list[str] | None = None,
    ) -> dict[str, str]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "title": title,
            "prompt": prompt,
            "researcher_type": researcher_type,
            "harness_engine": harness_engine,
            "environment_id": environment_id,
            "user_skills": list(user_skills or []),
            "user_mcp_servers": list(user_mcp_servers or []),
        }
        with closing(self._connect()) as conn:
            self._begin(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, dict(user))
            auth.require_workspace_owner(workspace_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.create", idempotency_key, request
            )
            if cached is not None:
                return self._string_result(cached)
            workspace = self._writable_workspace(
                conn,
                project_id=project_id,
                workspace_id=workspace_id,
                expected_environment_id=environment_id,
            )
            grant_version = self._grant_version(
                environment_id=str(workspace["environment_id"]),
                actor_user_id=actor_user_id,
                environment_owner_user_id=workspace["environment_owner_user_id"],
            )
            task_id = f"task-{uuid4().hex}"
            snapshot_id, context_version_id = (
                self._context_service.create_active_snapshot_for_task_in_transaction(
                    conn,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    task_id=task_id,
                    task_prompt=prompt,
                )
            )
            now = _now()
            conn.execute(
                """INSERT INTO tasks (
                       task_id, project_id, workspace_id, environment_id, researcher_type,
                       harness_engine, user_skills, user_mcp_servers, status, title, prompt,
                       created_at, updated_at, owner_user_id, project_context_version_id,
                       project_context_snapshot_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    project_id,
                    workspace_id,
                    str(workspace["environment_id"]),
                    researcher_type,
                    harness_engine,
                    json.dumps(user_skills or [], sort_keys=True),
                    json.dumps(user_mcp_servers or [], sort_keys=True),
                    title,
                    prompt,
                    now,
                    now,
                    actor_user_id,
                    context_version_id,
                    snapshot_id,
                ),
            )
            result = self._create_attempt_in_transaction(
                conn,
                task_id=task_id,
                trigger="initial",
                context_snapshot_id=snapshot_id,
                authorization_environment_id=str(workspace["environment_id"]),
                authorization_grant_version=grant_version,
            )
            self._store_idempotency(
                conn, actor_user_id, "task.create", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.created", "task", task_id)
            conn.commit()
            return result

    def retry_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, str]:
        return self._new_attempt_for_task(
            task_id,
            user,
            trigger="retry",
            scope="task.retry",
            idempotency_key=idempotency_key,
            request_extra={},
        )

    def continue_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        prompt: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"task_id": task_id, "prompt": prompt}
        with closing(self._connect()) as conn:
            self._begin(conn)
            self._owned_task(conn, task_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.continue", idempotency_key, request
            )
            if cached is not None:
                return cached
            task = self._owned_active_task(conn, task_id, dict(user))
            attempt = self._latest_attempt(conn, task_id)
            result: dict[str, object]
            if attempt is not None and attempt["status"] in {"starting", "running", "paused"}:
                result = self._request_control_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    action="continue",
                    actor_user_id=actor_user_id,
                    idempotency_key=f"task.continue:{idempotency_key}",
                    request_hash=_request_hash(request),
                    reason=None,
                    payload={"prompt": prompt},
                )
                result["message_sequence"] = self._append_user_message_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    prompt=prompt,
                )
            elif attempt is not None and attempt["status"] in self._terminal_attempt_statuses():
                snapshot_id = self._continuation_snapshot_in_transaction(
                    conn,
                    task=task,
                    continuation_prompt=prompt,
                )
                result = self._object_result(
                    self._create_attempt_for_existing_task_in_transaction(
                        conn,
                        task=task,
                        user=user,
                        actor_user_id=actor_user_id,
                        trigger="continue",
                        context_snapshot_id=snapshot_id,
                    )
                )
                result["message_sequence"] = self._append_user_message_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(result["attempt_id"]),
                    prompt=prompt,
                )
            else:
                raise DomainConflictError("Task is not ready to continue")
            self._store_idempotency(
                conn, actor_user_id, "task.continue", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.continued", "task", task_id)
            conn.commit()
            return result

    # ------------------------------------------------------------------
    # Runtime control and archive
    # ------------------------------------------------------------------
    def pause_task(
        self, task_id: str, user: Mapping[str, object], *, idempotency_key: str
    ) -> dict[str, object]:
        return self._control_task(
            task_id,
            user,
            action="pause",
            reason=None,
            idempotency_key=idempotency_key,
        )

    def resume_task(
        self, task_id: str, user: Mapping[str, object], *, idempotency_key: str
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"task_id": task_id, "action": "resume"}
        with closing(self._connect()) as conn:
            self._begin(conn)
            self._owned_task(conn, task_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.resume", idempotency_key, request
            )
            if cached is not None:
                return cached
            self._owned_active_task(conn, task_id, dict(user))
            attempt = self._latest_attempt(conn, task_id)
            if attempt is None:
                raise DomainConflictError("Task has no Attempt to resume")
            if attempt["status"] == "paused":
                result = self._request_control_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    action="resume",
                    actor_user_id=actor_user_id,
                    idempotency_key=f"task.resume:{idempotency_key}",
                    request_hash=_request_hash(request),
                    reason=None,
                    payload={},
                )
            else:
                raise DomainConflictError("Task is not paused")
            self._store_idempotency(
                conn, actor_user_id, "task.resume", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.resumed", "task", task_id)
            conn.commit()
            return result

    def cancel_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self._control_task(
            task_id,
            user,
            action="cancel",
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def archive_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"task_id": task_id, "reason": reason}
        with closing(self._connect()) as conn:
            self._begin(conn)
            task = self._owned_task(conn, task_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.archive", idempotency_key, request
            )
            if cached is not None:
                return cached
            if task["archived_at"] is not None:
                raise DomainConflictError("Task is already archived")
            now = _now()
            cancelled_attempt_ids = self._cancel_unstarted_dispatches_in_transaction(
                conn,
                task_id=task_id,
                reason=reason,
                now=now,
            )
            attempt = self._latest_attempt(conn, task_id)
            control: dict[str, object] | None = None
            if attempt is not None and attempt["status"] in {"starting", "running", "paused"}:
                control = self._request_control_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    action="cancel",
                    actor_user_id=actor_user_id,
                    idempotency_key=f"task.archive:{idempotency_key}",
                    request_hash=_request_hash(request),
                    reason=reason,
                    payload={"archive": True},
                )
            latest_cancelled = (
                attempt is not None and str(attempt["attempt_id"]) in cancelled_attempt_ids
            )
            if latest_cancelled:
                conn.execute(
                    """UPDATE tasks SET status = 'cancelled', updated_at = ?
                       WHERE task_id = ?""",
                    (now, task_id),
                )
            conn.execute(
                """UPDATE tasks
                   SET archived_at = ?, archive_reason = ?, updated_at = ?
                   WHERE task_id = ?""",
                (now, reason, now, task_id),
            )
            result: dict[str, object] = {
                "task_id": task_id,
                "archived": True,
                "cancelled_attempt_ids": cancelled_attempt_ids,
                "control": control,
            }
            self._store_idempotency(
                conn,
                actor_user_id,
                "task.archive",
                idempotency_key,
                request,
                result,
            )
            self._audit(conn, actor_user_id, "task.archived", "task", task_id)
            conn.commit()
            return result

    def unarchive_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"task_id": task_id}
        with closing(self._connect()) as conn:
            self._begin(conn)
            task = self._owned_task(conn, task_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.unarchive", idempotency_key, request
            )
            if cached is not None:
                return cached
            if task["archived_at"] is None:
                raise DomainConflictError("Task is not archived")
            project = conn.execute(
                "SELECT status FROM projects WHERE project_id = ?", (task["project_id"],)
            ).fetchone()
            if project is None or project["status"] != "active":
                raise DomainConflictError("Task Project must be active before unarchive")
            now = _now()
            conn.execute(
                """UPDATE tasks
                   SET archived_at = NULL, archive_reason = NULL, updated_at = ?
                   WHERE task_id = ?""",
                (now, task_id),
            )
            result: dict[str, object] = {"task_id": task_id, "unarchived": True}
            self._store_idempotency(
                conn, actor_user_id, "task.unarchive", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.unarchived", "task", task_id)
            conn.commit()
            return result

    def archive_project(
        self,
        project_id: str,
        user: Mapping[str, object],
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"project_id": project_id, "reason": reason}
        with closing(self._connect()) as conn:
            self._begin(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_owner(project_id, dict(user))
            cached = self._idempotent_result(
                conn,
                actor_user_id,
                "project.archive",
                idempotency_key,
                request,
            )
            if cached is not None:
                return cached
            project = conn.execute(
                "SELECT status, is_default FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise DomainNotFoundError(project_id)
            if bool(project["is_default"]):
                raise DomainConflictError("Default projects cannot be archived")
            if project["status"] == "archived":
                raise DomainConflictError("Project is already archived")
            now = _now()
            task_rows = conn.execute(
                "SELECT task_id FROM tasks WHERE project_id = ?", (project_id,)
            ).fetchall()
            cancelled_attempt_ids: list[str] = []
            stop_requests: list[str] = []
            for row in task_rows:
                task_id = str(row["task_id"])
                cancelled_attempt_ids.extend(
                    self._cancel_unstarted_dispatches_in_transaction(
                        conn,
                        task_id=task_id,
                        reason=reason,
                        now=now,
                    )
                )
                latest = self._latest_attempt(conn, task_id)
                if latest is not None and latest["status"] == "paused":
                    control = self._request_control_in_transaction(
                        conn,
                        task_id=task_id,
                        attempt_id=str(latest["attempt_id"]),
                        action="stop",
                        actor_user_id=actor_user_id,
                        idempotency_key=None,
                        request_hash=None,
                        reason=reason,
                        payload={"project_archive": True},
                    )
                    stop_requests.append(str(control["control_request_id"]))
                    conn.execute(
                        """UPDATE agent_task_attempts
                           SET stop_requested_at = ?, stop_requested_reason = ?
                           WHERE attempt_id = ?""",
                        (now, reason, latest["attempt_id"]),
                    )
            if cancelled_attempt_ids:
                placeholders = ",".join("?" for _ in cancelled_attempt_ids)
                conn.execute(
                    f"""UPDATE tasks SET status = 'cancelled', updated_at = ?
                        WHERE latest_attempt_id IN ({placeholders})""",
                    (now, *cancelled_attempt_ids),
                )
            conn.execute(
                """UPDATE projects
                   SET status = 'archived', archived_at = ?, archive_reason = ?, updated_at = ?
                   WHERE project_id = ?""",
                (now, reason, now, project_id),
            )
            result: dict[str, object] = {
                "project_id": project_id,
                "archived": True,
                "cancelled_attempt_ids": cancelled_attempt_ids,
                "stop_request_ids": stop_requests,
            }
            self._store_idempotency(
                conn,
                actor_user_id,
                "project.archive",
                idempotency_key,
                request,
                result,
            )
            self._audit(conn, actor_user_id, "project.archived", "project", project_id)
            conn.commit()
            return result

    def unarchive_project(
        self,
        project_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"project_id": project_id}
        with closing(self._connect()) as conn:
            self._begin(conn)
            DomainAuthorizationService(conn).require_project_owner(project_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "project.unarchive", idempotency_key, request
            )
            if cached is not None:
                return cached
            updated = conn.execute(
                """UPDATE projects
                   SET status = 'active', archived_at = NULL, archive_reason = NULL, updated_at = ?
                   WHERE project_id = ? AND status = 'archived'""",
                (_now(), project_id),
            )
            if updated.rowcount != 1:
                raise DomainConflictError("Project is not archived")
            result: dict[str, object] = {"project_id": project_id, "unarchived": True}
            self._store_idempotency(
                conn, actor_user_id, "project.unarchive", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "project.unarchived", "project", project_id)
            conn.commit()
            return result

    # ------------------------------------------------------------------
    # Context, move, and fork
    # ------------------------------------------------------------------
    def preview_task_context_update(
        self, task_id: str, project_id: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        """Expose the B4 diff phase through the one Task lifecycle facade."""

        return self._context_service.preview_task_context_update(task_id, project_id, user)

    def confirm_task_context_update(
        self,
        task_id: str,
        project_id: str,
        preview_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Confirm a previously reviewed Context diff through this facade."""

        return self._context_service.confirm_task_context_update(
            task_id,
            project_id,
            preview_id,
            user,
            idempotency_key=idempotency_key,
        )

    def move_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        project_id: str,
        context_version_id: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {
            "task_id": task_id,
            "project_id": project_id,
            "context_version_id": context_version_id,
        }
        with closing(self._connect()) as conn:
            self._begin(conn)
            source = self._owned_task(conn, task_id, dict(user))
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, dict(user))
            auth.require_workspace_owner(str(source["workspace_id"]), dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.move", idempotency_key, request
            )
            if cached is not None:
                return cached
            task = self._owned_active_task(conn, task_id, dict(user))
            if str(task["project_id"]) == project_id:
                raise DomainConflictError("Task already belongs to the target Project")
            self._ensure_no_started_attempt(conn, task_id)
            self._writable_workspace(
                conn,
                project_id=project_id,
                workspace_id=str(task["workspace_id"]),
                expected_environment_id=str(task["environment_id"]),
            )
            snapshot_id = (
                self._context_service.create_snapshot_for_task_context_version_in_transaction(
                    conn,
                    project_id=project_id,
                    workspace_id=str(task["workspace_id"]),
                    task_id=task_id,
                    task_prompt=str(task["prompt"]),
                    context_version_id=context_version_id,
                )
            )
            now = _now()
            conn.execute(
                """UPDATE tasks
                   SET project_id = ?, project_context_version_id = ?,
                       project_context_snapshot_id = ?, updated_at = ?
                   WHERE task_id = ?""",
                (project_id, context_version_id, snapshot_id, now, task_id),
            )
            # A queued Attempt has not acquired a runtime identity yet, so it
            # may follow the explicitly selected Context Version.  Started
            # Attempts are rejected above and therefore retain their original
            # immutable Snapshot forever.
            conn.execute(
                """UPDATE agent_task_attempts
                   SET context_snapshot_id = ?
                   WHERE task_id = ? AND status = 'queued'""",
                (snapshot_id, task_id),
            )
            result: dict[str, object] = {
                "task_id": task_id,
                "project_id": project_id,
                "workspace_id": str(task["workspace_id"]),
                "context_version_id": context_version_id,
                "context_snapshot_id": snapshot_id,
            }
            self._store_idempotency(
                conn, actor_user_id, "task.move", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.moved", "task", task_id)
            conn.commit()
            return result

    def fork_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        workspace_id: str,
        idempotency_key: str,
        prompt: str | None = None,
        title: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, str]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "prompt": prompt,
            "title": title,
        }
        with closing(self._connect()) as conn:
            self._begin(conn)
            source = self._owned_task(conn, task_id, dict(user))
            target_project_id = project_id or str(source["project_id"])
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(target_project_id, dict(user))
            auth.require_workspace_owner(workspace_id, dict(user))
            cached = self._idempotent_result(
                conn, actor_user_id, "task.fork", idempotency_key, request
            )
            if cached is not None:
                return self._string_result(cached)
            workspace = self._writable_workspace(
                conn,
                project_id=target_project_id,
                workspace_id=workspace_id,
                expected_environment_id=None,
            )
            grant_version = self._grant_version(
                environment_id=str(workspace["environment_id"]),
                actor_user_id=actor_user_id,
                environment_owner_user_id=workspace["environment_owner_user_id"],
            )
            new_task_id = f"task-{uuid4().hex}"
            new_prompt = prompt if prompt is not None else str(source["prompt"])
            new_title = title if title is not None else str(source["title"])
            snapshot_id, context_version_id = (
                self._context_service.create_active_snapshot_for_task_in_transaction(
                    conn,
                    project_id=target_project_id,
                    workspace_id=workspace_id,
                    task_id=new_task_id,
                    task_prompt=new_prompt,
                )
            )
            now = _now()
            conn.execute(
                """INSERT INTO tasks (
                       task_id, project_id, workspace_id, environment_id, researcher_type,
                       harness_engine, user_skills, user_mcp_servers, status, title, prompt,
                       created_at, updated_at, owner_user_id, project_context_version_id,
                       project_context_snapshot_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_task_id,
                    target_project_id,
                    workspace_id,
                    str(workspace["environment_id"]),
                    str(source["researcher_type"]),
                    str(source["harness_engine"]),
                    str(source["user_skills"] or "[]"),
                    str(source["user_mcp_servers"] or "[]"),
                    new_title,
                    new_prompt,
                    now,
                    now,
                    actor_user_id,
                    context_version_id,
                    snapshot_id,
                ),
            )
            result = self._create_attempt_in_transaction(
                conn,
                task_id=new_task_id,
                trigger="initial",
                context_snapshot_id=snapshot_id,
                authorization_environment_id=str(workspace["environment_id"]),
                authorization_grant_version=grant_version,
            )
            conn.execute(
                """INSERT INTO task_relationships (
                       source_task_id, target_task_id, relationship_type, relationship_id,
                       metadata_json, created_at
                   ) VALUES (?, ?, 'derived_from', ?, '{}', ?)""",
                (
                    new_task_id,
                    task_id,
                    self._relationship_id(new_task_id, task_id, "derived_from"),
                    now,
                ),
            )
            self._store_idempotency(
                conn, actor_user_id, "task.fork", idempotency_key, request, result
            )
            self._audit(conn, actor_user_id, "task.forked", "task", new_task_id)
            conn.commit()
            return result

    # ------------------------------------------------------------------
    # Internal transaction primitives
    # ------------------------------------------------------------------
    def _new_attempt_for_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        trigger: str,
        scope: str,
        idempotency_key: str,
        request_extra: Mapping[str, object],
    ) -> dict[str, str]:
        actor_user_id = self._user_id(user)
        request: dict[str, object] = {"task_id": task_id, "trigger": trigger, **request_extra}
        with closing(self._connect()) as conn:
            self._begin(conn)
            preauthorized_task = self._owned_task(conn, task_id, dict(user))
            DomainAuthorizationService(conn).require_workspace_owner(
                str(preauthorized_task["workspace_id"]), dict(user)
            )
            cached = self._idempotent_result(conn, actor_user_id, scope, idempotency_key, request)
            if cached is not None:
                return self._string_result(cached)
            task = self._owned_active_task(conn, task_id, dict(user))
            latest = self._latest_attempt(conn, task_id)
            if latest is not None and latest["status"] == "queued":
                self._supersede_queued_attempt_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(latest["attempt_id"]),
                    reason=f"superseded by {trigger}",
                )
                latest = self._latest_attempt(conn, task_id)
            if latest is not None and latest["status"] not in self._terminal_attempt_statuses():
                raise DomainConflictError("Task already has an active Attempt")
            result = self._create_attempt_for_existing_task_in_transaction(
                conn,
                task=task,
                user=user,
                actor_user_id=actor_user_id,
                trigger=trigger,
            )
            self._store_idempotency(conn, actor_user_id, scope, idempotency_key, request, result)
            self._audit(conn, actor_user_id, f"task.{trigger}", "task", task_id)
            conn.commit()
            return self._string_result(result)

    def _create_attempt_for_existing_task_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task: sqlite3.Row,
        user: Mapping[str, object],
        actor_user_id: str,
        trigger: str,
        context_snapshot_id: str | None = None,
    ) -> dict[str, str]:
        project = conn.execute(
            "SELECT status FROM projects WHERE project_id = ?", (task["project_id"],)
        ).fetchone()
        if project is None or project["status"] != "active":
            raise DomainConflictError("Archived Project cannot create a new Attempt")
        if task["archived_at"] is not None:
            raise DomainConflictError("Archived Task cannot create a new Attempt")
        DomainAuthorizationService(conn).require_workspace_owner(
            str(task["workspace_id"]), dict(user)
        )
        workspace = self._writable_workspace(
            conn,
            project_id=str(task["project_id"]),
            workspace_id=str(task["workspace_id"]),
            expected_environment_id=str(task["environment_id"]),
        )
        grant_version = self._grant_version(
            environment_id=str(workspace["environment_id"]),
            actor_user_id=actor_user_id,
            environment_owner_user_id=workspace["environment_owner_user_id"],
        )
        snapshot_id = context_snapshot_id or task["project_context_snapshot_id"]
        if not isinstance(snapshot_id, str) or not snapshot_id:
            snapshot_id = self._context_service.ensure_task_snapshot_in_transaction(
                conn, str(task["task_id"])
            )
        return self._create_attempt_in_transaction(
            conn,
            task_id=str(task["task_id"]),
            trigger=trigger,
            context_snapshot_id=snapshot_id,
            authorization_environment_id=str(workspace["environment_id"]),
            authorization_grant_version=grant_version,
        )

    def _continuation_snapshot_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task: sqlite3.Row,
        continuation_prompt: str,
    ) -> str:
        """Persist a terminal-Attempt continuation as a fresh immutable input.

        The Task's default Context pin remains untouched: a continuation is an
        Attempt-specific user turn.  Its Context Snapshot preserves the
        original request plus the durable follow-up text, so a restarted
        worker never silently executes the old prompt instead.
        """

        context_version_id = task["project_context_version_id"]
        if not isinstance(context_version_id, str) or not context_version_id:
            self._context_service.ensure_task_snapshot_in_transaction(conn, str(task["task_id"]))
            refreshed = conn.execute(
                "SELECT project_context_version_id FROM tasks WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            context_version_id = (
                refreshed["project_context_version_id"] if refreshed is not None else None
            )
        if not isinstance(context_version_id, str) or not context_version_id:
            raise DomainConflictError("Task requires a pinned Project Context Version")
        original_prompt = str(task["prompt"])
        combined_prompt = (
            f"{original_prompt.rstrip()}\n\nContinuation request:\n{continuation_prompt.lstrip()}"
        )
        return self._context_service.create_snapshot_for_task_context_version_in_transaction(
            conn,
            project_id=str(task["project_id"]),
            workspace_id=str(task["workspace_id"]),
            task_id=str(task["task_id"]),
            task_prompt=combined_prompt,
            context_version_id=context_version_id,
        )

    @staticmethod
    def _append_user_message_in_transaction(
        conn: sqlite3.Connection,
        *,
        task_id: str,
        attempt_id: str,
        prompt: str,
    ) -> int:
        """Append an auditable continuation input inside the lifecycle write."""

        latest = conn.execute(
            "SELECT latest_output_seq FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if latest is None:
            raise DomainNotFoundError(task_id)
        sequence = int(latest["latest_output_seq"]) + 1
        now = _now()
        conn.execute(
            """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
               VALUES (?, ?, 'message', ?, ?)""",
            (
                task_id,
                sequence,
                _canonical_json({"role": "user", "content": prompt}),
                now,
            ),
        )
        conn.execute(
            "UPDATE tasks SET latest_output_seq = ?, updated_at = ? WHERE task_id = ?",
            (sequence, now, task_id),
        )
        conn.execute(
            """UPDATE agent_task_attempts
               SET message_start_seq = COALESCE(message_start_seq, ?), message_end_seq = ?
               WHERE attempt_id = ?""",
            (sequence, sequence, attempt_id),
        )
        return sequence

    def _supersede_queued_attempt_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        attempt_id: str,
        reason: str,
    ) -> None:
        """Cancel a never-launched queued Attempt before replacing it.

        Retrying an immediately queued Task remains compatible with the
        pre-v2 API, but it may only supersede an outbox row whose launch state
        is still ``none``.  A dispatcher that has crossed its deterministic
        launch boundary must be treated as active rather than guessed away.
        """

        now = _now()
        self._cancel_unstarted_dispatches_in_transaction(
            conn,
            task_id=task_id,
            reason=reason,
            now=now,
        )
        pending = conn.execute(
            """SELECT 1 FROM task_dispatch_outbox
               WHERE attempt_id = ? AND status != 'cancelled'
               LIMIT 1""",
            (attempt_id,),
        ).fetchone()
        if pending is not None:
            raise DomainConflictError("Task already has an active Attempt")
        conn.execute(
            """UPDATE agent_task_attempts
               SET status = 'cancelled', stop_reason = ?, finished_at = ?
               WHERE attempt_id = ? AND status = 'queued'""",
            (reason, now, attempt_id),
        )

    def _create_attempt_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        trigger: str,
        context_snapshot_id: str,
        authorization_environment_id: str,
        authorization_grant_version: int,
    ) -> dict[str, str]:
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
            """INSERT INTO agent_task_attempts (
                   attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id,
                   authorization_environment_id, authorization_grant_version,
                   authorization_checked_at, created_at
               ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                task_id,
                sequence,
                trigger,
                context_snapshot_id,
                authorization_environment_id,
                authorization_grant_version,
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO task_dispatch_outbox (
                   dispatch_id, task_id, attempt_id, status, created_at, updated_at,
                   authorization_environment_id, authorization_grant_version,
                   authorization_checked_at
               ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
            (
                dispatch_id,
                task_id,
                attempt_id,
                now,
                now,
                authorization_environment_id,
                authorization_grant_version,
                now,
            ),
        )
        conn.execute(
            """UPDATE tasks SET latest_attempt_id = ?, status = 'queued', updated_at = ?
               WHERE task_id = ?""",
            (attempt_id, now, task_id),
        )
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "dispatch_id": dispatch_id,
            "context_snapshot_id": context_snapshot_id,
        }

    def _control_task(
        self,
        task_id: str,
        user: Mapping[str, object],
        *,
        action: str,
        reason: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor_user_id = self._user_id(user)
        scope = f"task.{action}"
        request: dict[str, object] = {"task_id": task_id, "action": action, "reason": reason}
        with closing(self._connect()) as conn:
            self._begin(conn)
            self._owned_task(conn, task_id, dict(user))
            cached = self._idempotent_result(conn, actor_user_id, scope, idempotency_key, request)
            if cached is not None:
                return cached
            self._owned_active_task(conn, task_id, dict(user))
            attempt = self._latest_attempt(conn, task_id)
            if attempt is None:
                raise DomainConflictError("Task has no Attempt to control")
            now = _now()
            if action == "cancel" and attempt["status"] == "queued":
                cancelled = self._cancel_unstarted_dispatches_in_transaction(
                    conn, task_id=task_id, reason=reason or "cancelled", now=now
                )
                if str(attempt["attempt_id"]) in cancelled:
                    conn.execute(
                        """UPDATE tasks SET status = 'cancelled', updated_at = ?
                           WHERE task_id = ? AND latest_attempt_id = ?""",
                        (now, task_id, attempt["attempt_id"]),
                    )
                    result: dict[str, object] = {
                        "task_id": task_id,
                        "action": action,
                        "cancelled_attempt_ids": cancelled,
                        "status": "cancelled",
                    }
                else:
                    result = self._request_control_in_transaction(
                        conn,
                        task_id=task_id,
                        attempt_id=str(attempt["attempt_id"]),
                        action=action,
                        actor_user_id=actor_user_id,
                        idempotency_key=f"{scope}:{idempotency_key}",
                        request_hash=_request_hash(request),
                        reason=reason,
                        payload={"launch_state_uncertain": True},
                    )
            elif attempt["status"] in {"starting", "running", "paused"}:
                result = self._request_control_in_transaction(
                    conn,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    action=action,
                    actor_user_id=actor_user_id,
                    idempotency_key=f"{scope}:{idempotency_key}",
                    request_hash=_request_hash(request),
                    reason=reason,
                    payload={},
                )
            else:
                raise DomainConflictError("Task Attempt is not active")
            self._store_idempotency(conn, actor_user_id, scope, idempotency_key, request, result)
            self._audit(conn, actor_user_id, f"task.{action}_requested", "task", task_id)
            conn.commit()
            return result

    def _cancel_unstarted_dispatches_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        reason: str,
        now: str,
    ) -> list[str]:
        rows = conn.execute(
            """SELECT attempt_id FROM task_dispatch_outbox
               WHERE task_id = ?
                 AND (status = 'pending' OR (status = 'claimed' AND launch_state = 'none'))""",
            (task_id,),
        ).fetchall()
        attempt_ids = [str(row["attempt_id"]) for row in rows]
        if not attempt_ids:
            return []
        placeholders = ",".join("?" for _ in attempt_ids)
        conn.execute(
            f"""UPDATE task_dispatch_outbox
                 SET status = 'cancelled', cancel_reason = ?, cancelled_at = ?, updated_at = ?
                 WHERE attempt_id IN ({placeholders})
                   AND (status = 'pending' OR (status = 'claimed' AND launch_state = 'none'))""",
            (reason, now, now, *attempt_ids),
        )
        conn.execute(
            f"""UPDATE agent_task_attempts
                 SET status = 'cancelled', stop_reason = ?, finished_at = ?
                 WHERE attempt_id IN ({placeholders}) AND status = 'queued'""",
            (reason, now, *attempt_ids),
        )
        return attempt_ids

    @staticmethod
    def _terminal_attempt_statuses() -> frozenset[str]:
        return frozenset(
            {
                "succeeded",
                "failed",
                "cancelled",
                "stopped",
                "stopped_by_project_archive",
                "stopped_permission_revoked",
            }
        )

    def _ensure_no_started_attempt(self, conn: sqlite3.Connection, task_id: str) -> None:
        row = conn.execute(
            """SELECT 1 FROM agent_task_attempts
               WHERE task_id = ?
                 AND status IN ('starting', 'running', 'paused', 'launch_unknown')
               LIMIT 1""",
            (task_id,),
        ).fetchone()
        if row is not None:
            raise DomainConflictError("Task with a started Attempt cannot be moved")

    def _request_control_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        attempt_id: str,
        action: str,
        actor_user_id: str,
        idempotency_key: str | None,
        request_hash: str | None,
        reason: str | None,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        control_request_id = f"control-{uuid4().hex}"
        now = _now()
        try:
            conn.execute(
                """INSERT INTO task_attempt_control_requests (
                       control_request_id, task_id, attempt_id, action, status, actor_user_id,
                       idempotency_key, request_hash, reason, payload_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    control_request_id,
                    task_id,
                    attempt_id,
                    action,
                    actor_user_id,
                    idempotency_key,
                    request_hash,
                    reason,
                    _canonical_json(payload),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DomainConflictError(
                "Task control request conflicts with a prior request"
            ) from exc
        if action in {"cancel", "stop"}:
            conn.execute(
                """UPDATE agent_task_attempts
                   SET stop_requested_at = COALESCE(stop_requested_at, ?),
                       stop_requested_reason = COALESCE(stop_requested_reason, ?)
                   WHERE attempt_id = ?""",
                (now, reason or action, attempt_id),
            )
        return {
            "control_request_id": control_request_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "action": action,
            "status": "requested",
        }

    def _owned_active_task(
        self, conn: sqlite3.Connection, task_id: str, user: dict[str, object]
    ) -> sqlite3.Row:
        task = self._owned_task(conn, task_id, user)
        if task["archived_at"] is not None:
            raise DomainConflictError("Task is archived")
        project = conn.execute(
            "SELECT status FROM projects WHERE project_id = ?", (task["project_id"],)
        ).fetchone()
        if project is None or project["status"] != "active":
            raise DomainConflictError("Project is archived")
        return task

    @staticmethod
    def _owned_task(conn: sqlite3.Connection, task_id: str, user: dict[str, object]) -> sqlite3.Row:
        DomainAuthorizationService(conn).require_task_owner(task_id, user)
        task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            raise DomainNotFoundError(task_id)
        return task

    @staticmethod
    def _latest_attempt(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
        return conn.execute(
            """SELECT * FROM agent_task_attempts
               WHERE task_id = ? ORDER BY attempt_seq DESC LIMIT 1""",
            (task_id,),
        ).fetchone()

    @staticmethod
    def _relationship_id(source_task_id: str, target_task_id: str, relationship_type: str) -> str:
        return (
            f"{len(source_task_id)}:{source_task_id}{len(target_task_id)}:{target_task_id}"
            f"{len(relationship_type)}:{relationship_type}"
        )

    @staticmethod
    def _string_result(result: Mapping[str, object]) -> dict[str, str]:
        return {key: str(value) for key, value in result.items() if isinstance(value, str)}

    @staticmethod
    def _object_result(result: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in result.items()}

    def _writable_workspace(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        expected_environment_id: str | None,
    ) -> sqlite3.Row:
        project = conn.execute(
            "SELECT status FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise DomainNotFoundError(project_id)
        if project["status"] != "active":
            raise DomainConflictError("Project is archived")
        row = conn.execute(
            """SELECT workspace.environment_id, workspace.status AS workspace_status,
                      environment.status AS environment_status,
                      environment.owner_user_id AS environment_owner_user_id
               FROM workspaces AS workspace
               JOIN environments AS environment ON environment.environment_id = workspace.environment_id
               JOIN project_workspace_links AS link
                 ON link.project_id = ? AND link.workspace_id = workspace.workspace_id
                AND link.status = 'active'
               WHERE workspace.workspace_id = ?""",
            (project_id, workspace_id),
        ).fetchone()
        if row is None:
            raise DomainConflictError("Task Workspace must be an active Project link")
        if row["workspace_status"] != "active" or row["environment_status"] != "active":
            raise DomainConflictError("Task Workspace and Environment must be active")
        if expected_environment_id is not None and row["environment_id"] != expected_environment_id:
            raise DomainConflictError("Task environment must be derived from the Workspace")
        return row

    def _grant_version(
        self,
        *,
        environment_id: str,
        actor_user_id: str,
        environment_owner_user_id: object,
    ) -> int:
        if environment_owner_user_id == actor_user_id:
            return 0
        if not self._auth_db_path.is_file():
            raise DomainPermissionError("Environment grant database is unavailable")
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                row = conn.execute(
                    """SELECT grant_version FROM environment_access
                       WHERE environment_id = ? AND user_id = ? AND status = 'active'""",
                    (environment_id, actor_user_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DomainPermissionError("Environment grant cannot be read") from exc
        if row is None:
            raise DomainPermissionError("Active Environment grant is required")
        return int(row[0])

    @staticmethod
    def _idempotent_result(
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        idempotency_key: str,
        request: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not idempotency_key:
            raise DomainConflictError("Idempotency-Key is required")
        row = conn.execute(
            """SELECT request_hash, response_json FROM domain_idempotency_requests
               WHERE actor_user_id = ? AND scope = ? AND idempotency_key = ?""",
            (actor_user_id, scope, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != _request_hash(request):
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        try:
            result = json.loads(str(row["response_json"]))
        except json.JSONDecodeError as exc:
            raise DomainConflictError("Stored idempotency response is invalid") from exc
        if not isinstance(result, dict):
            raise DomainConflictError("Stored idempotency response is invalid")
        return {str(key): value for key, value in result.items()}

    @staticmethod
    def _store_idempotency(
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        idempotency_key: str,
        request: Mapping[str, object],
        result: Mapping[str, object],
    ) -> None:
        if not idempotency_key:
            raise DomainConflictError("Idempotency-Key is required")
        conn.execute(
            """INSERT INTO domain_idempotency_requests (
                   actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                actor_user_id,
                scope,
                idempotency_key,
                _request_hash(request),
                _canonical_json(result),
                _now(),
            ),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
    ) -> None:
        conn.execute(
            """INSERT INTO domain_audit_events
               (event_id, actor_id, event_type, subject_type, subject_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )

"""Durable Literature-to-Task intent saga.

The Literature and domain control planes deliberately remain separate SQLite
databases.  This service therefore records a literature-side intent and a
durable work item first, invokes the idempotent Task application service, then
persists the Task link.  A retry can start at any point in that sequence
without creating another Task.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain import DomainAuthorizationService, TaskApplicationService
from ainrf.domain.service import (
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
)
from ainrf.domain_telemetry import (
    record_durable_idempotency_event,
    record_literature_saga_event,
    record_permission_denied,
)
from ainrf.domain_control import (
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    MaintenanceModeError,
)


_DEFAULT_PRESET = "structured-research-default"
_DEFAULT_LEASE_SECONDS = 120


class ResearchTaskPaperNotFoundError(LookupError):
    """The paper is not visible to the requesting Literature user."""


class ResearchTaskWorkspaceRequiredError(ValueError):
    """No owned executable Workspace can be selected for a new Task."""


class ResearchTaskIdempotencyConflictError(ValueError):
    """A Literature intent key was reused with a changed request."""


class ResearchTaskPresetError(ValueError):
    """The constrained Literature Task preset is not recognized."""


class ResearchTaskLeaseLostError(RuntimeError):
    """A worker may no longer mutate the intent it previously claimed."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _request_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


class LiteratureTaskSagaService:
    """Coordinate a user-visible Literature research Task without a 2PC.

    ``recover_intent`` is intentionally public: the domain worker can invoke
    it for a durable ``literature_work_items`` record after API process loss.
    It never uses a process-local queue or accepts an externally supplied Task
    ID.
    """

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "literature.sqlite3"
        self._domain_db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._artifact_sha = artifact_sha
        self._maintenance = DomainMaintenanceService(state_root)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "literature")
        self._tasks = TaskApplicationService(state_root, artifact_sha=artifact_sha)
        self._cutover = DomainCutoverController(state_root)

    @property
    def state_root(self) -> Path:
        return self._state_root

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def _record_permission_denial(
        self,
        *,
        resource: str,
        reason: str,
        user_id: str | None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        environment_id: str | None = None,
    ) -> None:
        """Record a bounded saga authorization failure in shared telemetry."""

        record_permission_denied(
            resource=resource,
            reason=reason,
            user_id=user_id,
            project_id=project_id,
            workspace_id=workspace_id,
            environment_id=environment_id,
            state_root=self._state_root,
        )

    def v2_ready(self) -> bool:
        """Whether this exact saga instance can safely create v2 Tasks.

        A constructed object alone is not a capability: it must carry the
        immutable artifact SHA, observe a committed cutover fuse, and retain
        the durable Literature intent/work/outbox schema that recovery needs.
        """

        if not self._artifact_sha:
            return False
        try:
            self._cutover.assert_v2_writable(artifact_sha=self._artifact_sha)
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name IN (
                        'literature_research_task_intents',
                        'literature_work_items',
                        'literature_outbox'
                    )
                    """
                ).fetchall()
        except (DomainCutoverError, sqlite3.Error):
            return False
        return {str(row["name"]) for row in rows} == {
            "literature_research_task_intents",
            "literature_work_items",
            "literature_outbox",
        }

    def _require_v2_writable(self) -> None:
        """Fail closed before a saga can cross into the Task write model.

        HTTP routes are not the only callers: durable Literature work may be
        recovered by a process that imports this service directly.  The
        cutover fuse therefore belongs at the saga boundary as well, with the
        exact immutable artifact binding used by the domain worker.
        """

        if self._maintenance.status().is_active:
            raise MaintenanceModeError("Literature research Tasks are paused for maintenance")
        if not self._artifact_sha:
            raise DomainCutoverError(
                "Literature research Tasks require the committed v2 artifact SHA"
            )
        self._cutover.assert_v2_writable(artifact_sha=self._artifact_sha)

    def _assert_maintenance_unchanged(self) -> None:
        """Reject a Literature-side commit that crossed into maintenance.

        The Literature and domain stores intentionally have no distributed
        transaction.  Re-checking immediately before each local commit keeps
        a request that began in the previous epoch from silently persisting a
        new intent after maintenance starts.
        """

        if self._maintenance.status().is_active:
            raise MaintenanceModeError("Literature research Tasks are paused for maintenance")

    # ------------------------------------------------------------------
    # Public intent API
    # ------------------------------------------------------------------
    def create_research_task(
        self,
        user: Mapping[str, object],
        *,
        paper_id: str,
        project_id: str,
        workspace_id: str | None,
        task_preset: str = _DEFAULT_PRESET,
        title: str | None = None,
        idempotency_key: str,
        subscription_id: str | None = None,
    ) -> dict[str, object]:
        """Create or recover one durable research-Task intent.

        Validation that is independent of Task creation happens before the
        intent is committed.  The Task itself is intentionally not part of the
        Literature transaction: the deterministic Task idempotency key makes
        retries safe across the database boundary.
        """

        self._require_v2_writable()
        actor = self._actor(user)
        normalized_project_id = project_id.strip()
        normalized_workspace_id = workspace_id.strip() if workspace_id is not None else None
        normalized_preset = task_preset.strip() or _DEFAULT_PRESET
        normalized_title = title.strip() if title is not None else None
        normalized_key = idempotency_key.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        if not normalized_key:
            raise ValueError("Idempotency-Key is required")
        if workspace_id is not None and not normalized_workspace_id:
            raise ValueError("workspace_id must not be empty")

        # The request hash describes the public request, not a transient
        # Primary Workspace, grant, or generated prompt.  Check an existing
        # intent immediately after paper visibility so a timeout retry remains
        # stable even if a Project is subsequently archived or a grant changes.
        request_input: dict[str, object] = {
            "paper_id": paper_id,
            "subscription_id": subscription_id,
            "project_id": normalized_project_id,
            "workspace_id": normalized_workspace_id,
            "task_preset": normalized_preset,
            "title": normalized_title,
        }
        request_hash = _request_hash(request_input)
        paper = self._paper_for_user(actor["id"], paper_id, subscription_id)
        existing = self._existing_intent(actor["id"], paper_id, normalized_key)
        if existing is not None:
            existing_response = self._intent_dict(existing)
            if str(existing["request_hash"]) != request_hash:
                record_durable_idempotency_event(
                    "conflict",
                    actor_user_id=actor["id"],
                    scope="literature.research_task",
                    idempotency_key=normalized_key,
                    request=request_input,
                    response=existing_response,
                )
                raise ResearchTaskIdempotencyConflictError(
                    "Idempotency-Key was already used for a different research Task request"
                )
            record_durable_idempotency_event(
                "reused",
                actor_user_id=actor["id"],
                scope="literature.research_task",
                idempotency_key=normalized_key,
                request=request_input,
                response=existing_response,
            )
            return self.recover_intent(
                str(existing["intent_id"]),
                worker_id="literature-api",
                raise_domain_errors=True,
            )

        researcher_type, harness_engine = self._preset_config(normalized_preset)
        self._require_project_editor(normalized_project_id, actor)
        selected_workspace = normalized_workspace_id or self._owned_executable_primary(
            normalized_project_id, actor
        )
        self._require_owned_executable_workspace(normalized_project_id, selected_workspace, actor)

        task_title = normalized_title or f"Literature: {paper['title']}"
        prompt = self._research_prompt(
            paper_id=paper_id,
            title=paper["title"],
            abstract=paper["abstract"],
            task_preset=normalized_preset,
        )
        task_request: dict[str, object] = {
            "paper_id": paper_id,
            "subscription_id": subscription_id,
            "project_id": normalized_project_id,
            "workspace_id": selected_workspace,
            "task_preset": normalized_preset,
            "title": task_title,
            "prompt": prompt,
            "researcher_type": researcher_type,
            "harness_engine": harness_engine,
            "actor_role": actor["role"],
            "request_input": request_input,
        }

        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    """
                    SELECT * FROM literature_research_task_intents
                    WHERE user_id = ? AND paper_id = ? AND idempotency_key = ?
                    """,
                    (actor["id"], paper_id, normalized_key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_hash"]) != request_hash:
                        record_durable_idempotency_event(
                            "conflict",
                            actor_user_id=actor["id"],
                            scope="literature.research_task",
                            idempotency_key=normalized_key,
                            request=request_input,
                            response=self._intent_dict(existing),
                        )
                        raise ResearchTaskIdempotencyConflictError(
                            "Idempotency-Key was already used for a different research Task request"
                        )
                    record_durable_idempotency_event(
                        "reused",
                        actor_user_id=actor["id"],
                        scope="literature.research_task",
                        idempotency_key=normalized_key,
                        request=request_input,
                        response=self._intent_dict(existing),
                    )
                    intent_id = str(existing["intent_id"])
                else:
                    intent_id = _identifier("literature-intent")
                    task_idempotency_key = self._task_idempotency_key(
                        user_id=actor["id"], paper_id=paper_id, idempotency_key=normalized_key
                    )
                    work_item_id = _identifier("literature-work")
                    now = _now()
                    conn.execute(
                        """
                        INSERT INTO literature_work_items (
                            work_item_id, kind, idempotency_key, status, payload_json,
                            available_at, created_at, updated_at
                        ) VALUES (?, 'research_task', ?, 'queued', ?, ?, ?, ?)
                        """,
                        (
                            work_item_id,
                            f"research-task:{intent_id}",
                            _canonical_json({"intent_id": intent_id}),
                            now,
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO literature_outbox (outbox_id, work_item_id, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (_identifier("literature-outbox"), work_item_id, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO literature_research_task_intents (
                            intent_id, user_id, paper_id, subscription_id, project_id, workspace_id,
                            actor_role, task_preset, title, request_input_json, request_hash,
                            idempotency_key, task_idempotency_key, status, work_item_id, attempt_count,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)
                        """,
                        (
                            intent_id,
                            actor["id"],
                            paper_id,
                            subscription_id,
                            normalized_project_id,
                            selected_workspace,
                            actor["role"],
                            normalized_preset,
                            task_title,
                            _canonical_json(task_request),
                            request_hash,
                            normalized_key,
                            task_idempotency_key,
                            work_item_id,
                            now,
                            now,
                        ),
                    )
                self._assert_maintenance_unchanged()
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        # The API path takes one synchronous recovery pass for a fast success
        # response.  If this process dies here, the work item and intent are
        # already durable and the domain worker can continue it.
        record_literature_saga_event(
            "intent_created",
            user_id=actor["id"],
            project_id=normalized_project_id,
            workspace_id=selected_workspace,
            intent_id=intent_id,
            idempotency_key=normalized_key,
        )
        return self.recover_intent(
            intent_id,
            worker_id="literature-api",
            raise_domain_errors=True,
        )

    def get_research_task(
        self, user: Mapping[str, object], *, paper_id: str, idempotency_key: str
    ) -> dict[str, object]:
        actor = self._actor(user)
        self._paper_for_user(actor["id"], paper_id, subscription_id=None)
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM literature_research_task_intents
                WHERE user_id = ? AND paper_id = ? AND idempotency_key = ?
                """,
                (actor["id"], paper_id, idempotency_key),
            ).fetchone()
        if row is None:
            raise ResearchTaskPaperNotFoundError("Research Task intent not found")
        return self._intent_dict(row)

    def list_research_tasks(
        self, user: Mapping[str, object], *, paper_id: str
    ) -> list[dict[str, object]]:
        actor = self._actor(user)
        self._paper_for_user(actor["id"], paper_id, subscription_id=None)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM literature_research_task_intents
                WHERE user_id = ? AND paper_id = ?
                ORDER BY created_at DESC, intent_id DESC
                """,
                (actor["id"], paper_id),
            ).fetchall()
        return [self._intent_dict(row) for row in rows]

    def convert(
        self,
        user: Mapping[str, object],
        *,
        paper_id: str,
        subscription_id: str,
        project_id: str,
        workspace_id: str | None,
        idempotency_key: str | None = None,
        task_preset: str = _DEFAULT_PRESET,
        title: str | None = None,
    ) -> dict[str, object]:
        """Deprecated proxy retained for the former ``/convert`` route.

        The old route formerly accepted a caller-chosen ``task_id``.  This
        method has no such parameter and only delegates to the validated
        intent contract.
        """

        key = idempotency_key or (
            f"legacy-convert:{subscription_id}:{paper_id}:{project_id}:{workspace_id or ''}"
        )
        return self.create_research_task(
            user,
            paper_id=paper_id,
            subscription_id=subscription_id,
            project_id=project_id,
            workspace_id=workspace_id,
            task_preset=task_preset,
            title=title,
            idempotency_key=key,
        )

    # ------------------------------------------------------------------
    # Durable recovery API for the domain worker / Literature work runner
    # ------------------------------------------------------------------
    def recover_pending(self, *, worker_id: str, limit: int = 100) -> list[dict[str, object]]:
        """Recover due pending, link-write, and retryable outbox intents.

        The method follows the durable Literature work/outbox relation rather
        than a process-local queue.  It deliberately also picks up an intent
        whose broker delivery was marked published before a worker crashed;
        ``published`` means the message was handed off, not that the saga is
        complete.  It is safe for two workers: each caller holds an intent
        lease and the underlying Task writer has its own idempotency fence.
        """

        self._require_v2_writable()
        if limit <= 0:
            raise ValueError("limit must be positive")
        now = _now()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT intent.intent_id
                FROM literature_research_task_intents AS intent
                JOIN literature_work_items AS work ON work.work_item_id = intent.work_item_id
                JOIN literature_outbox AS outbox ON outbox.work_item_id = intent.work_item_id
                WHERE (
                    intent.status = 'pending'
                    OR (
                        intent.status = 'task_created'
                        AND (intent.lease_expires_at IS NULL OR intent.lease_expires_at <= ?)
                    )
                    OR (
                        intent.status = 'retryable_failed'
                        AND (intent.next_retry_at IS NULL OR intent.next_retry_at <= ?)
                    )
                    OR (
                        intent.status = 'creating_task'
                        AND (intent.lease_expires_at IS NULL OR intent.lease_expires_at <= ?)
                    )
                )
                  AND work.kind = 'research_task'
                  AND work.status != 'completed'
                  AND outbox.status IN ('pending', 'published')
                ORDER BY intent.created_at, intent.intent_id
                LIMIT ?
                """,
                (now, now, now, limit),
            ).fetchall()
        return [self.recover_intent(str(row["intent_id"]), worker_id=worker_id) for row in rows]

    def recover_work_item(self, work_item_id: str, *, worker_id: str) -> dict[str, object] | None:
        """Recover the intent named by a durable Literature work item."""

        self._require_v2_writable()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT intent_id FROM literature_research_task_intents
                WHERE work_item_id = ?
                """,
                (work_item_id,),
            ).fetchone()
        if row is None:
            return None
        return self.recover_intent(str(row["intent_id"]), worker_id=worker_id)

    def recover_intent(
        self,
        intent_id: str,
        *,
        worker_id: str,
        raise_domain_errors: bool = False,
    ) -> dict[str, object]:
        """Resume one intent, retaining the same Task idempotency key.

        A user-facing initial request needs the normal Task-domain 403/409/503
        semantics.  Background recovery keeps the intent retryable instead,
        because it has no HTTP caller to present that synchronous outcome to.
        """

        self._require_v2_writable()
        claimed = self._claim_intent(intent_id, worker_id)
        if claimed is None:
            return self._intent_by_id(intent_id)
        if str(claimed["status"]) == "completed":
            return self._intent_dict(claimed)
        if claimed["task_id"] is not None:
            try:
                self._persist_completed_link(intent_id, worker_id, str(claimed["task_id"]))
            except Exception as exc:
                self._record_retryable_failure(intent_id, worker_id, str(exc))
            return self._intent_by_id(intent_id)

        try:
            request = self._request_from_row(claimed)
            self._heartbeat_intent(intent_id, worker_id)
            recovered_task_id = self._task_id_from_domain_idempotency(claimed)
            if recovered_task_id is not None:
                self._record_task_created(intent_id, worker_id, recovered_task_id)
                self._persist_completed_link(intent_id, worker_id, recovered_task_id)
                return self._intent_by_id(intent_id)
            current_actor = self._current_active_actor(str(claimed["user_id"]))
            task = self._tasks.create_task(
                current_actor,
                project_id=str(request["project_id"]),
                workspace_id=str(request["workspace_id"]),
                title=str(request["title"]),
                prompt=str(request["prompt"]),
                researcher_type=str(request["researcher_type"]),
                harness_engine=str(request["harness_engine"]),
                idempotency_key=str(claimed["task_idempotency_key"]),
            )
            task_id = task.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError("Task application service returned no task_id")
            self._record_task_created(intent_id, worker_id, task_id)
            self._persist_completed_link(intent_id, worker_id, task_id)
        except Exception as exc:
            self._record_retryable_failure(intent_id, worker_id, str(exc))
            if raise_domain_errors and isinstance(
                exc,
                (
                    DomainConflictError,
                    DomainNotFoundError,
                    DomainPermissionError,
                    DomainCutoverError,
                    MaintenanceModeError,
                ),
            ):
                raise
        return self._intent_by_id(intent_id)

    # ------------------------------------------------------------------
    # Domain/Literature authorization and request normalization
    # ------------------------------------------------------------------
    def _actor(self, user: Mapping[str, object]) -> dict[str, str]:
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            self._record_permission_denial(
                resource="literature", reason="authenticated_user_required", user_id=None
            )
            raise DomainPermissionError("Authenticated user ID is required")
        role = user.get("role")
        return {"id": user_id, "role": role if isinstance(role, str) and role else "member"}

    def _current_active_actor(self, user_id: str) -> dict[str, str]:
        """Load the current durable principal before a recovery creates a Task.

        ``actor_role`` in the Literature intent is retained as an audit record,
        not an authorization credential.  A retry can happen well after an
        administrator has demoted or disabled the original requester, so it
        must fail closed rather than replaying the stale role.
        """

        if not user_id:
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=None
            )
            raise DomainPermissionError("attention_required: Literature actor is invalid")
        if user_id == "api-key-user":
            # API keys deliberately authenticate as one restricted compatibility
            # principal rather than as a row in auth.sqlite3.  There is no
            # persisted admin capability to replay here: this fixed role can
            # only act through the Project membership/ownership and
            # Environment grant already checked by TaskApplicationService.
            # Keep it aligned with DomainService's explicit API-key principal
            # exception instead of treating an absent auth row as a bypass.
            return {"id": user_id, "role": "user"}
        if not self._auth_db_path.is_file():
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=user_id
            )
            raise DomainPermissionError(
                "attention_required: Literature actor identity is unavailable"
            )
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                row = conn.execute(
                    "SELECT id, role, status FROM users WHERE id = ?", (user_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=user_id
            )
            raise DomainPermissionError(
                "attention_required: Literature actor identity cannot be read"
            ) from exc
        if row is None:
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=user_id
            )
            raise DomainPermissionError("attention_required: Literature actor is unavailable")
        role = row[1]
        if row[2] != "active":
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=user_id
            )
            raise DomainPermissionError("attention_required: Literature actor is inactive")
        if not isinstance(role, str) or role not in {"admin", "member"}:
            self._record_permission_denial(
                resource="literature", reason="actor_unavailable", user_id=user_id
            )
            raise DomainPermissionError("attention_required: Literature actor role is invalid")
        return {"id": user_id, "role": role}

    @staticmethod
    def _preset_config(task_preset: str) -> tuple[str, str]:
        presets = {
            "raw-prompt": ("vanilla", "claude-code"),
            "structured-research-default": ("aris-researcher", "claude-code"),
            "reproduce-baseline-default": ("vanilla", "codex-app-server"),
            "overview": ("vanilla", "claude-code"),
        }
        try:
            return presets[task_preset]
        except KeyError as exc:
            raise ResearchTaskPresetError(
                f"Unsupported literature task_preset: {task_preset}"
            ) from exc

    def _paper_for_user(
        self, user_id: str, paper_id: str, subscription_id: str | None
    ) -> dict[str, str]:
        with closing(self._connect()) as conn:
            if subscription_id is not None:
                row = conn.execute(
                    """
                    SELECT p.title, p.abstract
                    FROM literature_papers AS p
                    JOIN literature_subscription_papers AS sp ON sp.paper_id = p.paper_id
                    JOIN literature_subscriptions AS s ON s.subscription_id = sp.subscription_id
                    WHERE p.paper_id = ? AND sp.subscription_id = ? AND s.user_id = ?
                    """,
                    (paper_id, subscription_id, user_id),
                ).fetchone()
                if row is not None:
                    return {"title": str(row["title"]), "abstract": str(row["abstract"])}
            row = conn.execute(
                """
                SELECT cp.title, cp.abstract
                FROM literature_catalog_papers AS cp
                JOIN literature_user_paper_states AS state ON state.paper_id = cp.paper_id
                WHERE cp.paper_id = ? AND state.user_id = ?
                """,
                (paper_id, user_id),
            ).fetchone()
            if row is not None:
                return {"title": str(row["title"]), "abstract": str(row["abstract"])}
            row = conn.execute(
                """
                SELECT p.title, p.abstract
                FROM literature_papers AS p
                JOIN literature_subscription_papers AS sp ON sp.paper_id = p.paper_id
                JOIN literature_subscriptions AS s ON s.subscription_id = sp.subscription_id
                WHERE p.paper_id = ? AND s.user_id = ?
                LIMIT 1
                """,
                (paper_id, user_id),
            ).fetchone()
            known_paper = None
            if row is None:
                # Preserve the public 404 for both an absent paper and one
                # that belongs to another user's Literature scope.  This
                # private existence probe is only used for bounded telemetry.
                known_paper = conn.execute(
                    """
                    SELECT 1 FROM literature_catalog_papers WHERE paper_id = ?
                    UNION ALL
                    SELECT 1 FROM literature_papers WHERE paper_id = ?
                    LIMIT 1
                    """,
                    (paper_id, paper_id),
                ).fetchone()
        if row is None:
            if known_paper is not None:
                self._record_permission_denial(
                    resource="literature",
                    reason="not_visible",
                    user_id=user_id,
                )
            raise ResearchTaskPaperNotFoundError("Paper not found")
        return {"title": str(row["title"]), "abstract": str(row["abstract"])}

    def _require_project_editor(self, project_id: str, actor: Mapping[str, str]) -> None:
        with closing(connect(self._domain_db_path)) as conn:
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(actor))
            project = conn.execute(
                "SELECT status FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if project is None:
            raise DomainNotFoundError(project_id)
        if str(project["status"]) != "active":
            raise DomainConflictError("Project is archived")

    def _owned_executable_primary(self, project_id: str, actor: Mapping[str, str]) -> str:
        with closing(connect(self._domain_db_path)) as conn:
            row = conn.execute(
                """
                SELECT workspace.workspace_id
                FROM project_workspace_links AS link
                JOIN workspaces AS workspace ON workspace.workspace_id = link.workspace_id
                JOIN environments AS environment ON environment.environment_id = workspace.environment_id
                WHERE link.project_id = ? AND link.status = 'active' AND link.is_primary = 1
                  AND workspace.status = 'active' AND environment.status = 'active'
                  AND workspace.owner_user_id = ?
                """,
                (project_id, actor["id"]),
            ).fetchone()
        if row is None:
            raise ResearchTaskWorkspaceRequiredError(
                "Select or link an owned executable Primary Workspace before creating a research Task"
            )
        workspace_id = str(row["workspace_id"])
        try:
            self._require_owned_executable_workspace(project_id, workspace_id, actor)
        except (DomainConflictError, DomainPermissionError, DomainNotFoundError) as exc:
            raise ResearchTaskWorkspaceRequiredError(
                "Select or link an owned executable Primary Workspace before creating a research Task"
            ) from exc
        return workspace_id

    def _require_owned_executable_workspace(
        self, project_id: str, workspace_id: str, actor: Mapping[str, str]
    ) -> None:
        with closing(connect(self._domain_db_path)) as conn:
            row = conn.execute(
                """
                SELECT workspace.owner_user_id, workspace.status AS workspace_status,
                       environment.environment_id, environment.owner_user_id AS environment_owner_user_id,
                       environment.status AS environment_status, link.status AS link_status
                FROM workspaces AS workspace
                JOIN environments AS environment ON environment.environment_id = workspace.environment_id
                LEFT JOIN project_workspace_links AS link
                  ON link.workspace_id = workspace.workspace_id AND link.project_id = ?
                WHERE workspace.workspace_id = ?
                """,
                (project_id, workspace_id),
            ).fetchone()
        if row is None:
            self._record_permission_denial(
                resource="workspace",
                reason="not_visible",
                user_id=actor["id"],
                project_id=project_id,
                workspace_id=workspace_id,
            )
            raise DomainNotFoundError(workspace_id)
        if str(row["owner_user_id"]) != actor["id"]:
            self._record_permission_denial(
                resource="workspace",
                reason="owner_required",
                user_id=actor["id"],
                project_id=project_id,
                workspace_id=workspace_id,
            )
            raise DomainPermissionError("Research Tasks require an owned Workspace")
        if (
            row["link_status"] != "active"
            or row["workspace_status"] != "active"
            or row["environment_status"] != "active"
        ):
            raise DomainConflictError("Research Task Workspace must be an active Project link")
        if not self._has_environment_grant(
            environment_id=str(row["environment_id"]),
            actor_user_id=actor["id"],
            environment_owner_user_id=row["environment_owner_user_id"],
        ):
            self._record_permission_denial(
                resource="environment",
                reason="environment_grant_required",
                user_id=actor["id"],
                project_id=project_id,
                workspace_id=workspace_id,
                environment_id=str(row["environment_id"]),
            )
            raise DomainPermissionError("Active Environment grant is required")

    def _has_environment_grant(
        self,
        *,
        environment_id: str,
        actor_user_id: str,
        environment_owner_user_id: object,
    ) -> bool:
        if environment_owner_user_id == actor_user_id:
            return True
        if not self._auth_db_path.is_file():
            return False
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                row = conn.execute(
                    """
                    SELECT 1 FROM environment_access
                    WHERE environment_id = ? AND user_id = ? AND status = 'active'
                    """,
                    (environment_id, actor_user_id),
                ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None

    @staticmethod
    def _research_prompt(*, paper_id: str, title: str, abstract: str, task_preset: str) -> str:
        arxiv_id = paper_id.removeprefix("arxiv:")
        source = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
        if task_preset == "overview":
            return (
                "Write a concise research overview for this paper.\n\n"
                f"Title: {title}\n\nAbstract:\n{abstract}\n\nSource: {source}"
            )
        if task_preset == "reproduce-baseline-default":
            return (
                "Assess and reproduce the baseline described by this paper.\n\n"
                f"Title: {title}\n\nAbstract:\n{abstract}\n\nSource: {source}"
            )
        return (
            "Review and extend this paper with a structured research report.\n\n"
            f"Title: {title}\n\nAbstract:\n{abstract}\n\nSource: {source}"
        )

    @staticmethod
    def _task_idempotency_key(*, user_id: str, paper_id: str, idempotency_key: str) -> str:
        value = "\x1f".join((user_id, paper_id, idempotency_key)).encode("utf-8")
        return f"literature-research-task:{hashlib.sha256(value).hexdigest()}"

    # ------------------------------------------------------------------
    # Intent lease and state transitions
    # ------------------------------------------------------------------
    def _claim_intent(self, intent_id: str, worker_id: str) -> sqlite3.Row | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        now = datetime.now(UTC)
        lease_expires_at = (now + timedelta(seconds=_DEFAULT_LEASE_SECONDS)).isoformat()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM literature_research_task_intents WHERE intent_id = ?",
                    (intent_id,),
                ).fetchone()
                if row is None:
                    raise ResearchTaskPaperNotFoundError("Research Task intent not found")
                if str(row["status"]) == "completed":
                    conn.commit()
                    return row
                status = str(row["status"])
                active_lease = row["lease_expires_at"]
                if (
                    status in {"creating_task", "task_created"}
                    and isinstance(active_lease, str)
                    and active_lease > now.isoformat()
                    and row["lease_owner"] != worker_id
                ):
                    conn.commit()
                    return None
                if status == "retryable_failed":
                    retry_at = row["next_retry_at"]
                    if isinstance(retry_at, str) and retry_at > now.isoformat():
                        conn.commit()
                        return None
                new_status = "task_created" if status == "task_created" else "creating_task"
                lease_clause = ""
                lease_params: tuple[object, ...] = ()
                if status in {"creating_task", "task_created"}:
                    lease_clause = " AND (lease_expires_at IS NULL OR lease_expires_at <= ? OR lease_owner = ?)"
                    lease_params = (now.isoformat(), worker_id)
                elif status == "retryable_failed":
                    lease_clause = " AND (next_retry_at IS NULL OR next_retry_at <= ?)"
                    lease_params = (now.isoformat(),)
                cursor = conn.execute(
                    """
                    UPDATE literature_research_task_intents
                    SET status = ?, lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                        attempt_count = attempt_count + 1, next_retry_at = NULL, updated_at = ?
                    WHERE intent_id = ? AND status = ?
                    """
                    + lease_clause,
                    (
                        new_status,
                        worker_id,
                        lease_expires_at,
                        now.isoformat(),
                        now.isoformat(),
                        intent_id,
                        status,
                        *lease_params,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.commit()
                    return None
                conn.execute(
                    """
                    UPDATE literature_work_items
                    SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                        attempt_count = attempt_count + 1, updated_at = ?
                    WHERE work_item_id = ? AND status != 'completed'
                    """,
                    (worker_id, lease_expires_at, now.isoformat(), row["work_item_id"]),
                )
                claimed = conn.execute(
                    "SELECT * FROM literature_research_task_intents WHERE intent_id = ?",
                    (intent_id,),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        assert claimed is not None
        return claimed

    def _heartbeat_intent(self, intent_id: str, worker_id: str) -> None:
        now = datetime.now(UTC)
        lease_expires_at = (now + timedelta(seconds=_DEFAULT_LEASE_SECONDS)).isoformat()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE literature_research_task_intents
                SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE intent_id = ? AND lease_owner = ? AND status IN ('creating_task', 'task_created')
                """,
                (now.isoformat(), lease_expires_at, now.isoformat(), intent_id, worker_id),
            )
        if cursor.rowcount != 1:
            raise ResearchTaskLeaseLostError(
                "Research Task intent lease was lost before Task creation"
            )

    def _record_task_created(self, intent_id: str, worker_id: str, task_id: str) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT task_id, status FROM literature_research_task_intents WHERE intent_id = ?",
                    (intent_id,),
                ).fetchone()
                if row is None:
                    raise ResearchTaskPaperNotFoundError("Research Task intent not found")
                existing_task_id = row["task_id"]
                if existing_task_id is not None and str(existing_task_id) != task_id:
                    raise RuntimeError("Research Task intent resolved to conflicting Task IDs")
                if str(row["status"]) == "completed":
                    conn.commit()
                    return
                cursor = conn.execute(
                    """
                    UPDATE literature_research_task_intents
                    SET task_id = ?, status = 'task_created', last_error = NULL,
                        heartbeat_at = ?, updated_at = ?
                    WHERE intent_id = ? AND lease_owner = ?
                    """,
                    (task_id, now, now, intent_id, worker_id),
                )
                if cursor.rowcount != 1:
                    raise ResearchTaskLeaseLostError(
                        "Research Task intent lease was lost before link checkpoint"
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        record_literature_saga_event(
            "task_created",
            intent_id=intent_id,
            task_id=task_id,
        )

    def _persist_completed_link(self, intent_id: str, worker_id: str, task_id: str) -> None:
        """Write the Literature link after a Task exists.

        Keeping this method separate from ``_record_task_created`` is
        intentional: a crash or SQLite error between them is represented as
        ``task_created`` and resumed without asking the Task service to create
        another Task.
        """

        now = _now()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM literature_research_task_intents WHERE intent_id = ?",
                    (intent_id,),
                ).fetchone()
                if row is None:
                    raise ResearchTaskPaperNotFoundError("Research Task intent not found")
                if row["task_id"] is not None and str(row["task_id"]) != task_id:
                    raise RuntimeError("Research Task link points at a different Task")
                if str(row["status"]) == "completed":
                    conn.commit()
                    return
                cursor = conn.execute(
                    """
                    UPDATE literature_research_task_intents
                    SET task_id = ?, status = 'completed', completed_at = ?, last_error = NULL,
                        lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = ?,
                        next_retry_at = NULL, updated_at = ?
                    WHERE intent_id = ? AND lease_owner = ?
                    """,
                    (task_id, now, now, now, intent_id, worker_id),
                )
                if cursor.rowcount != 1:
                    raise ResearchTaskLeaseLostError(
                        "Research Task intent lease was lost before link completion"
                    )
                if row["subscription_id"] is not None:
                    conn.execute(
                        """
                        UPDATE literature_subscription_papers
                        SET is_converted_to_task = 1, task_id = ?
                        WHERE subscription_id = ? AND paper_id = ?
                        """,
                        (task_id, row["subscription_id"], row["paper_id"]),
                    )
                catalog_row = conn.execute(
                    "SELECT 1 FROM literature_catalog_papers WHERE paper_id = ?", (row["paper_id"],)
                ).fetchone()
                if catalog_row is not None:
                    conn.execute(
                        """
                        INSERT INTO literature_research_task_links (
                            link_id, user_id, paper_id, task_id, idempotency_key, status,
                            payload_json, created_at, completed_at, last_error
                        ) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, NULL)
                        ON CONFLICT(idempotency_key) DO UPDATE SET
                            task_id = excluded.task_id, status = 'completed',
                            completed_at = excluded.completed_at, last_error = NULL
                        """,
                        (
                            f"research-link:{intent_id}",
                            row["user_id"],
                            row["paper_id"],
                            task_id,
                            row["task_idempotency_key"],
                            row["request_input_json"],
                            row["created_at"],
                            now,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE literature_work_items
                    SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL,
                        last_error = NULL, updated_at = ?
                    WHERE work_item_id = ?
                    """,
                    (now, row["work_item_id"]),
                )
                # A synchronous API recovery has already delivered the work
                # to its durable consumer.  Marking the outbox published keeps
                # a later broker scan from re-enqueueing a completed intent.
                conn.execute(
                    """
                    UPDATE literature_outbox
                    SET status = 'published', published_at = ?, last_error = NULL
                    WHERE work_item_id = ?
                    """,
                    (now, row["work_item_id"]),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        record_literature_saga_event(
            "completed",
            user_id=str(row["user_id"]),
            project_id=str(row["project_id"]),
            workspace_id=str(row["workspace_id"]),
            task_id=task_id,
            intent_id=intent_id,
            idempotency_key=str(row["idempotency_key"]),
        )

    def _record_retryable_failure(self, intent_id: str, worker_id: str, error: str) -> None:
        now = datetime.now(UTC)
        retry_at = (now + timedelta(seconds=30)).isoformat()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """
                    SELECT work_item_id, status, lease_owner
                    FROM literature_research_task_intents
                    WHERE intent_id = ?
                    """,
                    (intent_id,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return
                if str(row["status"]) == "completed" or row["lease_owner"] != worker_id:
                    conn.commit()
                    return
                cursor = conn.execute(
                    """
                    UPDATE literature_research_task_intents
                    SET status = 'retryable_failed', last_error = ?, next_retry_at = ?,
                        lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = ?, updated_at = ?
                    WHERE intent_id = ? AND lease_owner = ?
                    """,
                    (
                        error[:1000],
                        retry_at,
                        now.isoformat(),
                        now.isoformat(),
                        intent_id,
                        worker_id,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.commit()
                    return
                conn.execute(
                    """
                    UPDATE literature_work_items
                    SET status = 'retrying', available_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, last_error = ?, updated_at = ?
                    WHERE work_item_id = ? AND status != 'completed'
                    """,
                    (retry_at, error[:1000], now.isoformat(), row["work_item_id"]),
                )
                conn.execute(
                    """
                    UPDATE literature_outbox SET status = 'pending', last_error = ?
                    WHERE work_item_id = ?
                    """,
                    (error[:1000], row["work_item_id"]),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        record_literature_saga_event("retryable_failure", intent_id=intent_id)

    def _intent_by_id(self, intent_id: str) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM literature_research_task_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        if row is None:
            raise ResearchTaskPaperNotFoundError("Research Task intent not found")
        return self._intent_dict(row)

    def _existing_intent(
        self, user_id: str, paper_id: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                """
                SELECT * FROM literature_research_task_intents
                WHERE user_id = ? AND paper_id = ? AND idempotency_key = ?
                """,
                (user_id, paper_id, idempotency_key),
            ).fetchone()

    def _task_id_from_domain_idempotency(self, intent: sqlite3.Row) -> str | None:
        """Find a Task created before a process died before Literature checkpoint.

        ``TaskApplicationService.create_task`` checks current authorization
        before its idempotency record.  That is correct for a new request, but
        a saga recovery must be able to finish a pre-existing Task link after a
        later grant/project change.  This is a read-only lookup scoped to the
        original actor and deterministic saga key; it never creates or exposes
        a Task owned by another user.
        """

        with closing(connect(self._domain_db_path)) as conn:
            row = conn.execute(
                """
                SELECT response_json FROM domain_idempotency_requests
                WHERE actor_user_id = ? AND scope = 'task.create' AND idempotency_key = ?
                """,
                (intent["user_id"], intent["task_idempotency_key"]),
            ).fetchone()
            if row is None:
                return None
            try:
                response = json.loads(str(row["response_json"]))
            except json.JSONDecodeError as exc:
                raise RuntimeError("Stored Task idempotency response is invalid") from exc
            if not isinstance(response, dict):
                raise RuntimeError("Stored Task idempotency response is invalid")
            task_id = response.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError("Stored Task idempotency response has no task_id")
            task = conn.execute(
                "SELECT owner_user_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if task is None or task["owner_user_id"] != intent["user_id"]:
            raise RuntimeError("Stored Task idempotency response has an invalid owner")
        return task_id

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> dict[str, object]:
        try:
            payload = json.loads(str(row["request_input_json"]))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Research Task intent has invalid request input") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Research Task intent has invalid request input")
        return {str(key): value for key, value in payload.items()}

    @staticmethod
    def _intent_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "intent_id": str(row["intent_id"]),
            "paper_id": str(row["paper_id"]),
            "project_id": str(row["project_id"]),
            "workspace_id": str(row["workspace_id"]),
            "task_preset": str(row["task_preset"]),
            "title": str(row["title"]),
            "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
            "status": str(row["status"]),
            "idempotency_key": str(row["idempotency_key"]),
            "work_item_id": str(row["work_item_id"]),
            "attempt_count": int(row["attempt_count"]),
            "last_error": str(row["last_error"]) if row["last_error"] is not None else None,
            "next_retry_at": str(row["next_retry_at"])
            if row["next_retry_at"] is not None
            else None,
            "heartbeat_at": str(row["heartbeat_at"]) if row["heartbeat_at"] is not None else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "completed_at": str(row["completed_at"]) if row["completed_at"] is not None else None,
        }

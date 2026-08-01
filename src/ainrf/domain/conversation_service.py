"""Authoritative application transactions for conversation-v3 mutations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_contracts import (
    ApprovalStatus,
    ConversationAuthority,
    ConversationContractError,
    ConversationErrorCode,
    ControlKind,
    ForkTransferMode,
    IdempotencyScope,
    TaskWorkStatus,
    TurnStatus,
    require_approval_transition,
    require_task_work_transition,
    require_v3_write_authority,
)
from ainrf.domain.conversation_execution_repository import (
    SqliteConversationExecutionRepository,
)
from ainrf.domain.conversation_repository import SqliteConversationRepository
from ainrf.domain.context import ProjectContextService
from ainrf.domain.repositories import _SqliteDomainRepository
from ainrf.domain.service import (
    DomainAuthorizationService,
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
)
from ainrf.domain.write_fence import DomainWriteFence
from ainrf.domain_control import MaintenanceModeError
from ainrf.harness_engine.base import HarnessEngineType


_ENGINE_FAMILY_BY_HARNESS = {
    HarnessEngineType.CLAUDE_CODE: "claude",
    HarnessEngineType.AGENT_SDK: "claude",
    HarnessEngineType.CODEX_APP_SERVER: "codex",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _request_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            f"{field} must be an RFC3339 timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            f"{field} must be an RFC3339 timestamp",
        ) from None
    if parsed.tzinfo is None:
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            f"{field} must include a timezone",
        )
    return parsed.astimezone(timezone.utc)


def _metric_int(metrics: Mapping[str, object], key: str, default: int = 0) -> int:
    value = metrics.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Fork metric {key} must be a non-negative integer")
    return value


def _metric_float(metrics: Mapping[str, object], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Fork metric {key} must be numeric")
    return float(value)


def _text_size(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        return len(value), len(value.encode())
    if isinstance(value, Mapping):
        sizes = [_text_size(child) for child in value.values()]
    elif isinstance(value, (list, tuple)):
        sizes = [_text_size(child) for child in value]
    else:
        sizes = []
    return sum(size[0] for size in sizes), sum(size[1] for size in sizes)


def _fork_selection(
    turns: list[sqlite3.Row],
    *,
    transfer_mode: ForkTransferMode,
    transfer_range: Mapping[str, object],
) -> list[sqlite3.Row]:
    by_id = {str(turn["turn_id"]): turn for turn in turns}
    if transfer_mode is ForkTransferMode.CONTEXT_ONLY:
        if transfer_range:
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "context-only Fork range must be empty",
            )
        return []
    if transfer_mode is ForkTransferMode.FULL_TRANSCRIPT:
        through_turn = transfer_range.get("through_turn")
        if through_turn is None:
            return turns
        if not isinstance(through_turn, str) or through_turn not in by_id:
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "Fork range references an unknown Turn",
            )
        return turns[: turns.index(by_id[through_turn]) + 1]
    if transfer_mode is ForkTransferMode.SELECTED_TURNS:
        turn_ids = transfer_range.get("turn_ids")
        if (
            not isinstance(turn_ids, list)
            or not turn_ids
            or not all(isinstance(turn_id, str) and turn_id in by_id for turn_id in turn_ids)
        ):
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "selected-Turn Fork range must contain known Turn IDs",
            )
        if len(set(turn_ids)) != len(turn_ids):
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "selected-Turn Fork range contains duplicate Turn IDs",
            )
        selected = [turn for turn in turns if str(turn["turn_id"]) in turn_ids]
        if [str(turn["turn_id"]) for turn in selected] != turn_ids:
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "selected-Turn Fork range must use canonical order",
            )
        return selected
    count = transfer_range.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            "recent-Turn Fork range requires a positive count",
        )
    return turns[-count:]


_FORBIDDEN_EVIDENCE_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "credential",
    "secret",
    "cookie",
    "provider_header",
)


def _require_sanitized(value: object, *, path: str = "evidence") -> None:
    """Reject secret-shaped fields before durable evidence crosses the service boundary."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_EVIDENCE_KEYS):
                raise ConversationContractError(
                    ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                    f"{path} contains a prohibited field: {key}",
                )
            _require_sanitized(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _require_sanitized(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and value.lstrip().lower().startswith("bearer "):
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            f"{path} must not contain bearer credentials",
        )


class ConversationApplicationService:
    """The sole transaction owner for conversation-v3 application mutations."""

    def __init__(
        self,
        state_root: Path,
        *,
        artifact_sha: str | None = None,
        dispatch_notifier: Callable[[str], None] | None = None,
    ) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._write_fence = DomainWriteFence(state_root, artifact_sha=artifact_sha)
        self._context_service = ProjectContextService(state_root, artifact_sha=artifact_sha)
        self._dispatch_notifier = dispatch_notifier

    def v2_ready(self) -> bool:
        """Return whether committed-v2 state can host the Conversation Module."""

        return self._write_fence.v2_ready()

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _actor(user: Mapping[str, object]) -> str:
        actor = user.get("id")
        if not isinstance(actor, str) or not actor:
            raise DomainPermissionError("Authenticated user ID is required")
        return actor

    @staticmethod
    def _begin(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if state is None or bool(state["is_active"]):
            raise MaintenanceModeError("domain writes are paused for maintenance")

    @staticmethod
    def _require_v3(repository: SqliteConversationRepository, task_id: str) -> sqlite3.Row:
        authority = repository.task_authority(task_id)
        require_v3_write_authority(
            ConversationAuthority.CONVERSATION_V3
            if authority == ConversationAuthority.CONVERSATION_V3
            else ConversationAuthority.LEGACY_ATTEMPT
        )
        state = repository.task_state(task_id)
        if state is None:
            raise ConversationContractError(
                ConversationErrorCode.MIGRATION_REQUIRED,
                "conversation-v3 Task state is missing",
            )
        return state

    @staticmethod
    def _require_open(state: sqlite3.Row) -> None:
        if str(state["work_status"]) != TaskWorkStatus.OPEN:
            raise ConversationContractError(
                ConversationErrorCode.TASK_NOT_OPEN,
                "Task must be reopened before admitting another Turn",
            )

    @staticmethod
    def _replay(
        repository: _SqliteDomainRepository,
        *,
        actor: str,
        scope: IdempotencyScope,
        key: str,
        request: object,
    ) -> tuple[str, dict[str, object] | None]:
        if not key:
            raise DomainConflictError("Idempotency-Key is required")
        digest = _request_hash(request)
        row = repository.idempotency_record(actor_user_id=actor, scope=scope, key=key)
        if row is None:
            return digest, None
        if str(row["request_hash"]) != digest:
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        value = json.loads(str(row["response_json"]))
        if not isinstance(value, dict):
            raise DomainConflictError("Stored idempotency response is invalid")
        return digest, value

    @staticmethod
    def _store(
        repository: _SqliteDomainRepository,
        *,
        actor: str,
        scope: IdempotencyScope,
        key: str,
        digest: str,
        response: Mapping[str, object],
        created_at: str,
    ) -> None:
        repository.insert_idempotency_record(
            actor_user_id=actor,
            scope=scope,
            key=key,
            request_hash=digest,
            response_json=_canonical_json(response),
            created_at=created_at,
        )

    @staticmethod
    def _audit(
        repository: _SqliteDomainRepository,
        *,
        actor: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
        created_at: str,
    ) -> None:
        repository.insert_audit_event(
            event_id=uuid4().hex,
            actor_id=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            metadata_json="{}",
            created_at=created_at,
        )

    @staticmethod
    def _writable_workspace(
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
            """
            SELECT workspace.environment_id, workspace.status AS workspace_status,
                   environment.status AS environment_status
            FROM workspaces AS workspace
            JOIN environments AS environment
              ON environment.environment_id = workspace.environment_id
            JOIN project_workspace_links AS link
              ON link.project_id = ? AND link.workspace_id = workspace.workspace_id
             AND link.status = 'active'
            WHERE workspace.workspace_id = ?
            """,
            (project_id, workspace_id),
        ).fetchone()
        if row is None:
            raise DomainConflictError("Task Workspace must be an active Project link")
        if row["workspace_status"] != "active" or row["environment_status"] != "active":
            raise DomainConflictError("Task Workspace and Environment must be active")
        if expected_environment_id is not None and row["environment_id"] != expected_environment_id:
            raise DomainConflictError("Task environment must be derived from the Workspace")
        return row

    def initialize_task(self, task_id: str, user: dict[str, object]) -> dict[str, object]:
        """Establish explicit v3 authority for a newly-created Task."""
        actor = self._actor(user)
        created_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                conversations = SqliteConversationRepository(conn)
                if conversations.task_authority(task_id) is not None:
                    raise DomainConflictError("Task conversation authority already exists")
                conversations.insert_task_authority(task_id=task_id, created_at=created_at)
                conversations.insert_task_state(task_id=task_id, created_at=created_at)
                self._audit(
                    _SqliteDomainRepository(conn),
                    actor=actor,
                    event_type="conversation.task.initialized",
                    subject_type="task",
                    subject_id=task_id,
                    created_at=created_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return {"task_id": task_id, "work_status": TaskWorkStatus.OPEN, "revision": 1}

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
        environment_id: str | None = None,
        user_skills: list[str] | None = None,
        user_mcp_servers: list[str] | None = None,
    ) -> dict[str, object]:
        """Create a Task and its initial TurnSubmission in one transaction."""

        actor = self._actor(user)
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
        created_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.CREATE_TASK,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    DomainAuthorizationService(conn).require_task_owner(
                        str(replay["task_id"]), user
                    )
                    conn.commit()
                    return replay
                authorization = DomainAuthorizationService(conn)
                authorization.require_project_editor(project_id, user)
                authorization.require_workspace_owner(workspace_id, user)
                workspace = self._writable_workspace(
                    conn,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    expected_environment_id=environment_id,
                )
                task_id = f"task-{uuid4().hex}"
                snapshot_id, context_version_id = (
                    self._context_service._create_active_snapshot_for_task_in_transaction(
                        conn,
                        project_id=project_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                        task_prompt=prompt,
                    )
                )
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, workspace_id, environment_id, researcher_type,
                        harness_engine, user_skills, user_mcp_servers, status, title, prompt,
                        created_at, updated_at, owner_user_id, project_context_version_id,
                        project_context_snapshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        project_id,
                        workspace_id,
                        str(workspace["environment_id"]),
                        researcher_type,
                        harness_engine,
                        _canonical_json(user_skills or []),
                        _canonical_json(user_mcp_servers or []),
                        title,
                        prompt,
                        created_at,
                        created_at,
                        actor,
                        context_version_id,
                        snapshot_id,
                    ),
                )
                conversations = SqliteConversationRepository(conn)
                conversations.insert_task_authority(task_id=task_id, created_at=created_at)
                conversations.insert_task_state(task_id=task_id, created_at=created_at)
                executions = SqliteConversationExecutionRepository(conn)
                submission_id = uuid4().hex
                reserved_turn_id = uuid4().hex
                executions.insert_submission(
                    submission_id=submission_id,
                    task_id=task_id,
                    reserved_turn_id=reserved_turn_id,
                    actor_user_id=actor,
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                    input_json=_canonical_json({"text": prompt}),
                    context_snapshot_ref=snapshot_id,
                    created_at=created_at,
                    updated_at=created_at,
                )
                executions.insert_submission_intent(
                    submission_id=submission_id,
                    task_id=task_id,
                    kind="create",
                    retry_of_turn_id=None,
                    created_at=created_at,
                )
                result: dict[str, object] = {
                    "task_id": task_id,
                    "submission_id": submission_id,
                    "reserved_turn_id": reserved_turn_id,
                    "status": "queued",
                    "intent": "create",
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.CREATE_TASK,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=created_at,
                )
                self._audit(
                    domain,
                    actor=actor,
                    event_type="conversation.task.created",
                    subject_type="task",
                    subject_id=task_id,
                    created_at=created_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if self._dispatch_notifier is not None:
            self._dispatch_notifier(submission_id)
        return result

    def create_turn(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        input: Mapping[str, object],
        idempotency_key: str,
        context_snapshot_ref: str | None = None,
        allow_next_turn: bool = False,
    ) -> dict[str, object]:
        return self._admit(
            task_id,
            user,
            input=input,
            idempotency_key=idempotency_key,
            context_snapshot_ref=context_snapshot_ref,
            scope=IdempotencyScope.CREATE_TURN,
            retry_of_turn_id=None,
            allow_next_turn=allow_next_turn,
        )

    def retry_turn(
        self,
        task_id: str,
        turn_id: str,
        user: dict[str, object],
        *,
        input: Mapping[str, object],
        idempotency_key: str,
        context_snapshot_ref: str | None = None,
    ) -> dict[str, object]:
        return self._admit(
            task_id,
            user,
            input=input,
            idempotency_key=idempotency_key,
            context_snapshot_ref=context_snapshot_ref,
            scope=IdempotencyScope.RETRY_TURN,
            retry_of_turn_id=turn_id,
            allow_next_turn=False,
        )

    def _admit(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        input: Mapping[str, object],
        idempotency_key: str,
        context_snapshot_ref: str | None,
        scope: IdempotencyScope,
        retry_of_turn_id: str | None,
        allow_next_turn: bool,
    ) -> dict[str, object]:
        actor = self._actor(user)
        request = {
            "task_id": task_id,
            "input": dict(input),
            "context_snapshot_ref": context_snapshot_ref,
            "retry_of_turn_id": retry_of_turn_id,
            "allow_next_turn": allow_next_turn,
        }
        created_at = _now()
        notify_submission: str | None = None
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_open(self._require_v3(conversations, task_id))
                conflicting = executions.submission_by_task_key(
                    task_id=task_id,
                    actor_user_id=actor,
                    idempotency_key=idempotency_key,
                )
                if conflicting is not None:
                    raise DomainConflictError(
                        "Idempotency-Key was already used for another Turn admission action"
                    )
                active = conversations.active_turn(task_id)
                pending = executions.pending_next_turn(task_id)
                if pending is not None:
                    raise ConversationContractError(
                        ConversationErrorCode.ACTIVE_TURN_EXISTS,
                        "Task already has a pending next-Turn submission",
                    )
                if retry_of_turn_id is not None:
                    source = conversations.turn_by_id(retry_of_turn_id)
                    if source is None or str(source["task_id"]) != task_id:
                        raise DomainNotFoundError(retry_of_turn_id)
                    if str(source["status"]) == TurnStatus.IN_PROGRESS:
                        raise ConversationContractError(
                            ConversationErrorCode.TURN_NOT_ACTIVE,
                            "Retry requires a terminal source Turn",
                        )
                if active is not None and not allow_next_turn:
                    raise ConversationContractError(
                        ConversationErrorCode.ACTIVE_TURN_EXISTS,
                        "Task already has an active Turn",
                    )
                if active is not None and retry_of_turn_id is not None:
                    raise ConversationContractError(
                        ConversationErrorCode.ACTIVE_TURN_EXISTS,
                        "Retry cannot be admitted while another Turn is active",
                    )
                submission_id = uuid4().hex
                reserved_turn_id = uuid4().hex
                intent = (
                    "retry"
                    if retry_of_turn_id is not None
                    else "next_turn"
                    if active is not None
                    else "create"
                )
                executions.insert_submission(
                    submission_id=submission_id,
                    task_id=task_id,
                    reserved_turn_id=reserved_turn_id,
                    actor_user_id=actor,
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                    input_json=_canonical_json(input),
                    context_snapshot_ref=context_snapshot_ref,
                    created_at=created_at,
                    updated_at=created_at,
                )
                executions.insert_submission_intent(
                    submission_id=submission_id,
                    task_id=task_id,
                    kind=intent,
                    retry_of_turn_id=retry_of_turn_id,
                    created_at=created_at,
                )
                if active is not None:
                    executions.insert_next_turn(
                        submission_id=submission_id,
                        task_id=task_id,
                        blocking_turn_id=str(active["turn_id"]),
                        created_at=created_at,
                    )
                else:
                    notify_submission = submission_id
                result: dict[str, object] = {
                    "submission_id": submission_id,
                    "task_id": task_id,
                    "reserved_turn_id": reserved_turn_id,
                    "status": "queued",
                    "intent": intent,
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=created_at,
                )
                self._audit(
                    domain,
                    actor=actor,
                    event_type="conversation.turn.admitted",
                    subject_type="turn_submission",
                    subject_id=submission_id,
                    created_at=created_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if notify_submission is not None and self._dispatch_notifier is not None:
            self._dispatch_notifier(notify_submission)
        return result

    def update_work_status(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        status: TaskWorkStatus,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor = self._actor(user)
        request = {"task_id": task_id, "status": status}
        updated_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.UPDATE_WORK_STATUS,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                state = self._require_v3(conversations, task_id)
                current = TaskWorkStatus(str(state["work_status"]))
                require_task_work_transition(current, status)
                if (
                    conversations.update_work_status(
                        task_id=task_id,
                        expected_status=current,
                        status=status,
                        updated_at=updated_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Task work-status update lost a state race")
                result: dict[str, object] = {
                    "task_id": task_id,
                    "work_status": status,
                    "revision": int(state["revision"]) + 1,
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.UPDATE_WORK_STATUS,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=updated_at,
                )
                self._audit(
                    domain,
                    actor=actor,
                    event_type="conversation.task.work_status_updated",
                    subject_type="task",
                    subject_id=task_id,
                    created_at=updated_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def cancel_task(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Cancel Task work and causally interrupt its active Turn, if any."""

        actor = self._actor(user)
        updated_at = _now()
        request = {"task_id": task_id}
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.CANCEL_TASK,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                state = self._require_v3(conversations, task_id)
                current = TaskWorkStatus(str(state["work_status"]))
                control_request_id: str | None = None
                active_turn = conversations.active_turn(task_id)
                if active_turn is not None:
                    execution = executions.active_runtime_execution(str(active_turn["turn_id"]))
                    if execution is None:
                        raise ConversationContractError(
                            ConversationErrorCode.RUNTIME_LOST,
                            "Active Turn has no interruptible RuntimeExecution",
                        )
                    control_request_id = uuid4().hex
                    executions.insert_control_request(
                        control_request_id=control_request_id,
                        task_id=task_id,
                        expected_turn_id=str(active_turn["turn_id"]),
                        runtime_execution_id=str(execution["runtime_execution_id"]),
                        runtime_generation=int(execution["runtime_generation"]),
                        kind=ControlKind.INTERRUPT,
                        actor_user_id=actor,
                        idempotency_key=idempotency_key,
                        request_hash=digest,
                        payload_json="{}",
                        created_at=updated_at,
                        updated_at=updated_at,
                    )
                if current is TaskWorkStatus.OPEN:
                    require_task_work_transition(current, TaskWorkStatus.CANCELLED)
                    if conversations.update_work_status(
                        task_id=task_id,
                        expected_status=current,
                        status=TaskWorkStatus.CANCELLED,
                        updated_at=updated_at,
                    ) != 1:
                        raise DomainConflictError("Task cancellation lost a state race")
                conn.execute(
                    "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE task_id = ?",
                    (updated_at, task_id),
                )
                result: dict[str, object] = {
                    "task_id": task_id,
                    "work_status": TaskWorkStatus.CANCELLED,
                    "control_request_id": control_request_id,
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.CANCEL_TASK,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=updated_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def archive_task(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Archive an idle Conversation Task without hiding active execution."""

        return self._update_task_metadata(
            task_id,
            user,
            scope=IdempotencyScope.ARCHIVE_TASK,
            idempotency_key=idempotency_key,
            request={"task_id": task_id, "archived": True},
            require_idle=True,
            sql="UPDATE tasks SET archived_at = ?, archive_reason = 'user_archived', "
            "updated_at = ? WHERE task_id = ? AND archived_at IS NULL",
            parameters=lambda now: (now, now, task_id),
        )

    def unarchive_task(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self._update_task_metadata(
            task_id,
            user,
            scope=IdempotencyScope.UNARCHIVE_TASK,
            idempotency_key=idempotency_key,
            request={"task_id": task_id, "archived": False},
            require_idle=False,
            sql="UPDATE tasks SET archived_at = NULL, archive_reason = NULL, updated_at = ? "
            "WHERE task_id = ? AND archived_at IS NOT NULL",
            parameters=lambda now: (now, task_id),
        )

    def update_task_title(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        title: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized = title.strip()
        if not normalized:
            raise ValueError("Task title must not be empty")
        return self._update_task_metadata(
            task_id,
            user,
            scope=IdempotencyScope.UPDATE_TASK_TITLE,
            idempotency_key=idempotency_key,
            request={"task_id": task_id, "title": normalized},
            require_idle=False,
            sql="UPDATE tasks SET title = ?, updated_at = ? WHERE task_id = ?",
            parameters=lambda now: (normalized, now, task_id),
        )

    def _update_task_metadata(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        scope: IdempotencyScope,
        idempotency_key: str,
        request: Mapping[str, object],
        require_idle: bool,
        sql: str,
        parameters: Callable[[str], tuple[object, ...]],
    ) -> dict[str, object]:
        actor = self._actor(user)
        updated_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                self._require_v3(conversations, task_id)
                if require_idle and conversations.active_turn(task_id) is not None:
                    raise ConversationContractError(
                        ConversationErrorCode.ACTIVE_TURN_EXISTS,
                        "Interrupt the active Turn before archiving its Task",
                    )
                conn.execute(sql, parameters(updated_at))
                result: dict[str, object] = {"task_id": task_id, "updated_at": updated_at}
                self._store(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=updated_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def request_steer(
        self,
        task_id: str,
        turn_id: str,
        user: dict[str, object],
        *,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> dict[str, object]:
        return self._request_control(
            task_id,
            turn_id,
            user,
            kind=ControlKind.STEER,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def request_interrupt(
        self,
        task_id: str,
        turn_id: str,
        user: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self._request_control(
            task_id,
            turn_id,
            user,
            kind=ControlKind.INTERRUPT,
            payload={},
            idempotency_key=idempotency_key,
        )

    def _request_control(
        self,
        task_id: str,
        turn_id: str,
        user: dict[str, object],
        *,
        kind: ControlKind,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> dict[str, object]:
        actor = self._actor(user)
        scope = (
            IdempotencyScope.STEER_TURN
            if kind is ControlKind.STEER
            else IdempotencyScope.INTERRUPT_TURN
        )
        request = {"task_id": task_id, "turn_id": turn_id, "payload": dict(payload)}
        created_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_v3(conversations, task_id)
                turn = conversations.turn_by_id(turn_id)
                if turn is None or str(turn["task_id"]) != task_id:
                    raise DomainNotFoundError(turn_id)
                if str(turn["status"]) != TurnStatus.IN_PROGRESS:
                    raise ConversationContractError(
                        ConversationErrorCode.TURN_NOT_ACTIVE, "Expected Turn is not active"
                    )
                execution = executions.active_runtime_execution(turn_id)
                if execution is None:
                    raise ConversationContractError(
                        ConversationErrorCode.RUNTIME_LOST,
                        "Active Turn has no controllable RuntimeExecution",
                    )
                runtime_execution_id = str(execution["runtime_execution_id"])
                runtime_generation = int(execution["runtime_generation"])
                control_request_id = uuid4().hex
                executions.insert_control_request(
                    control_request_id=control_request_id,
                    task_id=task_id,
                    expected_turn_id=turn_id,
                    runtime_execution_id=runtime_execution_id,
                    runtime_generation=runtime_generation,
                    kind=kind,
                    actor_user_id=actor,
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                    payload_json=_canonical_json(payload),
                    created_at=created_at,
                    updated_at=created_at,
                )
                result: dict[str, object] = {
                    "control_request_id": control_request_id,
                    "task_id": task_id,
                    "expected_turn_id": turn_id,
                    "kind": kind,
                    "status": "requested",
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=scope,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=created_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def resolve_approval(
        self,
        task_id: str,
        approval_id: str,
        user: dict[str, object],
        *,
        status: ApprovalStatus,
        runtime_execution_id: str | None = None,
        runtime_generation: int | None = None,
        tool_call_ref: str | None = None,
        decision: Mapping[str, object],
        idempotency_key: str,
    ) -> dict[str, object]:
        _require_sanitized(decision, path="approval_decision")
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "A user decision can only approve or deny an approval",
            )
        actor = self._actor(user)
        request = {
            "task_id": task_id,
            "approval_id": approval_id,
            "status": status,
            "decision": dict(decision),
        }
        resolved_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.RESOLVE_APPROVAL,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_v3(conversations, task_id)
                approval = executions.approval_by_id(approval_id)
                if approval is None or str(approval["task_id"]) != task_id:
                    raise DomainNotFoundError(approval_id)
                persisted_runtime_execution_id = str(approval["runtime_execution_id"])
                persisted_runtime_generation = int(approval["runtime_generation"])
                persisted_tool_call_ref = str(approval["tool_call_ref"])
                if runtime_execution_id is not None and (
                    runtime_execution_id != persisted_runtime_execution_id
                    or runtime_generation != persisted_runtime_generation
                    or tool_call_ref != persisted_tool_call_ref
                ):
                    raise ConversationContractError(
                        ConversationErrorCode.RUNTIME_LOST,
                        "Approval runtime or tool-call scope is stale",
                    )
                require_approval_transition(ApprovalStatus(str(approval["status"])), status)
                turn = conversations.turn_by_id(str(approval["turn_id"]))
                execution = executions.active_runtime_execution(str(approval["turn_id"]))
                if turn is None or str(turn["status"]) != TurnStatus.IN_PROGRESS:
                    raise ConversationContractError(
                        ConversationErrorCode.TURN_NOT_ACTIVE,
                        "Approval belongs to a terminal Turn",
                    )
                if (
                    execution is None
                    or str(execution["runtime_execution_id"])
                    != persisted_runtime_execution_id
                    or int(execution["runtime_generation"])
                    != persisted_runtime_generation
                ):
                    raise ConversationContractError(
                        ConversationErrorCode.RUNTIME_LOST,
                        "Approval runtime or tool-call scope is stale",
                    )
                expires_at = approval["expires_at"]
                if expires_at is not None and _parse_timestamp(
                    expires_at, field="approval.expires_at"
                ) < _parse_timestamp(resolved_at, field="resolved_at"):
                    raise ConversationContractError(
                        ConversationErrorCode.RUNTIME_LOST, "Approval has expired"
                    )
                if (
                    executions.resolve_approval(
                        approval_id=approval_id,
                        status=status,
                        decision_json=_canonical_json(decision),
                        decision_actor_user_id=actor,
                        decision_idempotency_key=idempotency_key,
                        decision_request_hash=digest,
                        resolved_at=resolved_at,
                        updated_at=resolved_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Approval resolution lost a state race")
                result: dict[str, object] = {
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "status": status,
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.RESOLVE_APPROVAL,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=resolved_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def preview_fork(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        target_engine_family: str,
        transfer_mode: ForkTransferMode,
        transfer_range: Mapping[str, object],
        metrics: Mapping[str, object],
        disclosure: Mapping[str, object],
        idempotency_key: str,
        validity_seconds: int = 900,
    ) -> dict[str, object]:
        _require_sanitized(transfer_range, path="fork_transfer_range")
        _require_sanitized(metrics, path="fork_metrics")
        _require_sanitized(disclosure, path="fork_disclosure")
        if validity_seconds <= 0:
            raise ValueError("Fork preview validity must be positive")
        actor = self._actor(user)
        request = {
            "task_id": task_id,
            "target_engine_family": target_engine_family,
            "transfer_mode": transfer_mode,
            "transfer_range": dict(transfer_range),
            "metrics": dict(metrics),
            "disclosure": dict(disclosure),
            "validity_seconds": validity_seconds,
        }
        created = datetime.now(timezone.utc)
        created_at = created.isoformat()
        expires_at = (created + timedelta(seconds=validity_seconds)).isoformat()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.FORK_PREVIEW,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_v3(conversations, task_id)
                turns = conversations.list_turns(task_id)
                selected_turns = _fork_selection(
                    turns,
                    transfer_mode=transfer_mode,
                    transfer_range=transfer_range,
                )
                selected_turn_ids = {str(turn["turn_id"]) for turn in selected_turns}
                selected_items = [
                    item
                    for item in conversations.list_task_items(task_id)
                    if str(item["turn_id"]) in selected_turn_ids
                ]
                character_count = 0
                utf8_byte_count = 0
                for item in selected_items:
                    try:
                        payload = json.loads(str(item["payload_json"]))
                    except json.JSONDecodeError:
                        payload = str(item["payload_json"])
                    item_characters, item_bytes = _text_size(payload)
                    character_count += item_characters
                    utf8_byte_count += item_bytes
                canonical_metrics = {
                    "message_count": sum(
                        str(item["item_type"]) in {"user_message", "assistant_message"}
                        for item in selected_items
                    ),
                    "turn_count": len(selected_turns),
                    "item_count": len(selected_items),
                    "character_count": character_count,
                    "utf8_byte_count": utf8_byte_count,
                }
                for key, value in canonical_metrics.items():
                    if key in metrics and _metric_int(metrics, key) != value:
                        raise ConversationContractError(
                            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                            f"Fork metric {key} contradicts canonical history",
                        )
                if turns:
                    source_engine = str(turns[-1]["engine_family"])
                else:
                    harness_engine = conversations.task_harness_engine(task_id)
                    try:
                        source_engine = _ENGINE_FAMILY_BY_HARNESS[HarnessEngineType(harness_engine)]
                    except (ValueError, KeyError):
                        raise ConversationContractError(
                            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                            "Task harness engine cannot establish a Fork source engine",
                        ) from None
                if source_engine == target_engine_family:
                    raise ConversationContractError(
                        ConversationErrorCode.FORK_CONFIRMATION_REQUIRED,
                        "Cross-engine Fork preview requires a different target engine",
                    )
                preview_id = uuid4().hex
                source_revision = conversations.transcript_revision(task_id)
                preview_hash = _request_hash(
                    {**request, "source_revision": source_revision, "preview_id": preview_id}
                )
                executions.insert_fork_preview(
                    preview_id=preview_id,
                    preview_hash=preview_hash,
                    source_task_id=task_id,
                    source_revision=source_revision,
                    source_engine_family=source_engine,
                    target_engine_family=target_engine_family,
                    transfer_mode=transfer_mode,
                    transfer_range_json=_canonical_json(transfer_range),
                    message_count=canonical_metrics["message_count"],
                    turn_count=canonical_metrics["turn_count"],
                    item_count=canonical_metrics["item_count"],
                    character_count=canonical_metrics["character_count"],
                    utf8_byte_count=canonical_metrics["utf8_byte_count"],
                    estimated_token_count=_metric_int(metrics, "estimated_token_count"),
                    token_estimator=str(metrics.get("token_estimator", "unknown-v1")),
                    context_window_percent=_metric_float(metrics, "context_window_percent"),
                    tool_result_count=_metric_int(metrics, "tool_result_count"),
                    reasoning_count=_metric_int(metrics, "reasoning_count"),
                    binary_count=_metric_int(metrics, "binary_count"),
                    image_reference_count=_metric_int(metrics, "image_reference_count"),
                    cost_estimate_json=(
                        None
                        if metrics.get("cost_estimate") is None
                        else _canonical_json(metrics["cost_estimate"])
                    ),
                    cost_unknown=metrics.get("cost_estimate") is None,
                    truncated=bool(metrics.get("truncated", False)),
                    disclosure_json=_canonical_json(disclosure),
                    created_at=created_at,
                    expires_at=expires_at,
                )
                result: dict[str, object] = {
                    "preview_id": preview_id,
                    "preview_hash": preview_hash,
                    "source_task_id": task_id,
                    "source_revision": source_revision,
                    "source_engine_family": source_engine,
                    "target_engine_family": target_engine_family,
                    "transfer_mode": transfer_mode,
                    "truncated": bool(metrics.get("truncated", False)),
                    "expires_at": expires_at,
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.FORK_PREVIEW,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=created_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def confirm_fork(
        self,
        task_id: str,
        preview_id: str,
        user: dict[str, object],
        *,
        preview_hash: str,
        source_revision: str,
        transfer_mode: ForkTransferMode,
        truncation_acknowledged: bool,
        full_transcript_confirmed: bool,
        idempotency_key: str,
    ) -> dict[str, object]:
        actor = self._actor(user)
        request = {
            "task_id": task_id,
            "preview_id": preview_id,
            "preview_hash": preview_hash,
            "source_revision": source_revision,
            "transfer_mode": transfer_mode,
            "truncation_acknowledged": truncation_acknowledged,
            "full_transcript_confirmed": full_transcript_confirmed,
        }
        confirmed_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                DomainAuthorizationService(conn).require_task_owner(task_id, user)
                domain = _SqliteDomainRepository(conn)
                digest, replay = self._replay(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.FORK_CONFIRM,
                    key=idempotency_key,
                    request=request,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_v3(conversations, task_id)
                preview = executions.fork_preview_by_id(preview_id)
                if preview is None or str(preview["source_task_id"]) != task_id:
                    raise DomainNotFoundError(preview_id)
                if (
                    str(preview["preview_hash"]) != preview_hash
                    or str(preview["source_revision"]) != source_revision
                    or str(preview["transfer_mode"]) != transfer_mode
                    or conversations.transcript_revision(task_id) != source_revision
                    or _parse_timestamp(preview["expires_at"], field="fork_preview.expires_at")
                    < _parse_timestamp(confirmed_at, field="confirmed_at")
                    or (bool(preview["truncated"]) and not truncation_acknowledged)
                    or (
                        transfer_mode is ForkTransferMode.FULL_TRANSCRIPT
                        and not full_transcript_confirmed
                    )
                    or (
                        transfer_mode is not ForkTransferMode.FULL_TRANSCRIPT
                        and full_transcript_confirmed
                    )
                ):
                    raise ConversationContractError(
                        ConversationErrorCode.FORK_CONFIRMATION_REQUIRED,
                        "Fork confirmation does not match a current preview",
                    )
                transfer_id = uuid4().hex
                executions.insert_fork_transfer(
                    transfer_id=transfer_id,
                    preview_id=preview_id,
                    preview_hash=preview_hash,
                    source_task_id=task_id,
                    source_revision=source_revision,
                    transfer_mode=transfer_mode,
                    truncation_acknowledged=truncation_acknowledged,
                    full_transcript_confirmed=full_transcript_confirmed,
                    actor_user_id=actor,
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                    confirmed_at=confirmed_at,
                    updated_at=confirmed_at,
                )
                result: dict[str, object] = {
                    "transfer_id": transfer_id,
                    "preview_id": preview_id,
                    "source_task_id": task_id,
                    "status": "confirmed",
                }
                self._store(
                    domain,
                    actor=actor,
                    scope=IdempotencyScope.FORK_CONFIRM,
                    key=idempotency_key,
                    digest=digest,
                    response=result,
                    created_at=confirmed_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result

    def accept_submission(
        self,
        submission_id: str,
        *,
        native_turn_kind: str,
        native_turn_ref: str,
        engine_family: str,
        engine_driver: str,
        contract_version: int,
        delivery_evidence: Mapping[str, object],
        binding_id: str | None = None,
        provider_profile_ref: str | None = None,
        provider_profile_version: str | None = None,
        provider_profile_fingerprint: str | None = None,
        model: str | None = None,
    ) -> dict[str, object]:
        """Materialize canonical history from a trusted provider-acceptance callback."""
        _require_sanitized(delivery_evidence, path="delivery_evidence")
        accepted_at = _now()
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                executions = SqliteConversationExecutionRepository(conn)
                conversations = SqliteConversationRepository(conn)
                submission = executions.submission_by_id(submission_id)
                intent = executions.submission_intent(submission_id)
                if submission is None or intent is None:
                    raise DomainNotFoundError(submission_id)
                task_id = str(submission["task_id"])
                self._require_v3(conversations, task_id)
                harness_engine = conversations.task_harness_engine(task_id)
                try:
                    persisted_family = _ENGINE_FAMILY_BY_HARNESS[HarnessEngineType(harness_engine)]
                except (ValueError, KeyError):
                    raise ConversationContractError(
                        ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                        "Task harness engine cannot establish acceptance lineage",
                    ) from None
                if engine_family != persisted_family or engine_driver != harness_engine:
                    raise ConversationContractError(
                        ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                        "Acceptance callback contradicts persisted engine lineage",
                    )
                binding = conversations.active_binding(task_id)
                if binding is not None:
                    if (
                        binding_id != str(binding["binding_id"])
                        or engine_family != str(binding["engine_family"])
                        or engine_driver != str(binding["engine_driver"])
                        or contract_version != int(binding["contract_version"])
                    ):
                        raise ConversationContractError(
                            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                            "Acceptance callback contradicts the active engine binding",
                        )
                elif binding_id is not None:
                    raise ConversationContractError(
                        ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                        "Acceptance callback references an inactive engine binding",
                    )
                if str(submission["status"]) == "delivered":
                    turn = conversations.turn_by_id(str(submission["reserved_turn_id"]))
                    if (
                        turn is None
                        or str(turn["native_turn_kind"]) != native_turn_kind
                        or str(turn["native_turn_ref"]) != native_turn_ref
                        or str(turn["engine_family"]) != engine_family
                        or str(turn["engine_driver"]) != engine_driver
                        or int(turn["contract_version"]) != contract_version
                        or (None if turn["binding_id"] is None else str(turn["binding_id"]))
                        != binding_id
                    ):
                        raise ConversationContractError(
                            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                            "Delivered callback replay contradicts canonical Turn identity",
                        )
                    result: dict[str, object] = {
                        "submission_id": submission_id,
                        "turn_id": str(submission["reserved_turn_id"]),
                        "status": "delivered",
                    }
                    conn.commit()
                    return result
                if str(submission["status"]) not in {"delivering", "delivery_unknown"}:
                    raise ConversationContractError(
                        ConversationErrorCode.INVALID_STATE_TRANSITION,
                        "Only a delivering or delivery-unknown submission can be accepted",
                    )
                if conversations.active_turn(task_id) is not None:
                    raise ConversationContractError(
                        ConversationErrorCode.ACTIVE_TURN_EXISTS,
                        "Task already has an active Turn",
                    )
                turn_id = str(submission["reserved_turn_id"])
                conversations.insert_turn(
                    turn_id=turn_id,
                    task_id=task_id,
                    turn_seq=conversations.next_turn_seq(task_id),
                    status=TurnStatus.IN_PROGRESS,
                    retry_of_turn_id=(
                        None
                        if intent["retry_of_turn_id"] is None
                        else str(intent["retry_of_turn_id"])
                    ),
                    context_snapshot_ref=(
                        None
                        if submission["context_snapshot_ref"] is None
                        else str(submission["context_snapshot_ref"])
                    ),
                    binding_id=binding_id,
                    engine_family=engine_family,
                    engine_driver=engine_driver,
                    contract_version=contract_version,
                    provider_profile_ref=provider_profile_ref,
                    provider_profile_version=provider_profile_version,
                    provider_profile_fingerprint=provider_profile_fingerprint,
                    model=model,
                    native_turn_kind=native_turn_kind,
                    native_turn_ref=native_turn_ref,
                    accepted_at=accepted_at,
                    started_at=accepted_at,
                    updated_at=accepted_at,
                )
                conversations.insert_turn_item(
                    item_id=uuid4().hex,
                    task_id=task_id,
                    turn_id=turn_id,
                    task_item_seq=conversations.next_task_item_seq(task_id),
                    turn_item_seq=1,
                    envelope_type="conversation.item",
                    envelope_version=1,
                    item_type="user_message",
                    actor="user",
                    payload_json=str(submission["input_json"]),
                    native_provenance_json=_canonical_json(delivery_evidence),
                    native_dedupe_scope=f"submission:{submission_id}",
                    native_item_id=submission_id,
                    parent_item_id=None,
                    call_item_id=None,
                    occurred_at=accepted_at,
                    ingested_at=accepted_at,
                    persisted_at=accepted_at,
                )
                if (
                    executions.transition_submission(
                        submission_id=submission_id,
                        expected_status=str(submission["status"]),
                        status="delivered",
                        updated_at=accepted_at,
                        accepted_at=accepted_at,
                        finished_at=accepted_at,
                        native_turn_kind=native_turn_kind,
                        native_turn_ref=native_turn_ref,
                        delivery_evidence_json=_canonical_json(delivery_evidence),
                    )
                    != 1
                ):
                    raise DomainConflictError("Submission acceptance lost a state race")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return {"submission_id": submission_id, "turn_id": turn_id, "status": "delivered"}

    def finish_turn(
        self,
        task_id: str,
        turn_id: str,
        *,
        status: TurnStatus,
        failure_code: str | None = None,
        _terminal_side_effect: Callable[[SqliteConversationExecutionRepository, str], None]
        | None = None,
    ) -> dict[str, object]:
        """Apply trusted terminal runtime evidence and promote a deferred next Turn."""
        try:
            terminal_status = TurnStatus(status)
        except ValueError:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "Turn terminal status is invalid",
            ) from None
        if terminal_status is TurnStatus.IN_PROGRESS:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "A Turn can finish only in a terminal state",
            )
        if terminal_status is TurnStatus.FAILED and (
            failure_code is None or not failure_code.strip()
        ):
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "A failed Turn requires a non-empty failure code",
            )
        if terminal_status is not TurnStatus.FAILED and failure_code is not None:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "Only a failed Turn can include a failure code",
            )
        status = terminal_status
        finished_at = _now()
        promoted_submission: str | None = None
        with closing(self._connect()) as conn:
            try:
                self._begin(conn)
                conversations = SqliteConversationRepository(conn)
                executions = SqliteConversationExecutionRepository(conn)
                self._require_v3(conversations, task_id)
                turn = conversations.turn_by_id(turn_id)
                if turn is None or str(turn["task_id"]) != task_id:
                    raise DomainNotFoundError(turn_id)
                if str(turn["status"]) != TurnStatus.IN_PROGRESS:
                    persisted_failure = (
                        None if turn["failure_code"] is None else str(turn["failure_code"])
                    )
                    if str(turn["status"]) == status and persisted_failure == failure_code:
                        if _terminal_side_effect is not None:
                            _terminal_side_effect(executions, finished_at)
                        conn.commit()
                        return {
                            "task_id": task_id,
                            "turn_id": turn_id,
                            "status": status,
                            "promoted_submission_id": None,
                        }
                    raise ConversationContractError(
                        ConversationErrorCode.TURN_NOT_ACTIVE,
                        "Turn is already terminal with different evidence",
                    )
                if (
                    conversations.finish_turn(
                        turn_id=turn_id,
                        status=status,
                        finished_at=finished_at,
                        updated_at=finished_at,
                        failure_code=failure_code,
                    )
                    != 1
                ):
                    raise ConversationContractError(
                        ConversationErrorCode.TURN_NOT_ACTIVE, "Turn is not active"
                    )
                waiting = executions.waiting_next_turn(task_id)
                if waiting is not None and str(waiting["blocking_turn_id"]) == turn_id:
                    promoted_submission = str(waiting["submission_id"])
                    state = conversations.task_state(task_id)
                    if state is None:
                        raise ConversationContractError(
                            ConversationErrorCode.MIGRATION_REQUIRED,
                            "conversation-v3 Task state is missing",
                        )
                    if str(state["work_status"]) == TaskWorkStatus.OPEN:
                        if (
                            executions.promote_next_turn(
                                submission_id=promoted_submission,
                                promoted_at=finished_at,
                                updated_at=finished_at,
                            )
                            != 1
                        ):
                            raise DomainConflictError("Next-Turn promotion lost a state race")
                    else:
                        if (
                            executions.cancel_next_turn(
                                submission_id=promoted_submission,
                                updated_at=finished_at,
                            )
                            != 1
                            or executions.transition_submission(
                                submission_id=promoted_submission,
                                expected_status="queued",
                                status="cancelled",
                                updated_at=finished_at,
                                finished_at=finished_at,
                                failure_code="task_closed_before_promotion",
                            )
                            != 1
                        ):
                            raise DomainConflictError("Next-Turn cancellation lost a state race")
                        promoted_submission = None
                if _terminal_side_effect is not None:
                    _terminal_side_effect(executions, finished_at)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if promoted_submission is not None and self._dispatch_notifier is not None:
            self._dispatch_notifier(promoted_submission)
        return {
            "task_id": task_id,
            "turn_id": turn_id,
            "status": status,
            "promoted_submission_id": promoted_submission,
        }

    def read_task(self, task_id: str, user: dict[str, object]) -> dict[str, object]:
        """Read one canonical conversation aggregate through the application Interface."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_viewer(task_id, user)
            conversations = SqliteConversationRepository(conn)
            state = self._require_v3(conversations, task_id)
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            active_turn = conversations.active_turn(task_id)
            binding = conversations.active_binding(task_id)
            turn_count = conn.execute(
                "SELECT COUNT(*) FROM task_turns WHERE task_id = ?", (task_id,)
            ).fetchone()
            item_count = conn.execute(
                "SELECT COUNT(*) FROM turn_items WHERE task_id = ?", (task_id,)
            ).fetchone()
        result = self._row_dict(task)
        result.update(
            {
                "work_status": str(state["work_status"]),
                "conversation_revision": int(state["revision"]),
                "runtime_status": "active" if active_turn is not None else "idle",
                "active_turn_id": (None if active_turn is None else str(active_turn["turn_id"])),
                "turn_count": 0 if turn_count is None else int(turn_count[0]),
                "item_count": 0 if item_count is None else int(item_count[0]),
                "binding": None if binding is None else self._row_dict(binding),
            }
        )
        return result

    def list_turns(self, task_id: str, user: dict[str, object]) -> list[dict[str, object]]:
        """Return ordered canonical Turns after Task visibility authorization."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_viewer(task_id, user)
            conversations = SqliteConversationRepository(conn)
            self._require_v3(conversations, task_id)
            return [self._row_dict(row) for row in conversations.list_turns(task_id)]

    def list_items(
        self,
        task_id: str,
        user: dict[str, object],
        *,
        turn_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Return ordered canonical Items for a Task or one of its Turns."""

        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_viewer(task_id, user)
            conversations = SqliteConversationRepository(conn)
            self._require_v3(conversations, task_id)
            if turn_id is None:
                rows = conversations.list_task_items(task_id)
            else:
                turn = conversations.turn_by_id(turn_id)
                if turn is None or str(turn["task_id"]) != task_id:
                    raise DomainNotFoundError(turn_id)
                rows = conversations.list_turn_items(turn_id)
            return [self._row_dict(row) for row in rows]

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, object]:
        result: dict[str, object] = dict(row)
        for key in tuple(result):
            if not key.endswith("_json"):
                continue
            value = result[key]
            if not isinstance(value, str):
                continue
            try:
                result[key.removesuffix("_json")] = json.loads(value)
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = value
        return result

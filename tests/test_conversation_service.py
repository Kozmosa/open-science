"""Focused transaction tests for the conversation-v3 application service."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

import ainrf.domain.conversation_service as conversation_service_module
from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import ProjectContextService, build_domain_modules
from ainrf.domain.conversation_contracts import (
    ApprovalStatus,
    ConversationContractError,
    ConversationErrorCode,
    ForkTransferMode,
    TaskWorkStatus,
    TurnItemActor,
    TurnItemType,
    TurnStatus,
)
from ainrf.domain.conversation_execution_repository import (
    SqliteConversationExecutionRepository,
)
from ainrf.domain.conversation_execution import (
    ConversationExecutionService,
    RuntimeExecutionClaim,
    SubmissionClaim,
)
from ainrf.domain.conversation_repository import SqliteConversationRepository
from ainrf.domain.conversation_service import ConversationApplicationService
from ainrf.domain.service import DomainConflictError, DomainPermissionError
from ainrf.domain.task_projection import TaskProjectionService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]

_USER: dict[str, object] = {"id": "user-1", "role": "researcher"}
_NOW = "2026-07-18T00:00:00+00:00"
_EXPIRY = "2099-07-18T01:00:00+00:00"


def _db_path(state_root: Path) -> Path:
    return state_root / "runtime" / "agentic_researcher.sqlite3"


def _insert_task(state_root: Path, task_id: str = "task-1") -> None:
    with closing(connect(_db_path(state_root))) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                connection_fingerprint, created_at, updated_at
            ) VALUES ('environment-legacy', 'local', 'user-1', 'Local', '{}', 'fp', ?, ?)""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT OR IGNORE INTO workspaces (
                workspace_id, label, owner_user_id, environment_id, canonical_path,
                created_at, updated_at
            ) VALUES ('workspace-legacy', 'legacy', 'user-1', 'environment-legacy',
                '/tmp', ?, ?)""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT OR IGNORE INTO projects (
                project_id, owner_user_id, name, status, created_at, updated_at
            ) VALUES ('project-legacy', 'user-1', 'Legacy', 'active', ?, ?)""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT OR IGNORE INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-legacy', 'workspace-legacy', 'active', 1, 'user-1', ?, ?)""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT OR IGNORE INTO project_context_versions (
                context_version_id, project_id, content, fingerprint, is_active,
                created_by_user_id, created_at, fragment_manifest_json
            ) VALUES ('context-version-legacy', 'project-legacy', 'Project context',
                'context-fingerprint', 1, 'user-1', ?, '[]')""",
            (_NOW,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO project_context_version_provenance (
                context_version_id, fragment_provenance_status, evidence_json, recorded_at
            ) VALUES ('context-version-legacy', 'verified', '{}', ?)""",
            (_NOW,),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at,
                owner_user_id
            ) VALUES (?, 'project-legacy', 'workspace-legacy', 'environment-legacy',
                'general', 'codex-app-server', 'queued', 'Conversation', 'test',
                ?, ?, 'user-1')
            """,
            (task_id, _NOW, _NOW),
        )
        conn.commit()


def _service(
    state_root: Path,
    *,
    notifier: Callable[[str], None] | None = None,
) -> ConversationApplicationService:
    service = ConversationApplicationService(state_root, dispatch_notifier=notifier)
    _insert_task(state_root)
    service.initialize_task("task-1", _USER)
    return service


def _insert_context_snapshot(
    state_root: Path, snapshot_id: str, *, content: str = "Context"
) -> None:
    with closing(connect(_db_path(state_root))) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO context_snapshots (
                   context_snapshot_id, context_version_id, fingerprint, content, created_at
               ) VALUES (?, 'context-version-legacy', ?, ?, ?)""",
            (snapshot_id, f"fingerprint-{snapshot_id}", content, _NOW),
        )
        conn.commit()


def _pin_task_snapshot(state_root: Path, snapshot_id: str, *, content: str = "Context") -> None:
    _insert_context_snapshot(state_root, snapshot_id, content=content)
    with closing(connect(_db_path(state_root))) as conn:
        conn.execute(
            """UPDATE tasks
               SET project_context_version_id = 'context-version-legacy',
                   project_context_snapshot_id = ?
               WHERE task_id = 'task-1'""",
            (snapshot_id,),
        )
        conn.commit()


def _submission_context_snapshot(state_root: Path, submission_id: str) -> str | None:
    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            "SELECT context_snapshot_ref FROM turn_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
    assert row is not None
    return None if row["context_snapshot_ref"] is None else str(row["context_snapshot_ref"])


def _submission_context_source(state_root: Path, submission_id: str) -> str:
    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            "SELECT context_snapshot_source FROM turn_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
    assert row is not None
    return str(row["context_snapshot_source"])


def _submission_to_delivering(state_root: Path, submission_id: str) -> None:
    with closing(connect(_db_path(state_root))) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        assert (
            repository.transition_submission(
                submission_id=submission_id,
                expected_status="queued",
                status="claimed",
                claimed_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        assert (
            repository.transition_submission(
                submission_id=submission_id,
                expected_status="claimed",
                status="delivering",
                claimed_at=_NOW,
                delivering_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        conn.commit()


def _accept_turn(
    state_root: Path,
    service: ConversationApplicationService,
    submission_id: str,
) -> str:
    _submission_to_delivering(state_root, submission_id)
    accepted = service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref=f"native-{submission_id}",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "provider-accepted"},
    )
    return str(accepted["turn_id"])


def _create_accepted_turn(state_root: Path, service: ConversationApplicationService) -> str:
    admission = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )
    return _accept_turn(state_root, service, str(admission["submission_id"]))


def _insert_runtime_and_approval(
    state_root: Path,
    turn_id: str,
    *,
    approval_id: str = "approval-1",
    expires_at: str = _EXPIRY,
) -> None:
    with closing(connect(_db_path(state_root))) as conn:
        turn = conn.execute(
            "SELECT native_turn_kind, native_turn_ref FROM task_turns WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert turn is not None
        repository = SqliteConversationExecutionRepository(conn)
        repository.insert_runtime_execution(
            runtime_execution_id="execution-1",
            task_id="task-1",
            turn_id=turn_id,
            execution_seq=1,
            runtime_generation=1,
            binding_id=None,
            native_runtime_kind="process",
            native_runtime_ref="runtime-1",
            native_turn_kind=str(turn["native_turn_kind"]),
            native_turn_ref=str(turn["native_turn_ref"]),
            evidence_json='{"source":"driver"}',
            created_at=_NOW,
            started_at=_NOW,
            updated_at=_NOW,
        )
        repository.insert_approval_request(
            approval_id=approval_id,
            task_id="task-1",
            turn_id=turn_id,
            runtime_execution_id="execution-1",
            runtime_generation=1,
            tool_call_ref="tool-call-1",
            request_json='{"tool":"shell"}',
            created_at=_NOW,
            expires_at=expires_at,
            updated_at=_NOW,
        )
        conn.commit()


def test_ordinary_task_projection_uses_turn_item_and_execution_authority(
    state_root: Path,
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    with closing(connect(_db_path(state_root))) as conn:
        turn = conn.execute(
            "SELECT native_turn_kind, native_turn_ref FROM task_turns WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert turn is not None
        execution = SqliteConversationExecutionRepository(conn)
        execution.insert_runtime_execution(
            runtime_execution_id="execution-projection",
            task_id="task-1",
            turn_id=turn_id,
            execution_seq=1,
            runtime_generation=1,
            binding_id=None,
            native_runtime_kind="process",
            native_runtime_ref="runtime-projection",
            native_turn_kind=str(turn["native_turn_kind"]),
            native_turn_ref=str(turn["native_turn_ref"]),
            evidence_json="{}",
            created_at=_NOW,
            started_at=_NOW,
            updated_at=_NOW,
        )
        assert (
            execution.transition_runtime_execution(
                runtime_execution_id="execution-projection",
                expected_status="starting",
                status="running",
                evidence_json="{}",
                updated_at=_NOW,
            )
            == 1
        )
        conn.commit()
    ConversationExecutionService(state_root).append_item(
        RuntimeExecutionClaim(
            runtime_execution_id="execution-projection",
            task_id="task-1",
            turn_id=turn_id,
            runtime_generation=1,
        ),
        item_type=TurnItemType.SYSTEM_NOTICE,
        actor=TurnItemActor.SYSTEM,
        payload={
            "usage": {
                "model": "fixture-model",
                "input_tokens": 7,
                "output_tokens": 3,
                "cost_usd": 0.25,
            }
        },
        native_provenance={},
    )

    projection = TaskProjectionService(state_root)
    task = projection.task("task-1", _USER)
    health = projection.health("task-1", _USER)
    usage = projection.token_usage_summary(_USER, include_archived=True)

    assert task["status"] == "running"
    assert task["latest_output_seq"] == 2
    assert "fixture-model" in str(task["token_usage_json"])
    assert health["engine_alive"] is True
    assert usage["total_tokens"] == 10


def test_task_metadata_and_cancel_stay_inside_conversation_interface(
    state_root: Path,
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    _insert_runtime_and_approval(state_root, turn_id)
    deferred = service.create_turn(
        "task-1",
        _USER,
        input={"text": "next"},
        idempotency_key="cancel-next",
        allow_next_turn=True,
    )

    with pytest.raises(ConversationContractError) as active_archive:
        service.archive_task("task-1", _USER, idempotency_key="archive-active")
    assert active_archive.value.code is ConversationErrorCode.ACTIVE_TURN_EXISTS

    cancelled = service.cancel_task("task-1", _USER, idempotency_key="cancel-1")
    assert cancelled["work_status"] == TaskWorkStatus.CANCELLED
    assert isinstance(cancelled["control_request_id"], str)
    assert cancelled["cancelled_submission_ids"] == [str(deferred["submission_id"])]
    titled = service.update_task_title(
        "task-1", _USER, title="Renamed Conversation", idempotency_key="title-1"
    )
    assert titled["task_id"] == "task-1"
    with closing(connect(_db_path(state_root))) as conn:
        assert (
            conn.execute(
                "SELECT work_status FROM conversation_task_states WHERE task_id = 'task-1'"
            ).fetchone()[0]
            == "cancelled"
        )
        control = conn.execute("SELECT kind, status FROM turn_control_requests").fetchone()
        next_turn = conn.execute(
            "SELECT status FROM next_turn_submissions WHERE submission_id = ?",
            (deferred["submission_id"],),
        ).fetchone()
        assert control is not None
        assert (control["kind"], control["status"]) == ("interrupt", "requested")
        assert next_turn is not None and next_turn["status"] == "cancelled"
        assert conn.execute("SELECT title FROM tasks WHERE task_id = 'task-1'").fetchone()[0] == (
            "Renamed Conversation"
        )


def test_cancel_task_cancels_queued_and_claimed_submissions_with_evidence(
    state_root: Path,
) -> None:
    service = _service(state_root)
    first = service.create_turn("task-1", _USER, input={"text": "first"}, idempotency_key="first")
    second = service.create_turn(
        "task-1", _USER, input={"text": "second"}, idempotency_key="second"
    )
    execution = ConversationExecutionService(state_root)
    claimed = execution.claim_next_submission()
    assert claimed is not None

    result = service.cancel_task("task-1", _USER, idempotency_key="cancel-pending")
    cancelled_submission_ids = result["cancelled_submission_ids"]
    assert isinstance(cancelled_submission_ids, list)
    assert set(cancelled_submission_ids) == {
        str(first["submission_id"]),
        str(second["submission_id"]),
    }
    with closing(connect(_db_path(state_root))) as conn:
        rows = conn.execute(
            "SELECT submission_id, status, finished_at, failure_code, "
            "delivery_evidence_json FROM turn_submissions ORDER BY submission_id"
        ).fetchall()
        state = conn.execute(
            "SELECT work_status FROM conversation_task_states WHERE task_id = 'task-1'"
        ).fetchone()
    assert state is not None and state["work_status"] == "cancelled"
    assert len(rows) == 2
    assert all(row["status"] == "cancelled" for row in rows)
    assert all(row["finished_at"] is not None for row in rows)
    assert all(row["failure_code"] == "task_cancelled_before_delivery" for row in rows)
    assert all(
        json.loads(str(row["delivery_evidence_json"]))["reason"] == "task_cancelled_before_delivery"
        for row in rows
    )


def test_cancel_ready_next_turn_then_reopen_allows_new_admission(state_root: Path) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    deferred = service.create_turn(
        "task-1",
        _USER,
        input={"text": "next"},
        idempotency_key="next-ready",
        allow_next_turn=True,
    )
    service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)

    cancelled = service.cancel_task("task-1", _USER, idempotency_key="cancel-ready")
    assert cancelled["cancelled_submission_ids"] == [str(deferred["submission_id"])]
    with closing(connect(_db_path(state_root))) as conn:
        next_turn = conn.execute(
            "SELECT status FROM next_turn_submissions WHERE submission_id = ?",
            (deferred["submission_id"],),
        ).fetchone()
        submission = conn.execute(
            "SELECT status FROM turn_submissions WHERE submission_id = ?",
            (deferred["submission_id"],),
        ).fetchone()
    assert next_turn is not None and next_turn["status"] == "cancelled"
    assert submission is not None and submission["status"] == "cancelled"

    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.OPEN, idempotency_key="reopen-ready"
    )
    replacement = service.create_turn(
        "task-1", _USER, input={"text": "replacement"}, idempotency_key="replacement"
    )
    assert replacement["status"] == "queued"


def test_cancel_and_claim_have_one_serialized_winner(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn("task-1", _USER, input={"text": "race"}, idempotency_key="race")

    def claim() -> object:
        return ConversationExecutionService(state_root).claim_next_submission()

    def cancel() -> dict[str, object]:
        return service.cancel_task("task-1", _USER, idempotency_key="race-cancel")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed, cancelled = pool.map(lambda operation: operation(), (claim, cancel))

    assert claimed is None or claimed.submission_id == admission["submission_id"]
    assert cancelled["work_status"] == TaskWorkStatus.CANCELLED
    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            "SELECT status FROM turn_submissions WHERE submission_id = ?",
            (admission["submission_id"],),
        ).fetchone()
    assert row is not None and row["status"] == "cancelled"


def test_closed_task_submission_is_not_claimable(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "closed"}, idempotency_key="closed-queue"
    )
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.COMPLETED, idempotency_key="close-queue"
    )

    assert ConversationExecutionService(state_root).claim_next_submission() is None
    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            "SELECT status FROM turn_submissions WHERE submission_id = ?",
            (admission["submission_id"],),
        ).fetchone()
    assert row is not None and row["status"] == "queued"


def test_cancel_after_begin_fences_acceptance_without_turn_or_runtime(
    state_root: Path,
) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "race"}, idempotency_key="accept-race"
    )
    execution = ConversationExecutionService(state_root)
    claim = execution.claim_next_submission()
    assert claim is not None
    execution.begin_delivery(claim.submission_id)
    service.cancel_task("task-1", _USER, idempotency_key="cancel-before-accept")

    with pytest.raises(ConversationContractError) as closed:
        execution.accept_and_open_execution(
            claim,
            engine_family="codex",
            engine_driver="codex-app-server",
            native_turn_kind="turn",
            native_turn_ref="native-race",
            native_runtime_kind="process",
            native_runtime_ref="runtime-race",
            evidence={"source": "race"},
        )
    assert closed.value.code is ConversationErrorCode.TASK_NOT_OPEN
    with closing(connect(_db_path(state_root))) as conn:
        before_fence = conn.execute(
            "SELECT status, finished_at, failure_code FROM turn_submissions "
            "WHERE submission_id = ?",
            (admission["submission_id"],),
        ).fetchone()
    assert before_fence is not None
    assert before_fence["status"] == "delivery_unknown"
    assert before_fence["finished_at"] is None
    assert before_fence["failure_code"] == "task_cancelled_during_delivery"
    execution.mark_delivery_unknown(
        claim.submission_id,
        failure_code="task_cancelled_during_delivery",
        evidence={
            "source": "test",
            "reason": "task_cancelled_during_delivery",
            "replay_forbidden": True,
        },
    )
    with closing(connect(_db_path(state_root))) as conn:
        submission = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = ?",
            (admission["submission_id"],),
        ).fetchone()
        turn_count = conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0]
        runtime_count = conn.execute("SELECT COUNT(*) FROM runtime_executions").fetchone()[0]
    assert submission is not None
    assert tuple(submission) == ("delivery_unknown", "task_cancelled_during_delivery")
    assert turn_count == 0
    assert runtime_count == 0


def test_admission_is_durable_idempotent_and_not_canonical_history(
    state_root: Path,
) -> None:
    observed: list[tuple[str, str]] = []

    def notifier(submission_id: str) -> None:
        with closing(connect(_db_path(state_root))) as conn:
            row = conn.execute(
                "SELECT status FROM turn_submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            assert row is not None
            observed.append((submission_id, str(row["status"])))

    service = _service(state_root, notifier=notifier)
    result = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )
    replay = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )

    assert replay == result
    assert observed == [(result["submission_id"], "queued")]
    with closing(connect(_db_path(state_root))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM turn_submissions").fetchone()[0] == 1

    with pytest.raises(DomainConflictError, match="different request"):
        service.create_turn("task-1", _USER, input={"text": "changed"}, idempotency_key="create-1")


def test_application_interface_reads_canonical_task_turns_and_items(state_root: Path) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)

    task = service.read_task("task-1", _USER)
    turns = service.list_turns("task-1", _USER)
    items = service.list_items("task-1", _USER, turn_id=turn_id)

    assert task["work_status"] == "open"
    assert task["runtime_status"] == "active"
    assert task["active_turn_id"] == turn_id
    assert task["turn_count"] == 1
    assert task["item_count"] == 1
    assert [turn["turn_id"] for turn in turns] == [turn_id]
    assert items[0]["item_type"] == "user_message"
    assert items[0]["payload"] == {"text": "hello"}


def test_item_reads_redact_project_collaborator_payload_without_rewriting_durable_evidence(
    state_root: Path,
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    with closing(connect(_db_path(state_root))) as conn:
        turn = conn.execute(
            "SELECT native_turn_kind, native_turn_ref FROM task_turns WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert turn is not None
        execution = SqliteConversationExecutionRepository(conn)
        execution.insert_runtime_execution(
            runtime_execution_id="execution-item-redaction",
            task_id="task-1",
            turn_id=turn_id,
            execution_seq=1,
            runtime_generation=1,
            binding_id=None,
            native_runtime_kind="process",
            native_runtime_ref="runtime-item-redaction",
            native_turn_kind=str(turn["native_turn_kind"]),
            native_turn_ref=str(turn["native_turn_ref"]),
            evidence_json="{}",
            created_at=_NOW,
            started_at=_NOW,
            updated_at=_NOW,
        )
        assert (
            execution.transition_runtime_execution(
                runtime_execution_id="execution-item-redaction",
                expected_status="starting",
                status="running",
                evidence_json="{}",
                updated_at=_NOW,
            )
            == 1
        )
        conn.execute(
            """
            INSERT INTO project_members (
                project_id, user_id, role, can_publish, created_at, updated_at
            ) VALUES ('project-legacy', 'collaborator', 'viewer', 0, ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.commit()

    payload = {
        "message": "shared dialogue",
        "credential": "credential-secret",
        "nested": [
            {
                "token": "token-secret",
                "headers": {"Authorization": "Bearer authorization-secret"},
            },
            "Authorization: Bearer inline-secret",
            "/home/ainrf_tenants/user-1/workspace/output.txt",
        ],
    }
    ConversationExecutionService(state_root).append_item(
        RuntimeExecutionClaim(
            runtime_execution_id="execution-item-redaction",
            task_id="task-1",
            turn_id=turn_id,
            runtime_generation=1,
        ),
        item_type=TurnItemType.SYSTEM_NOTICE,
        actor=TurnItemActor.SYSTEM,
        payload=payload,
        native_provenance={},
    )

    owner = service.list_items("task-1", _USER, turn_id=turn_id)
    admin = service.list_items("task-1", {"id": "admin", "role": "admin"}, turn_id=turn_id)
    collaborator = service.list_items(
        "task-1", {"id": "collaborator", "role": "researcher"}, turn_id=turn_id
    )
    owner_item = next(item for item in owner if item["item_type"] == "system_notice")
    admin_item = next(item for item in admin if item["item_type"] == "system_notice")
    collaborator_item = next(item for item in collaborator if item["item_type"] == "system_notice")

    assert owner_item["payload"] == payload
    assert admin_item["payload"] == payload
    assert collaborator_item["payload"] == {
        "message": "shared dialogue",
        "credential": "[REDACTED]",
        "nested": [
            {
                "token": "[REDACTED]",
                "headers": {"Authorization": "[REDACTED]"},
            },
            "Authorization: [REDACTED]",
            "[REDACTED_PATH]",
        ],
    }

    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM turn_items
            WHERE task_id = ? AND turn_id = ? AND item_type = 'system_notice'
            """,
            ("task-1", turn_id),
        ).fetchone()
        assert row is not None
        assert json.loads(str(row["payload_json"])) == payload


def test_create_task_atomically_uses_conversation_authority_without_attempt(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = build_domain_modules(state_root, artifact_sha=committed_v2_state)
    environment = domain.environments.create_environment(
        admin, alias="host", display_name="Host", connection={}
    )
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="conversation task test",
    )
    project = domain.projects.create_project(owner, name="Project")
    workspace = domain.workspaces.create_workspace(
        owner,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/conversation-task",
        label="Task",
    )
    domain.projects.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        owner,
        idempotency_key="link",
    )
    context = ProjectContextService(state_root, artifact_sha=committed_v2_state)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    service = ConversationApplicationService(state_root, artifact_sha=committed_v2_state)

    created = service.create_task(
        owner,
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
        title="Task",
        prompt="Prompt",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="create",
    )
    replay = service.create_task(
        owner,
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
        title="Task",
        prompt="Prompt",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="create",
    )

    assert replay == created
    with closing(connect(_db_path(state_root))) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM conversation_task_authorities WHERE task_id = ?",
                (created["task_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM turn_submissions WHERE task_id = ?", (created["task_id"],)
            ).fetchone()[0]
            == 1
        )


def test_replay_requires_current_authorization(state_root: Path) -> None:
    service = _service(state_root)
    service.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="create-1")
    with closing(connect(_db_path(state_root))) as conn:
        conn.execute("UPDATE tasks SET owner_user_id = 'user-2' WHERE task_id = 'task-1'")
        conn.commit()

    with pytest.raises(DomainPermissionError):
        service.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="create-1")


def test_create_and_retry_key_reuse_is_a_stable_conflict(state_root: Path) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)

    with pytest.raises(DomainConflictError, match="another Turn admission action"):
        service.retry_turn(
            "task-1",
            turn_id,
            _USER,
            input={"text": "retry"},
            idempotency_key="create-1",
        )


def test_turn_admissions_inherit_the_current_task_context_pin_across_lifecycle(
    state_root: Path,
) -> None:
    service = _service(state_root)
    _pin_task_snapshot(state_root, "snapshot-context-v1")

    first = service.create_turn(
        "task-1", _USER, input={"text": "first"}, idempotency_key="context-first"
    )
    assert _submission_context_snapshot(state_root, str(first["submission_id"])) == (
        "snapshot-context-v1"
    )
    first_turn = _accept_turn(state_root, service, str(first["submission_id"]))
    service.finish_turn("task-1", first_turn, status=TurnStatus.COMPLETED)

    later = service.create_turn(
        "task-1", _USER, input={"text": "later"}, idempotency_key="context-later"
    )
    assert _submission_context_snapshot(state_root, str(later["submission_id"])) == (
        "snapshot-context-v1"
    )
    later_turn = _accept_turn(state_root, service, str(later["submission_id"]))
    service.finish_turn("task-1", later_turn, status=TurnStatus.COMPLETED)

    retry = service.retry_turn(
        "task-1",
        later_turn,
        _USER,
        input={"text": "retry"},
        idempotency_key="context-retry",
    )
    assert _submission_context_snapshot(state_root, str(retry["submission_id"])) == (
        "snapshot-context-v1"
    )
    retry_turn = _accept_turn(state_root, service, str(retry["submission_id"]))
    service.finish_turn("task-1", retry_turn, status=TurnStatus.COMPLETED)

    _pin_task_snapshot(state_root, "snapshot-context-v2")
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.COMPLETED, idempotency_key="context-close"
    )
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.OPEN, idempotency_key="context-reopen"
    )
    reopened = service.create_turn(
        "task-1", _USER, input={"text": "reopened"}, idempotency_key="context-reopened"
    )
    assert _submission_context_snapshot(state_root, str(reopened["submission_id"])) == (
        "snapshot-context-v2"
    )


def test_explicit_context_override_is_project_scoped_and_survives_context_confirmation(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    service = _service(state_root)
    _pin_task_snapshot(state_root, "snapshot-context-v1")
    _insert_context_snapshot(state_root, "snapshot-context-override", content="Override")

    inherited = service.create_turn(
        "task-1", _USER, input={"text": "inherited"}, idempotency_key="context-inherited"
    )
    override = service.create_turn(
        "task-1",
        _USER,
        input={"text": "override"},
        idempotency_key="context-override",
        context_snapshot_ref="snapshot-context-override",
    )
    explicit_current_pin = service.create_turn(
        "task-1",
        _USER,
        input={"text": "explicit current pin"},
        idempotency_key="context-explicit-current-pin",
        context_snapshot_ref="snapshot-context-v1",
    )
    assert _submission_context_snapshot(state_root, str(inherited["submission_id"])) == (
        "snapshot-context-v1"
    )
    assert _submission_context_snapshot(state_root, str(override["submission_id"])) == (
        "snapshot-context-override"
    )
    assert _submission_context_snapshot(state_root, str(explicit_current_pin["submission_id"])) == (
        "snapshot-context-v1"
    )
    assert _submission_context_source(state_root, str(inherited["submission_id"])) == "task_pin"
    assert (
        _submission_context_source(state_root, str(override["submission_id"]))
        == "submission_override"
    )
    assert (
        _submission_context_source(state_root, str(explicit_current_pin["submission_id"]))
        == "submission_override"
    )

    with closing(connect(_db_path(state_root))) as conn:
        task = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = 'task-1'"
        ).fetchone()
    assert task is not None and task["project_context_snapshot_id"] == "snapshot-context-v1"

    context = ProjectContextService(state_root, artifact_sha=committed_v2_state)
    context.save_draft("project-legacy", "Confirmed context", _USER)
    context.publish("project-legacy", _USER, idempotency_key="context-publish")
    preview = context.preview_task_context_update("task-1", "project-legacy", _USER)
    confirmed = context.confirm_task_context_update(
        "task-1",
        "project-legacy",
        str(preview["preview_id"]),
        _USER,
        idempotency_key="context-confirm",
    )

    assert _submission_context_snapshot(state_root, str(inherited["submission_id"])) == (
        str(confirmed["context_snapshot_id"])
    )
    assert _submission_context_snapshot(state_root, str(override["submission_id"])) == (
        "snapshot-context-override"
    )
    assert _submission_context_snapshot(state_root, str(explicit_current_pin["submission_id"])) == (
        "snapshot-context-v1"
    )
    with closing(connect(_db_path(state_root))) as conn:
        task = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = 'task-1'"
        ).fetchone()
    assert (
        task is not None and task["project_context_snapshot_id"] == confirmed["context_snapshot_id"]
    )


def test_terminal_evidence_validation_and_replay(state_root: Path) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)

    with pytest.raises(ConversationContractError) as missing_code:
        service.finish_turn("task-1", turn_id, status=TurnStatus.FAILED)
    assert missing_code.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION
    with pytest.raises(ConversationContractError) as unexpected_code:
        service.finish_turn(
            "task-1",
            turn_id,
            status=TurnStatus.COMPLETED,
            failure_code="unexpected",
        )
    assert unexpected_code.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION

    result = service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)
    assert service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED) == result
    with pytest.raises(ConversationContractError) as contradiction:
        service.finish_turn(
            "task-1", turn_id, status=TurnStatus.FAILED, failure_code="runtime_error"
        )
    assert contradiction.value.code is ConversationErrorCode.TURN_NOT_ACTIVE


def test_acceptance_rejects_delivery_after_task_closure(
    state_root: Path,
) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )
    submission_id = str(admission["submission_id"])
    _submission_to_delivering(state_root, submission_id)
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.COMPLETED, idempotency_key="close"
    )

    with pytest.raises(ConversationContractError) as wrong_engine:
        service.accept_submission(
            submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-1",
            engine_family="claude",
            engine_driver="claude-code",
            contract_version=1,
            delivery_evidence={"receipt": "accepted"},
        )
    assert wrong_engine.value.code is ConversationErrorCode.TASK_NOT_OPEN

    with closing(connect(_db_path(state_root))) as conn:
        submission = conn.execute(
            "SELECT status, finished_at, failure_code FROM turn_submissions "
            "WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        assert submission is not None
        assert tuple(submission) == ("delivering", None, None)
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 0


def test_delivered_acceptance_replay_survives_task_closure(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="closed-replay"
    )
    submission_id = str(admission["submission_id"])
    _submission_to_delivering(state_root, submission_id)
    accepted = service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-closed-replay",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "accepted"},
    )
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.COMPLETED, idempotency_key="close-replay"
    )

    replay = service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-closed-replay",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "accepted"},
    )
    assert replay == accepted
    with closing(connect(_db_path(state_root))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 1


def test_acceptance_rejects_active_binding_mismatch(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )
    submission_id = str(admission["submission_id"])
    with closing(connect(_db_path(state_root))) as conn:
        repository = SqliteConversationRepository(conn)
        repository.insert_binding(
            binding_id="binding-1",
            task_id="task-1",
            binding_seq=repository.next_binding_seq("task-1"),
            engine_family="codex",
            engine_driver="codex-app-server",
            native_conversation_kind="thread",
            native_conversation_ref="thread-1",
            contract_version=1,
            provider_profile_ref=None,
            provider_profile_version=None,
            provider_profile_fingerprint=None,
            provenance_json="{}",
            validation_evidence_json="{}",
            created_at=_NOW,
            validated_at=_NOW,
        )
        conn.commit()
    _submission_to_delivering(state_root, submission_id)

    with pytest.raises(ConversationContractError) as mismatch:
        service.accept_submission(
            submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-1",
            engine_family="codex",
            engine_driver="codex-app-server",
            contract_version=1,
            binding_id="binding-other",
            delivery_evidence={"receipt": "accepted"},
        )
    assert mismatch.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH


def test_closed_task_cancels_waiting_next_turn(state_root: Path) -> None:
    notified: list[str] = []
    service = _service(state_root, notifier=notified.append)
    turn_id = _create_accepted_turn(state_root, service)
    deferred = service.create_turn(
        "task-1",
        _USER,
        input={"text": "next"},
        idempotency_key="next",
        allow_next_turn=True,
    )
    before_finish = list(notified)
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.CANCELLED, idempotency_key="close"
    )

    result = service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)
    assert result["promoted_submission_id"] is None
    assert notified == before_finish
    with closing(connect(_db_path(state_root))) as conn:
        submission = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = ?",
            (deferred["submission_id"],),
        ).fetchone()
        next_turn = conn.execute(
            "SELECT status FROM next_turn_submissions WHERE submission_id = ?",
            (deferred["submission_id"],),
        ).fetchone()
        assert submission is not None and next_turn is not None
        assert (submission["status"], submission["failure_code"]) == (
            "cancelled",
            "task_closed_before_promotion",
        )
        assert next_turn["status"] == "cancelled"


def test_fork_confirmation_uses_canonical_revision_and_metrics(state_root: Path) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)

    with pytest.raises(ConversationContractError) as metrics:
        service.preview_fork(
            "task-1",
            _USER,
            target_engine_family="claude",
            transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
            transfer_range={"through_turn": turn_id},
            metrics={"message_count": 999},
            disclosure={},
            idempotency_key="bad-metrics",
        )
    assert metrics.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH

    preview = service.preview_fork(
        "task-1",
        _USER,
        target_engine_family="claude",
        transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
        transfer_range={"through_turn": turn_id},
        metrics={"truncated": False},
        disclosure={},
        idempotency_key="preview",
    )
    with closing(connect(_db_path(state_root))) as conn:
        repository = SqliteConversationRepository(conn)
        repository.insert_turn_item(
            item_id="late-item",
            task_id="task-1",
            turn_id=turn_id,
            task_item_seq=repository.next_task_item_seq("task-1"),
            turn_item_seq=repository.next_turn_item_seq(turn_id),
            envelope_type="conversation.item",
            envelope_version=1,
            item_type="agent_message",
            actor="agent",
            payload_json='{"text":"late"}',
            native_provenance_json="{}",
            native_dedupe_scope="fixture",
            native_item_id="late",
            parent_item_id=None,
            call_item_id=None,
            occurred_at=_NOW,
            ingested_at=_NOW,
            persisted_at=_NOW,
        )
        conn.commit()

    with pytest.raises(ConversationContractError) as stale:
        service.confirm_fork(
            "task-1",
            str(preview["preview_id"]),
            _USER,
            preview_hash=str(preview["preview_hash"]),
            source_revision=str(preview["source_revision"]),
            transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
            truncation_acknowledged=False,
            full_transcript_confirmed=True,
            idempotency_key="confirm",
        )
    assert stale.value.code is ConversationErrorCode.FORK_CONFIRMATION_REQUIRED


def test_legacy_and_closed_tasks_reject_turn_admission(state_root: Path) -> None:
    service = ConversationApplicationService(state_root)
    _insert_task(state_root)
    with pytest.raises(ConversationContractError) as legacy:
        service.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="legacy")
    assert legacy.value.code is ConversationErrorCode.MIGRATION_REQUIRED

    service.initialize_task("task-1", _USER)
    service.update_work_status(
        "task-1",
        _USER,
        status=TaskWorkStatus.COMPLETED,
        idempotency_key="complete",
    )
    with pytest.raises(ConversationContractError) as closed:
        service.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="closed")
    assert closed.value.code is ConversationErrorCode.TASK_NOT_OPEN

    reopened = service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.OPEN, idempotency_key="reopen"
    )
    assert reopened["revision"] == 3
    assert (
        service.create_turn(
            "task-1", _USER, input={"text": "hello"}, idempotency_key="after-reopen"
        )["status"]
        == "queued"
    )


def test_work_status_rejects_noop_and_turn_completion_does_not_change_it(
    state_root: Path,
) -> None:
    service = _service(state_root)
    with pytest.raises(ConversationContractError) as noop:
        service.update_work_status(
            "task-1", _USER, status=TaskWorkStatus.OPEN, idempotency_key="noop"
        )
    assert noop.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION

    turn_id = _create_accepted_turn(state_root, service)
    service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)
    with closing(connect(_db_path(state_root))) as conn:
        state = conn.execute(
            "SELECT work_status, revision FROM conversation_task_states WHERE task_id = 'task-1'"
        ).fetchone()
        assert state is not None
        assert (state["work_status"], state["revision"]) == ("open", 1)


def test_explicit_complete_reopen_preserves_pending_submission_and_idempotency(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "complete me"}, idempotency_key="complete-admission"
    )
    timestamps = iter(
        (
            "2026-08-10T20:30:00+00:00",
            "2026-08-10T20:30:01+00:00",
            "2026-08-10T20:30:02+00:00",
            "2026-08-10T20:30:03+00:00",
        )
    )
    monkeypatch.setattr(conversation_service_module, "_now", lambda: next(timestamps))

    completed = service.complete_task("task-1", _USER, idempotency_key="complete-explicit")
    completed_view = service.read_task("task-1", _USER)
    replay = service.complete_task("task-1", _USER, idempotency_key="complete-explicit")
    replay_view = service.read_task("task-1", _USER)
    assert completed == replay
    assert completed["work_status"] == TaskWorkStatus.COMPLETED
    assert completed_view["updated_at"] == "2026-08-10T20:30:00+00:00"
    assert replay_view["updated_at"] == completed_view["updated_at"]
    with closing(connect(_db_path(state_root))) as conn:
        submission = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = ?",
            (admission["submission_id"],),
        ).fetchone()
    assert submission is not None
    assert tuple(submission) == ("queued", None)

    reopened = service.reopen_task("task-1", _USER, idempotency_key="reopen-explicit")
    reopened_view = service.read_task("task-1", _USER)
    assert reopened["work_status"] == TaskWorkStatus.OPEN
    assert reopened_view["updated_at"] == "2026-08-10T20:30:02+00:00"
    replacement = service.create_turn(
        "task-1", _USER, input={"text": "after reopen"}, idempotency_key="after-reopen-explicit"
    )
    assert replacement["status"] == "queued"


def test_explicit_complete_does_not_interrupt_active_turn(
    state_root: Path,
) -> None:
    service = _service(state_root)
    active_turn = _create_accepted_turn(state_root, service)
    completed = service.complete_task("task-1", _USER, idempotency_key="complete-active")
    assert completed["work_status"] == TaskWorkStatus.COMPLETED
    with closing(connect(_db_path(state_root))) as conn:
        state = conn.execute(
            "SELECT work_status FROM conversation_task_states WHERE task_id = 'task-1'"
        ).fetchone()
        turn = conn.execute(
            "SELECT status FROM task_turns WHERE turn_id = ?", (active_turn,)
        ).fetchone()
    assert state is not None and state["work_status"] == TaskWorkStatus.COMPLETED
    assert turn is not None and turn["status"] == TurnStatus.IN_PROGRESS
    service.reopen_task("task-1", _USER, idempotency_key="reopen-active")
    service.finish_turn("task-1", active_turn, status=TurnStatus.COMPLETED)
    assert service.read_task("task-1", _USER)["work_status"] == TaskWorkStatus.OPEN


def test_acceptance_materializes_once_and_rejects_secret_evidence(
    state_root: Path,
) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "hello"}, idempotency_key="create-1"
    )
    submission_id = str(admission["submission_id"])
    _submission_to_delivering(state_root, submission_id)

    with pytest.raises(ConversationContractError) as secret:
        service.accept_submission(
            submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-turn-1",
            engine_family="codex",
            engine_driver="codex-app-server",
            contract_version=1,
            delivery_evidence={"nested": {"authorization": "Bearer token"}},
        )
    assert secret.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH

    with pytest.raises(ConversationContractError) as bearer:
        service.accept_submission(
            submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-turn-1",
            engine_family="codex",
            engine_driver="codex-app-server",
            contract_version=1,
            delivery_evidence={"receipt": "Bearer token"},
        )
    assert bearer.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH

    result = service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "accepted"},
    )
    replay = service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "accepted"},
    )
    assert replay == result
    with closing(connect(_db_path(state_root))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 1
        item = conn.execute("SELECT * FROM turn_items").fetchone()
        assert item is not None
        assert item["item_type"] == "user_message"
        assert item["payload_json"] == '{"text":"hello"}'


def test_delivered_without_runtime_recovers_atomically_and_idempotently(
    state_root: Path,
) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "recover"}, idempotency_key="recover-runtime"
    )
    submission_id = str(admission["submission_id"])
    _submission_to_delivering(state_root, submission_id)
    service.accept_submission(
        submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-recover",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"receipt": "accepted"},
    )
    with closing(connect(_db_path(state_root))) as conn:
        row = conn.execute(
            "SELECT task_id, reserved_turn_id, input_json, context_snapshot_ref "
            "FROM turn_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
    assert row is not None
    claim = SubmissionClaim(
        submission_id=submission_id,
        task_id=str(row["task_id"]),
        reserved_turn_id=str(row["reserved_turn_id"]),
        input=json.loads(str(row["input_json"])),
        context_snapshot_ref=(
            None if row["context_snapshot_ref"] is None else str(row["context_snapshot_ref"])
        ),
    )
    execution = ConversationExecutionService(state_root)
    first = execution.accept_and_open_execution(
        claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_turn_kind="turn",
        native_turn_ref="native-recover",
        native_runtime_kind="process",
        native_runtime_ref="runtime-recover",
        evidence={"source": "recovery"},
    )
    second = execution.accept_and_open_execution(
        claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_turn_kind="turn",
        native_turn_ref="native-recover",
        native_runtime_kind="process",
        native_runtime_ref="runtime-recover",
        evidence={"source": "recovery-replay"},
    )
    assert second == first
    with closing(connect(_db_path(state_root))) as conn:
        runtime_rows = conn.execute(
            "SELECT runtime_execution_id, status FROM runtime_executions WHERE turn_id = ?",
            (str(admission["reserved_turn_id"]),),
        ).fetchall()
    assert len(runtime_rows) == 1
    assert runtime_rows[0]["status"] == "running"


def test_cancel_reopen_permanently_fences_old_delivery_claim(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1", _USER, input={"text": "fenced"}, idempotency_key="fenced-delivery"
    )
    submission_id = str(admission["submission_id"])
    _submission_to_delivering(state_root, submission_id)
    cancelled = service.cancel_task("task-1", _USER, idempotency_key="fence-cancel")
    assert cancelled["delivery_unknown_submission_ids"] == [submission_id]
    service.update_work_status(
        "task-1", _USER, status=TaskWorkStatus.OPEN, idempotency_key="fence-reopen"
    )

    with pytest.raises(ConversationContractError) as fenced:
        service.accept_submission(
            submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-fenced",
            engine_family="codex",
            engine_driver="codex-app-server",
            contract_version=1,
            delivery_evidence={"receipt": "accepted"},
        )
    assert fenced.value.code is ConversationErrorCode.DELIVERY_UNKNOWN
    with closing(connect(_db_path(state_root))) as conn:
        submission = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 0
    assert submission is not None
    assert tuple(submission) == ("delivery_unknown", "task_cancelled_during_delivery")


def test_runtime_native_identity_conflict_is_domain_error_and_rolls_back(
    state_root: Path,
) -> None:
    service = _service(state_root)
    service.create_turn("task-1", _USER, input={"text": "first"}, idempotency_key="runtime-owner")
    execution = ConversationExecutionService(state_root)
    first_claim = execution.claim_next_submission()
    assert first_claim is not None
    execution.begin_delivery(first_claim.submission_id)
    execution.accept_and_open_execution(
        first_claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_turn_kind="turn",
        native_turn_ref="native-runtime-owner",
        native_runtime_kind="process",
        native_runtime_ref="global-runtime-1",
        evidence={"source": "owner"},
    )

    _insert_task(state_root, "task-2")
    service.initialize_task("task-2", _USER)
    second = service.create_turn(
        "task-2", _USER, input={"text": "second"}, idempotency_key="runtime-conflict"
    )
    second_claim = execution.claim_next_submission()
    assert second_claim is not None
    assert second_claim.submission_id == second["submission_id"]
    execution.begin_delivery(second_claim.submission_id)
    with pytest.raises(DomainConflictError, match="another Turn"):
        execution.accept_and_open_execution(
            second_claim,
            engine_family="codex",
            engine_driver="codex-app-server",
            native_turn_kind="turn",
            native_turn_ref="native-runtime-conflict",
            native_runtime_kind="process",
            native_runtime_ref="global-runtime-1",
            evidence={"source": "conflict"},
        )
    with closing(connect(_db_path(state_root))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM runtime_executions").fetchone()[0] == 1
        submission = conn.execute(
            "SELECT status FROM turn_submissions WHERE submission_id = ?",
            (second["submission_id"],),
        ).fetchone()
    assert submission is not None and submission["status"] == "delivering"


def test_active_turn_retry_and_next_turn_semantics(state_root: Path) -> None:
    notified: list[str] = []
    service = _service(state_root, notifier=notified.append)
    turn_id = _create_accepted_turn(state_root, service)

    with pytest.raises(ConversationContractError) as active:
        service.create_turn("task-1", _USER, input={"text": "second"}, idempotency_key="second")
    assert active.value.code is ConversationErrorCode.ACTIVE_TURN_EXISTS
    with pytest.raises(ConversationContractError) as retry_active:
        service.retry_turn(
            "task-1",
            turn_id,
            _USER,
            input={"text": "retry"},
            idempotency_key="retry-active",
        )
    assert retry_active.value.code is ConversationErrorCode.TURN_NOT_ACTIVE

    deferred = service.create_turn(
        "task-1",
        _USER,
        input={"text": "next"},
        idempotency_key="next",
        allow_next_turn=True,
    )
    assert deferred["intent"] == "next_turn"
    before_finish = list(notified)
    finished = service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)
    assert finished["promoted_submission_id"] == deferred["submission_id"]
    assert notified == [*before_finish, str(deferred["submission_id"])]

    with pytest.raises(ConversationContractError) as reserved:
        service.create_turn("task-1", _USER, input={"text": "overtake"}, idempotency_key="overtake")
    assert reserved.value.code is ConversationErrorCode.ACTIVE_TURN_EXISTS

    next_turn_id = _accept_turn(state_root, service, str(deferred["submission_id"]))
    service.finish_turn("task-1", next_turn_id, status=TurnStatus.COMPLETED)
    retry = service.retry_turn(
        "task-1",
        turn_id,
        _USER,
        input={"text": "retry"},
        idempotency_key="retry-terminal",
    )
    assert retry["intent"] == "retry"


def test_controls_and_approvals_are_runtime_scoped_and_idempotent(
    state_root: Path,
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    _insert_runtime_and_approval(state_root, turn_id)
    service.update_work_status(
        "task-1",
        _USER,
        status=TaskWorkStatus.COMPLETED,
        idempotency_key="close-with-active-turn",
    )

    steer = service.request_steer(
        "task-1",
        turn_id,
        _USER,
        payload={"text": "focus", "secret_topic": "credential hygiene"},
        idempotency_key="steer-1",
    )
    assert steer["status"] == "requested"
    interrupt = service.request_interrupt(
        "task-1",
        turn_id,
        _USER,
        idempotency_key="interrupt-1",
    )
    assert interrupt["expected_turn_id"] == turn_id

    decision = service.resolve_approval(
        "task-1",
        "approval-1",
        _USER,
        status=ApprovalStatus.APPROVED,
        runtime_execution_id="execution-1",
        runtime_generation=1,
        tool_call_ref="tool-call-1",
        decision={"scope": "once"},
        idempotency_key="approval-1",
    )
    replay = service.resolve_approval(
        "task-1",
        "approval-1",
        _USER,
        status=ApprovalStatus.APPROVED,
        runtime_execution_id="execution-1",
        runtime_generation=1,
        tool_call_ref="tool-call-1",
        decision={"scope": "once"},
        idempotency_key="approval-1",
    )
    assert replay == decision


def test_approval_expiry_compares_rfc3339_offsets_chronologically(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    _insert_runtime_and_approval(
        state_root,
        turn_id,
        expires_at="2026-07-18T01:30:00+01:00",
    )
    monkeypatch.setattr(
        conversation_service_module,
        "_now",
        lambda: "2026-07-18T00:45:00+00:00",
    )

    with pytest.raises(ConversationContractError) as expired:
        service.resolve_approval(
            "task-1",
            "approval-1",
            _USER,
            status=ApprovalStatus.APPROVED,
            runtime_execution_id="execution-1",
            runtime_generation=1,
            tool_call_ref="tool-call-1",
            decision={"scope": "once"},
            idempotency_key="approval-expired-offset",
        )
    assert expired.value.code is ConversationErrorCode.RUNTIME_LOST


def test_fork_preview_confirmation_binds_revision_mode_and_disclosures(
    state_root: Path,
) -> None:
    service = _service(state_root)
    turn_id = _create_accepted_turn(state_root, service)
    service.finish_turn("task-1", turn_id, status=TurnStatus.COMPLETED)
    preview = service.preview_fork(
        "task-1",
        _USER,
        target_engine_family="claude",
        transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
        transfer_range={"through_turn": turn_id},
        metrics={
            "message_count": 1,
            "turn_count": 1,
            "item_count": 1,
            "character_count": 5,
            "utf8_byte_count": 5,
            "estimated_token_count": 2,
            "token_estimator": "fixture-v1",
            "truncated": True,
        },
        disclosure={"reasoning": "summaries-only"},
        idempotency_key="preview-1",
    )

    with pytest.raises(ConversationContractError) as missing_confirmation:
        service.confirm_fork(
            "task-1",
            str(preview["preview_id"]),
            _USER,
            preview_hash=str(preview["preview_hash"]),
            source_revision=str(preview["source_revision"]),
            transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
            truncation_acknowledged=False,
            full_transcript_confirmed=False,
            idempotency_key="confirm-invalid",
        )
    assert missing_confirmation.value.code is ConversationErrorCode.FORK_CONFIRMATION_REQUIRED

    confirmed = service.confirm_fork(
        "task-1",
        str(preview["preview_id"]),
        _USER,
        preview_hash=str(preview["preview_hash"]),
        source_revision=str(preview["source_revision"]),
        transfer_mode=ForkTransferMode.FULL_TRANSCRIPT,
        truncation_acknowledged=True,
        full_transcript_confirmed=True,
        idempotency_key="confirm-1",
    )
    assert confirmed["status"] == "transferred"
    with closing(connect(_db_path(state_root))) as conn:
        target = conn.execute(
            "SELECT harness_engine, status FROM tasks WHERE task_id = ?",
            (confirmed["target_task_id"],),
        ).fetchone()
        submission = conn.execute(
            "SELECT task_id, status FROM turn_submissions WHERE submission_id = ?",
            (confirmed["submission_id"],),
        ).fetchone()
    assert target["harness_engine"] == "agent-sdk"
    assert target["status"] == "queued"
    assert submission["task_id"] == confirmed["target_task_id"]
    assert submission["status"] == "queued"


def test_no_turn_fork_uses_persisted_harness_engine_not_caller_metrics(
    state_root: Path,
) -> None:
    service = _service(state_root)
    preview = service.preview_fork(
        "task-1",
        _USER,
        target_engine_family="claude",
        transfer_mode=ForkTransferMode.CONTEXT_ONLY,
        transfer_range={},
        metrics={
            "source_engine_family": "claude",
            "message_count": 0,
            "turn_count": 0,
            "item_count": 0,
            "character_count": 0,
            "utf8_byte_count": 0,
            "estimated_token_count": 0,
        },
        disclosure={},
        idempotency_key="preview-no-turn",
    )
    assert preview["source_engine_family"] == "codex"

    with closing(connect(_db_path(state_root))) as conn:
        conn.execute("UPDATE tasks SET harness_engine = 'unknown-engine' WHERE task_id = 'task-1'")
        conn.commit()
    with pytest.raises(ConversationContractError) as unknown:
        service.preview_fork(
            "task-1",
            _USER,
            target_engine_family="claude",
            transfer_mode=ForkTransferMode.CONTEXT_ONLY,
            transfer_range={},
            metrics={},
            disclosure={},
            idempotency_key="preview-unknown-engine",
        )
    assert unknown.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH


def test_user_input_is_not_treated_as_provider_evidence(state_root: Path) -> None:
    service = _service(state_root)
    admission = service.create_turn(
        "task-1",
        _USER,
        input={"text": "Explain credential rotation", "secret_topic": "education"},
        idempotency_key="ordinary-user-input",
    )
    assert admission["status"] == "queued"


def test_maintenance_fence_blocks_service_mutations(state_root: Path) -> None:
    service = _service(state_root)
    with closing(connect(_db_path(state_root))) as conn:
        conn.execute("UPDATE domain_maintenance_state SET is_active = 1 WHERE singleton = 1")
        conn.commit()

    from ainrf.domain_control import MaintenanceModeError

    with pytest.raises(MaintenanceModeError):
        service.create_turn("task-1", _USER, input={"text": "blocked"}, idempotency_key="blocked")

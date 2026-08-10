from __future__ import annotations

import asyncio
import json
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect, run_pending
from ainrf.domain import OverviewSnapshotService
from ainrf.domain.conversation_contracts import (
    CapabilitySupport,
    ConversationContractError,
    ConversationErrorCode,
    TaskWorkStatus,
    TurnStatus,
)
from ainrf.domain.conversation_execution import (
    ConversationExecutionService,
    RuntimeExecutionClaim,
    SubmissionClaim,
)
from ainrf.domain.conversation_execution_repository import SqliteConversationExecutionRepository
from ainrf.domain.conversation_service import ConversationApplicationService
from ainrf.domain.conversation_worker import ConversationDispatcher, ConversationWorkerRuntime
from ainrf.domain_control import DomainMaintenanceService
from ainrf.domain.service import DomainConflictError
from ainrf.harness_engine.base import EngineEvent, ExecutionContext, HarnessEngineType
from ainrf.harness_engine.conversation_adapter import (
    ControlReceipt,
    ConversationRuntimeAdapter,
    NativeAcceptanceIdentity,
)
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine, CodexSession
from ainrf.harness_engine.session_state import SessionCheckpoint

pytestmark = [pytest.mark.engine]

_USER: dict[str, object] = {"id": "user-1", "role": "user"}


class FakeRuntimeAdapter(ConversationRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(CodexAppServerEngine())

    def native_conversation_identity(
        self,
        *,
        runtime_launch_key: str,
        fallback_task_id: str,
    ) -> tuple[str, str]:
        _ = fallback_task_id
        return "thread", f"thread-{runtime_launch_key}"

    def native_acceptance_identity(
        self,
        *,
        runtime_launch_key: str,
        fallback_task_id: str,
        fallback_turn_id: str,
    ) -> NativeAcceptanceIdentity | None:
        _ = fallback_task_id
        return NativeAcceptanceIdentity(
            conversation_kind="thread",
            conversation_ref=f"thread-{runtime_launch_key}",
            turn_kind="turn",
            turn_ref=fallback_turn_id,
        )

    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        callback = emit
        await callback(  # type: ignore[operator]
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "done"})
        )
        await callback(  # type: ignore[operator]
            EngineEvent(event_type="status", payload={"status": "succeeded"})
        )


class NoAcceptanceRuntimeAdapter(FakeRuntimeAdapter):
    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        _ = context, emit


class FailingSteerRuntimeAdapter(FakeRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.accepted = asyncio.Event()
        self.release = asyncio.Event()

    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        await emit(  # type: ignore[operator]
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "ready"})
        )
        self.accepted.set()
        await self.release.wait()
        await emit(  # type: ignore[operator]
            EngineEvent(event_type="status", payload={"status": "succeeded"})
        )

    async def steer_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        text: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        _ = task_id, expected_turn_id, text, runtime_launch_key
        raise RuntimeError("simulated steer adapter failure")


class InterruptingRuntimeAdapter(FakeRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.accepted = asyncio.Event()
        self.interrupt_called = asyncio.Event()

    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        await emit(  # type: ignore[operator]
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "ready"})
        )
        self.accepted.set()
        await self.interrupt_called.wait()
        await emit(  # type: ignore[operator]
            EngineEvent(event_type="status", payload={"status": "interrupted"})
        )

    async def interrupt_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        _ = task_id, expected_turn_id, runtime_launch_key
        self.interrupt_called.set()
        return ControlReceipt(CapabilitySupport.NATIVE, True, {"rpc_ack": True})


class CountingInterruptRuntimeAdapter(FakeRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def interrupt_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        _ = task_id, expected_turn_id, runtime_launch_key
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ControlReceipt(CapabilitySupport.NATIVE, True, {"rpc_ack": True})


class BlockingInterruptRuntimeAdapter(FakeRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.accepted = asyncio.Event()
        self.interrupt_started = asyncio.Event()
        self.interrupt_release = asyncio.Event()
        self.runtime_release = asyncio.Event()

    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        await emit(  # type: ignore[operator]
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "ready"})
        )
        self.accepted.set()
        await self.runtime_release.wait()

    async def interrupt_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        _ = task_id, expected_turn_id, runtime_launch_key
        self.interrupt_started.set()
        await self.interrupt_release.wait()
        return ControlReceipt(CapabilitySupport.NATIVE, True, {"rpc_ack": True})


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    root = tmp_path / "ainrf-state"
    db_path = root / "runtime" / "agentic_researcher.sqlite3"
    db_path.parent.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                connection_fingerprint, created_at, updated_at
            ) VALUES ('environment-1', 'local', 'user-1', 'Local', '{}', 'fp', 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO workspaces (
                workspace_id, label, owner_user_id, environment_id, canonical_path,
                created_at, updated_at
            ) VALUES ('workspace-1', 'ws', 'user-1', 'environment-1', ?, 'now', 'now')""",
            (str(workspace),),
        )
        conn.execute(
            """INSERT INTO projects (
                project_id, owner_user_id, name, status, created_at, updated_at
            ) VALUES ('project-1', 'user-1', 'Project', 'active', 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-1', 'workspace-1', 'active', 1, 'user-1', 'now', 'now')"""
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, title, prompt, created_at, updated_at,
                owner_user_id
            ) VALUES (
                'task-1', 'project-1', 'workspace-1', 'environment-1', 'general',
                'codex-app-server', 'Conversation', 'hello', 'now', 'now', 'user-1'
            )
            """
        )
        conn.commit()
    auth = AuthService(state_root=root)
    auth.initialize()
    auth.grant_environment(
        env_id="environment-1",
        user_id="user-1",
        max_tasks=None,
        granted_by="admin",
        reason="conversation worker fixture",
    )
    application = ConversationApplicationService(root)
    application.initialize_task("task-1", _USER)
    application.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="create-1")
    return root


def test_worker_renders_the_persisted_submission_context_snapshot(state_root: Path) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO project_context_versions (
                   context_version_id, project_id, content, fingerprint, is_active,
                   created_by_user_id, created_at, fragment_manifest_json
               ) VALUES ('worker-context-version', 'project-1', 'Worker Context',
                         'worker-context-fingerprint', 0, 'user-1', 'now', '[]')"""
        )
        conn.execute(
            """INSERT INTO context_snapshots (
                   context_snapshot_id, context_version_id, fingerprint, content, created_at
               ) VALUES ('worker-context-snapshot', 'worker-context-version',
                         'worker-snapshot-fingerprint', 'Worker Context', 'now')"""
        )
        conn.execute(
            """UPDATE tasks
               SET project_context_version_id = 'worker-context-version',
                   project_context_snapshot_id = 'worker-context-snapshot'
               WHERE task_id = 'task-1'"""
        )
        conn.commit()

    application = ConversationApplicationService(state_root)
    admission = application.create_turn(
        "task-1", _USER, input={"text": "context turn"}, idempotency_key="context-turn"
    )
    with closing(connect(db_path)) as conn:
        initial = conn.execute(
            "SELECT submission_id FROM turn_submissions WHERE idempotency_key = 'create-1'"
        ).fetchone()
        assert initial is not None
        repository = SqliteConversationExecutionRepository(conn)
        assert (
            repository.transition_submission(
                submission_id=str(initial["submission_id"]),
                expected_status="queued",
                status="cancelled",
                finished_at="now",
                failure_code="superseded_by_context_test",
                updated_at="now",
            )
            == 1
        )
        persisted = conn.execute(
            "SELECT context_snapshot_ref FROM turn_submissions WHERE submission_id = ?",
            (str(admission["submission_id"]),),
        ).fetchone()
        assert persisted is not None
        assert persisted["context_snapshot_ref"] == "worker-context-snapshot"
        conn.commit()

    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None
    assert claim.submission_id == admission["submission_id"]
    context = dispatcher._execution_context(claim)
    assert context.rendered_prompt == "Worker Context\n\nUser Turn:\ncontext turn"


@pytest.mark.anyio
async def test_worker_does_not_start_adapter_for_environment_owner_without_grant(
    state_root: Path,
) -> None:
    AuthService(state_root=state_root).revoke_environment(
        "environment-1", "user-1", revoked_by="admin", reason="worker grant race"
    )
    starts = 0

    class TrackingAdapter(FakeRuntimeAdapter):
        async def start_turn(self, context: ExecutionContext, emit: object) -> None:
            nonlocal starts
            starts += 1
            await super().start_turn(context, emit)

    adapter = TrackingAdapter()
    dispatcher = ConversationDispatcher(state_root, adapter_factory=lambda _engine: adapter)
    assert await dispatcher.run_once() is True
    assert starts == 0

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        row = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = "
            "(SELECT submission_id FROM turn_submissions ORDER BY created_at LIMIT 1)"
        ).fetchone()
    assert row is not None
    assert tuple(row) == ("delivery_unknown", "worker_failed_before_acceptance")


@pytest.mark.anyio
async def test_worker_rechecks_environment_grant_after_context_before_adapter_start(
    state_root: Path,
) -> None:
    starts = 0

    class TrackingAdapter(FakeRuntimeAdapter):
        async def start_turn(self, context: ExecutionContext, emit: object) -> None:
            nonlocal starts
            starts += 1
            await super().start_turn(context, emit)

    def context_factory(claim: SubmissionClaim) -> ExecutionContext:
        AuthService(state_root=state_root).revoke_environment(
            "environment-1", "user-1", revoked_by="admin", reason="worker start race"
        )
        return ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        )

    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine: TrackingAdapter(),
        context_factory=context_factory,
    )
    assert await dispatcher.run_once() is True
    assert starts == 0


def test_worker_scopes_checkpoint_to_submission_runtime_identity(state_root: Path) -> None:
    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None

    context = dispatcher._execution_context(claim)

    assert context.runtime_launch_key == claim.submission_id
    assert context.runtime_execution_id is not None
    assert context.session_state_path == str(
        state_root / "session-states" / context.runtime_execution_id / "checkpoint.json"
    )
    checkpoint = SessionCheckpoint(
        task_id=claim.task_id,
        runtime_launch_key=claim.submission_id,
        runtime_execution_id=context.runtime_execution_id,
        session_id="session-for-submission",
    )
    assert context.session_state_path is not None
    checkpoint_path = Path(context.session_state_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(asdict(checkpoint)), encoding="utf-8")

    CodexAppServerEngine()._restore_checkpoint(
        context,
        CodexSession(task_id=claim.task_id),
    )


def test_delivery_unknown_without_runtime_rejects_launch_but_acceptance_recovers(
    state_root: Path,
) -> None:
    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None
    dispatcher._execution.begin_delivery(claim.submission_id)
    dispatcher._execution.mark_delivery_unknown(
        claim.submission_id,
        failure_code="acceptance_unknown",
        evidence={"source": "identity-recovery-test"},
    )

    with pytest.raises(ConversationContractError) as launch_rejected:
        dispatcher._execution_context(claim)
    assert launch_rejected.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION
    assert not (state_root / "session-states").exists()

    execution = dispatcher._execution.accept_and_open_execution(
        claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-delivery-unknown",
        native_turn_kind="turn",
        native_turn_ref="native-delivery-unknown",
        native_runtime_kind="process",
        native_runtime_ref="runtime-delivery-unknown",
        evidence={"source": "identity-recovery-test"},
    )
    replay = dispatcher._execution.accept_and_open_execution(
        claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-delivery-unknown",
        native_turn_kind="turn",
        native_turn_ref="native-delivery-unknown",
        native_runtime_kind="process",
        native_runtime_ref="runtime-delivery-unknown",
        evidence={"source": "identity-recovery-replay"},
    )

    assert replay == execution
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runtime_executions").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("submission_id", "wrong-submission"),
        ("task_id", "wrong-task"),
        ("reserved_turn_id", "wrong-turn"),
    ],
)
def test_worker_rejects_claim_identity_mismatch_before_context_path(
    state_root: Path,
    field: str,
    value: str,
) -> None:
    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None

    with pytest.raises(DomainConflictError, match="authoritative|claimed"):
        dispatcher._execution_context(replace(claim, **{field: value}))

    assert not (state_root / "session-states").exists()


def test_worker_rejects_unrelated_runtime_row_before_context_path(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None
    deterministic = dispatcher._execution.runtime_identity_for_launch_context(claim)
    unrelated = {
        "runtime_execution_id": deterministic.runtime_execution_id,
        "task_id": "unrelated-task",
        "turn_id": "unrelated-turn",
        "status": "running",
    }
    monkeypatch.setattr(
        SqliteConversationExecutionRepository,
        "runtime_execution_by_id",
        lambda _repository, _runtime_execution_id: unrelated,
    )

    with pytest.raises(DomainConflictError, match="does not belong"):
        dispatcher._execution_context(claim)

    assert not (state_root / "session-states").exists()


def test_worker_rejects_terminal_runtime_before_context_path(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = ConversationDispatcher(state_root)
    claim = dispatcher._execution.claim_next_submission()
    assert claim is not None
    terminal = {
        "runtime_execution_id": "terminal-execution",
        "task_id": claim.task_id,
        "turn_id": claim.reserved_turn_id,
        "status": "completed",
    }
    monkeypatch.setattr(
        SqliteConversationExecutionRepository,
        "runtime_executions_for_turn",
        lambda _repository, _turn_id: [terminal],
    )

    with pytest.raises(ConversationContractError) as rejected:
        dispatcher._execution_context(claim)

    assert rejected.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION
    assert not (state_root / "session-states").exists()


def test_runtime_checkpoint_identity_is_stable_for_submission_and_isolated_for_retry(
    state_root: Path,
) -> None:
    dispatcher = ConversationDispatcher(state_root)
    first_claim = dispatcher._execution.claim_next_submission()
    assert first_claim is not None
    first = dispatcher._execution.runtime_identity_for_launch_context(first_claim)
    repeated = dispatcher._execution.runtime_identity_for_launch_context(first_claim)

    assert repeated == first

    application = ConversationApplicationService(state_root)
    dispatcher._execution.begin_delivery(first_claim.submission_id)
    execution = dispatcher._execution.accept_and_open_execution(
        first_claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-first",
        native_turn_kind="turn",
        native_turn_ref="native-first",
        native_runtime_kind="process",
        native_runtime_ref="runtime-first",
        evidence={"source": "identity-test"},
    )
    restarted = ConversationDispatcher(state_root)
    assert restarted._execution.runtime_identity_for_launch_context(
        first_claim
    ).runtime_execution_id == (execution.runtime_execution_id)
    restarted_context = restarted._execution_context(first_claim)
    assert restarted_context.runtime_execution_id == execution.runtime_execution_id
    assert restarted_context.session_state_path == str(
        state_root / "session-states" / execution.runtime_execution_id / "checkpoint.json"
    )
    dispatcher._execution.finish_execution(
        execution,
        status=TurnStatus.COMPLETED,
        evidence={"source": "identity-test-finished"},
    )
    with pytest.raises(ConversationContractError) as terminal:
        dispatcher._execution.runtime_identity_for_launch_context(first_claim)
    assert terminal.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION
    retry = application.retry_turn(
        "task-1",
        first_claim.reserved_turn_id,
        _USER,
        input={"text": "retry"},
        idempotency_key="identity-retry",
    )
    second_claim = dispatcher._execution.claim_next_submission()
    assert second_claim is not None
    second = dispatcher._execution.runtime_identity_for_launch_context(second_claim)

    assert second.submission_id == retry["submission_id"]
    assert second.runtime_execution_id != first.runtime_execution_id


@pytest.mark.anyio
async def test_dispatcher_projects_engine_events_to_canonical_items(state_root: Path) -> None:
    adapter = FakeRuntimeAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    assert await dispatcher.run_once() is False

    task = ConversationApplicationService(state_root).read_task("task-1", _USER)
    turns = ConversationApplicationService(state_root).list_turns("task-1", _USER)
    items = ConversationApplicationService(state_root).list_items("task-1", _USER)
    assert task["runtime_status"] == "idle"
    assert turns[0]["status"] == "completed"
    assert [item["item_type"] for item in items] == ["user_message", "agent_message"]
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        binding = conn.execute(
            "SELECT binding_id, native_conversation_kind, native_conversation_ref, status "
            "FROM engine_conversation_bindings"
        ).fetchone()
        submission = conn.execute("SELECT submission_id FROM turn_submissions").fetchone()
        turn = conn.execute("SELECT binding_id FROM task_turns").fetchone()
        runtime = conn.execute("SELECT binding_id FROM runtime_executions").fetchone()
    assert binding is not None
    assert submission is not None
    assert tuple(binding[1:]) == (
        "thread",
        f"thread-{submission['submission_id']}",
        "active",
    )
    assert turn is not None and turn["binding_id"] == binding["binding_id"]
    assert runtime is not None and runtime["binding_id"] == binding["binding_id"]


@pytest.mark.anyio
async def test_dispatcher_buffers_events_until_complete_acceptance_identity(
    state_root: Path,
) -> None:
    class DelayedIdentityAdapter(FakeRuntimeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.identity_ready = False

        def native_acceptance_identity(
            self,
            *,
            runtime_launch_key: str,
            fallback_task_id: str,
            fallback_turn_id: str,
        ) -> NativeAcceptanceIdentity | None:
            if not self.identity_ready:
                return None
            return super().native_acceptance_identity(
                runtime_launch_key=runtime_launch_key,
                fallback_task_id=fallback_task_id,
                fallback_turn_id=fallback_turn_id,
            )

        async def start_turn(self, context: ExecutionContext, emit: object) -> None:
            await emit(  # type: ignore[operator]
                EngineEvent(event_type="system", payload={"subtype": "thread_started"})
            )
            self.identity_ready = True
            await emit(  # type: ignore[operator]
                EngineEvent(
                    event_type="message",
                    payload={"role": "assistant", "content": "ready"},
                )
            )
            await emit(  # type: ignore[operator]
                EngineEvent(event_type="status", payload={"status": "succeeded"})
            )

    adapter = DelayedIdentityAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    items = ConversationApplicationService(state_root).list_items("task-1", _USER)
    assert [item["item_type"] for item in items] == [
        "user_message",
        "system_notice",
        "agent_message",
    ]


@pytest.mark.anyio
async def test_worker_runtime_advertises_current_dispatch_and_overview_readiness(
    state_root: Path,
) -> None:
    artifact_sha = "a" * 64
    worker = ConversationWorkerRuntime(
        state_root,
        artifact_sha=artifact_sha,
        worker_id="domain-worker-test",
        adapter_factory=lambda _engine_type: FakeRuntimeAdapter(),
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )
    try:
        result = await worker.run_once()

        assert result.outcome == "completed"
        dispatcher = DomainMaintenanceService(state_root).participant_readiness("task-dispatcher")
        assert dispatcher["ready"] is True
        assert dispatcher["active_participant_ids"] == ["domain-worker-test"]
        overview = OverviewSnapshotService(
            state_root,
            artifact_sha=artifact_sha,
        ).planner_readiness()
        assert overview["job_store_ready"] is True
        assert overview["planner_ready"] is True
    finally:
        worker.stop()

    dispatcher = DomainMaintenanceService(state_root).participant_readiness("task-dispatcher")
    assert dispatcher["ready"] is False


@pytest.mark.anyio
async def test_worker_crash_before_delivery_reclaims_same_submission_without_extra_turn(
    state_root: Path,
) -> None:
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute("SELECT submission_id FROM turn_submissions").fetchone()
        conn.execute(
            """
            UPDATE turn_submissions
            SET status = 'claimed', claimed_at = '2000-01-01T00:00:00+00:00',
                updated_at = '2000-01-01T00:00:00+00:00'
            WHERE submission_id = ?
            """,
            (submission["submission_id"],),
        )
        conn.commit()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: FakeRuntimeAdapter(),
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    turns = ConversationApplicationService(state_root).list_turns("task-1", _USER)
    items = ConversationApplicationService(state_root).list_items("task-1", _USER)
    assert len(turns) == 1
    assert [item["item_type"] for item in items].count("user_message") == 1


@pytest.mark.anyio
async def test_unproven_delivery_becomes_unknown_without_materializing_or_replaying_turn(
    state_root: Path,
) -> None:
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: NoAcceptanceRuntimeAdapter(),
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    assert await dispatcher.run_once() is False
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute("SELECT status, failure_code FROM turn_submissions").fetchone()
        turn_count = conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0]
    assert submission["status"] == "delivery_unknown"
    assert submission["failure_code"] == "provider_acceptance_unproven"
    assert turn_count == 0


@pytest.mark.anyio
async def test_cancelled_claim_is_skipped_without_starting_adapter_or_runtime(
    state_root: Path,
) -> None:
    application = ConversationApplicationService(state_root)
    execution = ConversationExecutionService(state_root)
    claim = execution.claim_next_submission()
    assert claim is not None
    application.cancel_task("task-1", _USER, idempotency_key="cancel-claimed")
    started = False

    def adapter_factory(_: HarnessEngineType) -> ConversationRuntimeAdapter:
        nonlocal started
        started = True
        raise AssertionError("cancelled claim must not construct an adapter")

    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=adapter_factory,
        context_factory=lambda _: (_ for _ in ()).throw(
            AssertionError("cancelled claim must not construct execution context")
        ),
    )

    assert await dispatcher.run_once() is False
    assert started is False
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute("SELECT status FROM turn_submissions").fetchone()
        task_state = conn.execute("SELECT work_status FROM conversation_task_states").fetchone()
        turn_count = conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0]
        runtime_count = conn.execute("SELECT COUNT(*) FROM runtime_executions").fetchone()[0]
    assert submission is not None and submission["status"] == "cancelled"
    assert task_state is not None and task_state["work_status"] == TaskWorkStatus.CANCELLED
    assert turn_count == 0
    assert runtime_count == 0


async def _wait_for_control_status(
    state_root: Path, control_request_id: str, expected_status: str
) -> None:
    for _ in range(100):
        with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
            row = conn.execute(
                "SELECT status FROM turn_control_requests WHERE control_request_id = ?",
                (control_request_id,),
            ).fetchone()
        if row is not None and str(row["status"]) == expected_status:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"control {control_request_id} did not reach {expected_status}")


def _active_turn_id(state_root: Path) -> str:
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        row = conn.execute("SELECT turn_id FROM task_turns WHERE status = 'in_progress'").fetchone()
    assert row is not None
    return str(row["turn_id"])


def _open_execution(
    state_root: Path,
) -> tuple[ConversationExecutionService, SubmissionClaim, RuntimeExecutionClaim]:
    execution_service = ConversationExecutionService(state_root)
    claim = execution_service.claim_next_submission()
    assert claim is not None
    execution_service.begin_delivery(claim.submission_id)
    execution = execution_service.accept_and_open_execution(
        claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-1",
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        native_runtime_kind="process",
        native_runtime_ref="runtime-1",
        evidence={"source": "test"},
    )
    return execution_service, claim, execution


@pytest.mark.anyio
async def test_steer_adapter_failure_is_delivery_unknown_without_failing_turn(
    state_root: Path,
) -> None:
    adapter = FailingSteerRuntimeAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )
    run = asyncio.create_task(dispatcher.run_once())
    await adapter.accepted.wait()
    control = ConversationApplicationService(state_root).request_steer(
        "task-1",
        _active_turn_id(state_root),
        _USER,
        payload={"text": "focus"},
        idempotency_key="steer-failure",
    )
    await _wait_for_control_status(
        state_root,
        str(control["control_request_id"]),
        "delivery_unknown",
    )
    adapter.release.set()
    assert await run is True

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        control_row = conn.execute(
            "SELECT status, failure_code, evidence_json FROM turn_control_requests "
            "WHERE control_request_id = ?",
            (str(control["control_request_id"]),),
        ).fetchone()
        turn = conn.execute("SELECT status, failure_code FROM task_turns").fetchone()
    assert control_row is not None
    assert tuple(control_row[:2]) == ("delivery_unknown", "adapter_error")
    assert json.loads(str(control_row["evidence_json"]))["replay_forbidden"] is True
    assert turn is not None and tuple(turn) == ("completed", None)


@pytest.mark.anyio
async def test_accepted_interrupt_completes_with_interrupted_runtime(
    state_root: Path,
) -> None:
    adapter = InterruptingRuntimeAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )
    run = asyncio.create_task(dispatcher.run_once())
    await adapter.accepted.wait()
    control = ConversationApplicationService(state_root).request_interrupt(
        "task-1",
        _active_turn_id(state_root),
        _USER,
        idempotency_key="interrupt-completion",
    )
    await run

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        control_row = conn.execute(
            "SELECT status, accepted_at, completed_at FROM turn_control_requests "
            "WHERE control_request_id = ?",
            (str(control["control_request_id"]),),
        ).fetchone()
        turn = conn.execute("SELECT status FROM task_turns").fetchone()
        runtime = conn.execute("SELECT status FROM runtime_executions").fetchone()
    assert control_row is not None
    assert control_row["status"] == "completed"
    assert control_row["accepted_at"] is not None
    assert control_row["completed_at"] is not None
    assert turn is not None and turn["status"] == "interrupted"
    assert runtime is not None and runtime["status"] == "interrupted"


@pytest.mark.parametrize(
    ("terminal_status", "failure_code"),
    [
        (TurnStatus.COMPLETED, None),
        (TurnStatus.INTERRUPTED, None),
        (TurnStatus.FAILED, "engine_failed"),
    ],
)
@pytest.mark.anyio
async def test_terminal_runtime_reconciles_requested_and_delivering_controls(
    state_root: Path, terminal_status: TurnStatus, failure_code: str | None
) -> None:
    execution_service, _, execution = _open_execution(state_root)
    service = ConversationApplicationService(state_root)
    steer = service.request_steer(
        "task-1",
        execution.turn_id,
        _USER,
        payload={"text": "focus"},
        idempotency_key="terminal-steer",
    )
    interrupt = service.request_interrupt(
        "task-1",
        execution.turn_id,
        _USER,
        idempotency_key="terminal-interrupt",
    )
    execution_service.transition_control(
        str(steer["control_request_id"]),
        expected_status="requested",
        status="delivering",
        evidence={"source": "test"},
    )

    execution_service.finish_execution(
        execution,
        status=terminal_status,
        failure_code=failure_code,
        evidence={"source": "test_terminal"},
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        rows = conn.execute(
            "SELECT control_request_id, status, failure_code, completed_at "
            "FROM turn_control_requests ORDER BY control_request_id"
        ).fetchall()
        turn = conn.execute("SELECT status FROM task_turns").fetchone()
        runtime = conn.execute("SELECT status FROM runtime_executions").fetchone()
    controls = {str(row["control_request_id"]): row for row in rows}
    assert controls[str(steer["control_request_id"])]["status"] == "delivery_unknown"
    assert (
        controls[str(steer["control_request_id"])]["failure_code"]
        == "control_delivery_unknown_runtime_terminal"
    )
    assert controls[str(interrupt["control_request_id"])]["status"] == "rejected"
    assert (
        controls[str(interrupt["control_request_id"])]["failure_code"]
        == "runtime_terminal_before_control_delivery"
    )
    assert all(row["completed_at"] is not None for row in rows)
    assert turn is not None and turn["status"] == terminal_status
    assert runtime is not None and runtime["status"] == terminal_status


@pytest.mark.anyio
async def test_stale_control_delivery_recovers_without_replay(state_root: Path) -> None:
    execution_service, _, execution = _open_execution(state_root)
    service = ConversationApplicationService(state_root)
    steer = service.request_steer(
        "task-1",
        execution.turn_id,
        _USER,
        payload={"text": "focus"},
        idempotency_key="stale-steer",
    )
    execution_service.transition_control(
        str(steer["control_request_id"]),
        expected_status="requested",
        status="delivering",
        evidence={"source": "test"},
    )
    interrupt = service.request_interrupt(
        "task-1",
        execution.turn_id,
        _USER,
        idempotency_key="stale-interrupt",
    )
    assert execution_service.claim_interrupt(
        str(interrupt["control_request_id"]), claim_id="stale-claim"
    )
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE turn_control_requests SET updated_at = '2000-01-01T00:00:00+00:00' "
            "WHERE control_request_id IN (?, ?)",
            (str(steer["control_request_id"]), str(interrupt["control_request_id"])),
        )
        conn.commit()

    dispatcher = ConversationDispatcher(state_root, adapter_factory=lambda _: FakeRuntimeAdapter())
    assert await dispatcher.run_once() is False

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        row = conn.execute(
            "SELECT status, failure_code, completed_at FROM turn_control_requests "
            "WHERE control_request_id IN (?, ?) ORDER BY control_request_id",
            (str(steer["control_request_id"]), str(interrupt["control_request_id"])),
        ).fetchall()
    assert len(row) == 2
    assert all(
        tuple(item[:2]) == ("delivery_unknown", "worker_lost_during_control_delivery")
        for item in row
    )
    assert all(item["completed_at"] is not None for item in row)


@pytest.mark.anyio
async def test_interrupt_adapter_is_called_once_across_worker_control_consumers(
    state_root: Path,
) -> None:
    execution_service, claim, execution = _open_execution(state_root)
    control = ConversationApplicationService(state_root).request_interrupt(
        "task-1",
        execution.turn_id,
        _USER,
        idempotency_key="concurrent-interrupt",
    )
    adapter = CountingInterruptRuntimeAdapter()
    dispatcher_a = ConversationDispatcher(state_root)
    dispatcher_b = ConversationDispatcher(state_root)
    consumers = asyncio.gather(
        dispatcher_a._consume_controls(adapter, claim, execution),
        dispatcher_b._consume_controls(adapter, claim, execution),
    )
    await adapter.started.wait()
    adapter.release.set()
    await consumers

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        row = conn.execute(
            "SELECT status, accepted_at, completed_at FROM turn_control_requests "
            "WHERE control_request_id = ?",
            (str(control["control_request_id"]),),
        ).fetchone()
    assert adapter.calls == 1
    assert row is not None
    assert row["status"] == "accepted"
    assert row["accepted_at"] is not None
    assert row["completed_at"] is None


@pytest.mark.anyio
async def test_worker_cancellation_reconciles_claimed_interrupt_before_propagating(
    state_root: Path,
) -> None:
    adapter = BlockingInterruptRuntimeAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )
    run = asyncio.create_task(dispatcher.run_once())
    await adapter.accepted.wait()
    control = ConversationApplicationService(state_root).request_interrupt(
        "task-1",
        _active_turn_id(state_root),
        _USER,
        idempotency_key="cancelled-interrupt",
    )
    await adapter.interrupt_started.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        control_row = conn.execute(
            "SELECT status, failure_code, completed_at FROM turn_control_requests "
            "WHERE control_request_id = ?",
            (str(control["control_request_id"]),),
        ).fetchone()
        turn = conn.execute("SELECT status, failure_code FROM task_turns").fetchone()
    assert control_row is not None
    assert tuple(control_row[:2]) == ("delivery_unknown", "adapter_cancelled")
    assert control_row["completed_at"] is not None
    assert turn is not None and tuple(turn) == ("interrupted", None)

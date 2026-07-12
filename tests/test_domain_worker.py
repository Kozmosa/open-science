"""Durable domain-worker dispatch and recovery tests."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import (
    AttemptService,
    DomainService,
    ProjectContextService,
    TaskApplicationService,
)
from ainrf.domain.attempts import DispatchClaim, DispatchClaimError
from ainrf.domain.worker import DispatchRunResult, TaskDispatcher
from ainrf.domain_control import DomainCutoverError, DomainMaintenanceService
from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    RuntimeProbeResult,
    RuntimeProbeStatus,
)
from ainrf.harness_engine.base import EngineEmit
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import FakeEngine, HangingEngine, TokenEngine, seed_user

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _queued_task(
    state_root: Path,
    tmp_path: Path,
    *,
    harness_engine: str = "claude-code",
) -> tuple[dict[str, str], AuthService, str]:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = DomainService(state_root)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="domain worker test",
    )
    project = domain.create_project(owner, name="Project")
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Workspace",
    )
    project_id = str(project["project_id"])
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, owner, idempotency_key="link")
    context = ProjectContextService(state_root)
    context.save_draft(project_id, "Project context", owner)
    context.publish(project_id, owner)
    task = TaskApplicationService(state_root).create_task(
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        title="Research",
        prompt="Investigate this",
        researcher_type="vanilla",
        harness_engine=harness_engine,
        idempotency_key="create",
    )
    return task, auth, environment_id


@pytest.mark.anyio
async def test_domain_worker_runs_durable_attempt_and_projects_event_data(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "completed"
    assert result.attempt_id == task["attempt_id"]
    assert engine.started_count == 1
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status, output_start_seq, output_end_seq FROM agent_task_attempts WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        runtime = conn.execute(
            "SELECT status, launch_key FROM agent_runtime_sessions WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status, launch_state FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (task["dispatch_id"],),
        ).fetchone()
        outputs = conn.execute(
            "SELECT kind, content FROM task_outputs WHERE task_id = ? ORDER BY seq",
            (task["task_id"],),
        ).fetchall()
    assert attempt is not None
    assert attempt["status"] == "succeeded"
    assert (attempt["output_start_seq"], attempt["output_end_seq"]) == (1, 2)
    assert runtime is not None
    assert runtime["status"] == "completed"
    assert str(runtime["launch_key"]).startswith("launch-attempt-")
    assert dispatch is not None
    assert (dispatch["status"], dispatch["launch_state"]) == ("completed", "launched")
    assert [output["kind"] for output in outputs] == ["message", "lifecycle"]
    assert "## Task Request\nInvestigate this" in str(outputs[0]["content"])


@pytest.mark.anyio
async def test_domain_worker_requires_the_committed_v2_artifact(
    state_root: Path, tmp_path: Path
) -> None:
    prepare_committed_v2_cutover(state_root, tmp_path)

    missing = TaskDispatcher(state_root, dispatcher_id="missing-artifact", lease_seconds=3)
    with pytest.raises(DomainCutoverError, match="requires the committed v2 artifact SHA"):
        await missing.run_once()
    missing.stop()

    mismatched = TaskDispatcher(
        state_root,
        dispatcher_id="wrong-artifact",
        lease_seconds=3,
        artifact_sha="c" * 64,
    )
    with pytest.raises(DomainCutoverError, match="does not match"):
        await mismatched.run_once()
    mismatched.stop()

    matching = TaskDispatcher(
        state_root,
        dispatcher_id="matching-artifact",
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )
    result = await matching.run_once()
    matching.stop()
    assert result.outcome == "idle"


@pytest.mark.anyio
async def test_dispatcher_consumes_live_cancel_control_and_waits_for_runtime_exit(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = HangingEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-live-control",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    cancellation = TaskApplicationService(state_root).cancel_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        reason="cancel a live runtime",
        idempotency_key="cancel-live-runtime",
    )
    result = await asyncio.wait_for(run, timeout=3)
    dispatcher.stop()

    assert result.outcome == "cancelled"
    assert task["task_id"] in engine.cancelled_task_ids
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        control = conn.execute(
            """SELECT status FROM task_attempt_control_requests
               WHERE control_request_id = ?""",
            (cancellation["control_request_id"],),
        ).fetchone()
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (task["attempt_id"],)
        ).fetchone()
        runtime = conn.execute(
            "SELECT status FROM agent_runtime_sessions WHERE attempt_id = ?", (task["attempt_id"],)
        ).fetchone()

    assert control is not None
    assert control["status"] == "completed"
    assert attempt is not None
    assert attempt["status"] == "cancelled"
    assert runtime is not None
    assert runtime["status"] == "cancelled"


@pytest.mark.anyio
async def test_dispatcher_delivers_live_continuation_once_with_attempt_runtime_identity(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = HangingEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-live-input",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )
    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    tasks = TaskApplicationService(state_root)
    continued = tasks.continue_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        prompt="Please include the uncertainty bounds.",
        idempotency_key="continue-live-runtime",
    )
    assert (
        tasks.continue_task(
            task["task_id"],
            {"id": "owner", "role": "member"},
            prompt="Please include the uncertainty bounds.",
            idempotency_key="continue-live-runtime",
        )
        == continued
    )
    for _ in range(100):
        if engine.pending_prompts == ["Please include the uncertainty bounds."]:
            break
        await asyncio.sleep(0.01)
    assert engine.pending_prompts == ["Please include the uncertainty bounds."]

    TaskApplicationService(state_root).cancel_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        reason="complete live input test",
        idempotency_key="cancel-live-input",
    )
    await asyncio.wait_for(run, timeout=3)
    dispatcher.stop()
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        control = conn.execute(
            """SELECT status FROM task_attempt_control_requests
               WHERE control_request_id = ?""",
            (continued["control_request_id"],),
        ).fetchone()

    assert control is not None
    assert control["status"] == "completed"


class _PausableEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.pause_requested = asyncio.Event()
        self.resume_count = 0

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.started_count += 1
        self._alive.add(context.task_id)
        self._remember_runtime_launch(context)
        await self.pause_requested.wait()
        await emit(EngineEvent(event_type="system", payload={"subtype": "task_paused"}))

    async def pause(self, task_id: str, *, runtime_launch_key: str | None = None) -> None:
        _ = task_id, runtime_launch_key
        self.pause_requested.set()

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.resume_count += 1
        await emit(
            EngineEvent(
                event_type="message",
                payload={"role": "assistant", "content": "resumed the same runtime"},
            )
        )
        await emit(EngineEvent(event_type="status", payload={"status": "succeeded"}))
        self._alive.discard(context.task_id)


@pytest.mark.anyio
async def test_dispatcher_pauses_and_resumes_the_same_attempt_and_runtime(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = _PausableEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-pause-resume",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )
    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    tasks = TaskApplicationService(state_root)
    paused = tasks.pause_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        idempotency_key="pause-live-runtime",
    )
    for _ in range(100):
        with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
            attempt = conn.execute(
                "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (task["attempt_id"],)
            ).fetchone()
        if attempt is not None and attempt["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    assert attempt is not None
    assert attempt["status"] == "paused"

    resumed = tasks.resume_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        idempotency_key="resume-live-runtime",
    )
    result = await asyncio.wait_for(run, timeout=3)
    dispatcher.stop()

    assert result.outcome == "completed"
    assert engine.resume_count == 1
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM agent_task_attempts WHERE task_id = ?", (task["task_id"],)
        ).fetchone()
        runtime_count = conn.execute(
            "SELECT COUNT(*) FROM agent_runtime_sessions WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        pause_control = conn.execute(
            "SELECT status FROM task_attempt_control_requests WHERE control_request_id = ?",
            (paused["control_request_id"],),
        ).fetchone()
        resume_control = conn.execute(
            "SELECT status FROM task_attempt_control_requests WHERE control_request_id = ?",
            (resumed["control_request_id"],),
        ).fetchone()

    assert attempt_count is not None
    assert attempt_count[0] == 1
    assert runtime_count is not None
    assert runtime_count[0] == 1
    assert pause_control is not None
    assert pause_control["status"] == "completed"
    assert resume_control is not None
    assert resume_control["status"] == "completed"


def test_expired_claim_is_recovered_by_one_new_dispatcher_and_old_token_loses_access(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root)
    original = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert original is not None
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        conn.commit()

    recovered = attempts.claim_next("dispatcher-b", lease_seconds=30)

    assert recovered is not None
    assert recovered.dispatch_id == original.dispatch_id
    assert recovered.claim_token != original.claim_token
    with pytest.raises(DispatchClaimError, match="claim"):
        attempts.prepare_runtime_launch(original)


def test_expired_claim_token_cannot_renew_or_write_after_another_dispatcher_recovers(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root)
    original = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert original is not None
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        conn.commit()
    recovered = attempts.claim_next("dispatcher-b", lease_seconds=30)
    assert recovered is not None

    with pytest.raises(DispatchClaimError):
        attempts.heartbeat_claim(original)
    with pytest.raises(DispatchClaimError):
        attempts.record_event(
            original,
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "stale"}),
        )


def test_stop_request_wins_before_the_runtime_launch_fence(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root)
    claim = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert claim is not None
    preparation = attempts.prepare_runtime_launch(claim)

    cancellation = TaskApplicationService(state_root).cancel_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        reason="cancel before engine boundary",
        idempotency_key="cancel-before-engine-boundary",
    )
    assert cancellation["status"] == "requested"
    assert attempts.commit_runtime_launch(claim, preparation.runtime_session_id) is False

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (task["attempt_id"],)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status, launch_state FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (task["dispatch_id"],),
        ).fetchone()
        runtime = conn.execute(
            "SELECT 1 FROM agent_runtime_sessions WHERE attempt_id = ?", (task["attempt_id"],)
        ).fetchone()
        control = conn.execute(
            """SELECT status FROM task_attempt_control_requests
               WHERE control_request_id = ?""",
            (cancellation["control_request_id"],),
        ).fetchone()

    assert attempt is not None
    assert attempt["status"] == "cancelled"
    assert dispatch is not None
    assert (dispatch["status"], dispatch["launch_state"]) == ("cancelled", "none")
    assert runtime is None
    assert control is not None
    assert control["status"] == "completed"


class _AbsentRecoveryEngine(FakeEngine):
    async def probe_runtime(self, *, task_id: str, launch_key: str) -> RuntimeProbeResult:
        _ = task_id, launch_key
        return RuntimeProbeResult(status=RuntimeProbeStatus.ABSENT)


class _UnknownRecoveryEngine(FakeEngine):
    async def probe_runtime(self, *, task_id: str, launch_key: str) -> RuntimeProbeResult:
        _ = task_id, launch_key
        return RuntimeProbeResult(status=RuntimeProbeStatus.UNKNOWN)


class _AdoptableRecoveryEngine(FakeEngine):
    async def probe_runtime(self, *, task_id: str, launch_key: str) -> RuntimeProbeResult:
        _ = task_id, launch_key
        return RuntimeProbeResult(
            status=RuntimeProbeStatus.RUNNING,
            engine_session_key="external-session",
        )

    async def adopt_runtime(self, *, task_id: str, launch_key: str) -> RuntimeProbeResult:
        _ = task_id, launch_key
        return RuntimeProbeResult(
            status=RuntimeProbeStatus.RUNNING,
            engine_session_key="external-session",
            metadata={"adopted": True},
        )


async def _recover_expired_start(
    state_root: Path,
    task: dict[str, str],
    engine: FakeEngine,
) -> tuple[DispatchRunResult, FakeEngine]:
    attempts = AttemptService(state_root)
    original = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert original is not None
    attempts.prepare_runtime_launch(original)
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        conn.commit()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-b",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )
    result = await dispatcher.run_once()
    dispatcher.stop()
    return result, engine


@pytest.mark.anyio
async def test_domain_worker_never_blindly_restarts_an_unknown_prior_launch(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)

    result, engine = await _recover_expired_start(state_root, task, _UnknownRecoveryEngine())

    assert result.outcome == "launch_unknown"
    assert engine.started_count == 0
    state = AttemptService(state_root).dispatch_state(task["dispatch_id"])
    assert state["status"] == "launch_unknown"
    assert state["launch_state"] == "unknown"
    assert AttemptService(state_root).claim_next("dispatcher-c") is None


@pytest.mark.anyio
async def test_domain_worker_adopts_a_proven_runtime_after_dispatcher_crash(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)

    result, engine = await _recover_expired_start(state_root, task, _AdoptableRecoveryEngine())

    assert result.outcome == "adopted"
    assert engine.started_count == 0
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        runtime = conn.execute(
            "SELECT status, engine_session_key, adopted_at FROM agent_runtime_sessions WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
    assert runtime is not None
    assert runtime["status"] == "running"
    assert runtime["engine_session_key"] == "external-session"
    assert runtime["adopted_at"] is not None


@pytest.mark.anyio
async def test_expired_dispatched_runtime_is_reconciled_without_a_blind_restart(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root)
    original = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert original is not None
    prepared = attempts.prepare_runtime_launch(original)
    attempts.mark_runtime_running(original, prepared.runtime_session_id)
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        conn.commit()
    engine = _AbsentRecoveryEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-b",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "launch_unknown"
    assert engine.started_count == 0
    state = attempts.dispatch_state(task["dispatch_id"])
    assert state["status"] == "launch_unknown"


class _FailedThenRaisesEngine(FakeEngine):
    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.started_count += 1
        self._remember_runtime_launch(context)
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "failed", "message": "runtime failure"},
            )
        )
        raise RuntimeError("engine raised after terminal status")


@pytest.mark.anyio
async def test_terminal_engine_event_wins_when_engine_then_raises(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = _FailedThenRaisesEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "failed"
    state = AttemptService(state_root).dispatch_state(task["dispatch_id"])
    assert state["status"] == "failed"


@pytest.mark.anyio
async def test_maintenance_epoch_after_claim_releases_prepared_work_without_starting_engine(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )
    original_context = dispatcher._execution_context_for
    entered = False

    def enter_maintenance_after_context(
        claim: DispatchClaim,
    ) -> tuple[ExecutionContext, str, int]:
        nonlocal entered
        result = original_context(claim)
        if not entered:
            DomainMaintenanceService(state_root).enter(actor_id="operator", reason="test")
            entered = True
        return result

    monkeypatch.setattr(dispatcher, "_execution_context_for", enter_maintenance_after_context)

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "maintenance_drained"
    assert engine.started_count == 0
    state = AttemptService(state_root).dispatch_state(task["dispatch_id"])
    assert (state["status"], state["launch_state"]) == ("pending", "none")


@pytest.mark.anyio
async def test_tenant_agent_sdk_is_rejected_before_any_backend_user_launch(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, auth, _ = _queued_task(state_root, tmp_path, harness_engine="agent-sdk")
    seed_user(auth, username="owner-user", password="test-pass", role="member", user_id="owner")
    monkeypatch.setattr("ainrf.domain.worker._is_container_environment", lambda: True)
    monkeypatch.setattr("ainrf.domain.worker._linux_user_exists", lambda _user: True)
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "stopped_permission_revoked"
    assert "Agent SDK" in str(result.detail)
    assert engine.started_count == 0


@pytest.mark.anyio
async def test_domain_worker_projects_attempt_token_usage_and_cost(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = TokenEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "completed"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT token_usage_json, cost_usd FROM agent_task_attempts WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
    assert attempt is not None
    assert '"input_tokens": 20' in str(attempt["token_usage_json"])
    assert attempt["cost_usd"] == pytest.approx(0.02)


class _ReferenceEngine(FakeEngine):
    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.started_count += 1
        self._remember_runtime_launch(context)
        await emit(
            EngineEvent(
                event_type="message",
                payload={
                    "role": "assistant",
                    "content": "produced durable references",
                    "artifact_refs": ["artifact-1", "artifact-1"],
                    "code_refs": ["commit-abc"],
                    "data_refs": ["dataset-1"],
                },
            )
        )
        await emit(EngineEvent(event_type="status", payload={"status": "succeeded"}))


@pytest.mark.anyio
async def test_domain_worker_persists_attempt_output_scope_and_references(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: _ReferenceEngine(),
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "completed"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            """SELECT message_start_seq, message_end_seq, output_start_seq, output_end_seq,
                      artifact_refs_json, code_refs_json, data_refs_json
               FROM agent_task_attempts WHERE attempt_id = ?""",
            (task["attempt_id"],),
        ).fetchone()
    assert attempt is not None
    assert (attempt["message_start_seq"], attempt["message_end_seq"]) == (1, 1)
    assert (attempt["output_start_seq"], attempt["output_end_seq"]) == (1, 2)
    assert attempt["artifact_refs_json"] == '["artifact-1"]'
    assert attempt["code_refs_json"] == '["commit-abc"]'
    assert attempt["data_refs_json"] == '["dataset-1"]'


@pytest.mark.anyio
async def test_domain_worker_rechecks_environment_grant_before_any_runtime_start(
    state_root: Path, tmp_path: Path
) -> None:
    task, auth, environment_id = _queued_task(state_root, tmp_path)
    auth.revoke_environment(environment_id, "owner", reason="revoked before dispatch")
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "stopped_permission_revoked"
    assert engine.started_count == 0
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status, stop_reason FROM agent_task_attempts WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (task["dispatch_id"],),
        ).fetchone()
    assert attempt is not None
    assert attempt["status"] == "stopped_permission_revoked"
    assert "revoked" in str(attempt["stop_reason"])
    assert dispatch is not None
    assert dispatch["status"] == "cancelled"

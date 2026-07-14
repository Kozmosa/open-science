"""Durable domain-worker dispatch and recovery tests."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.api.routes.metrics import get_metrics_text, reset_metrics
from ainrf.db import connect
from ainrf.domain import (
    AttemptService,
    DomainService,
    OverviewSnapshotService,
    ProjectContextService,
    TaskApplicationService,
)
from ainrf.domain.attempts import DispatchClaim, DispatchClaimError
from ainrf.domain.worker import (
    DispatchRunResult,
    TaskDispatcher,
    _maintenance_is_active_read_only,
)
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
    # Every B5 test exercises the authoritative worker, never a pre-cutover
    # shadow writer.  The fixture follows the real finalize/prepare/commit
    # path and binds all application repositories to its immutable artifact.
    prepare_committed_v2_cutover(state_root, tmp_path)
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    auth = AuthService(state_root=state_root)
    auth.initialize()
    seed_user(auth, username="worker-owner", role="member", user_id="owner")
    seed_user(auth, username="worker-admin", role="admin", user_id="admin")
    domain = DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    environment_id = str(environment["environment_id"])
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
    context = ProjectContextService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    context.save_draft(project_id, "Project context", owner)
    context.publish(project_id, owner)
    task = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).create_task(
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


def _state_tree_digest(state_root: Path, *, exclude_control_database: bool) -> str:
    """Fingerprint state contents without changing its SQLite journal state."""

    digest = hashlib.sha256()
    if not state_root.exists():
        return digest.hexdigest()
    for path in sorted(state_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(state_root).as_posix()
        if exclude_control_database and relative.startswith("runtime/agentic_researcher.sqlite3"):
            continue
        if path.is_dir():
            digest.update(f"dir:{relative}\n".encode("utf-8"))
            continue
        if not path.is_file():
            digest.update(f"other:{relative}\n".encode("utf-8"))
            continue
        digest.update(f"file:{relative}\n".encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _non_control_state_digest(state_root: Path) -> str:
    """Fingerprint state while allowing the explicit maintenance registry write."""

    return _state_tree_digest(state_root, exclude_control_database=True)


def _checkpoint_control_database_for_immutable_probe(state_root: Path) -> None:
    """Create a clean main-db-only fixture for the startup probe regression."""

    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for suffix in ("-wal", "-shm"):
        database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)


def test_worker_maintenance_probe_fails_closed_for_uncheckpointed_wal(state_root: Path) -> None:
    maintenance = DomainMaintenanceService(state_root)
    maintenance.initialize()
    _checkpoint_control_database_for_immutable_probe(state_root)
    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    wal_path = database_path.with_name(f"{database_path.name}-wal")
    wal_path.touch()
    before = _state_tree_digest(state_root, exclude_control_database=False)

    try:
        assert _maintenance_is_active_read_only(state_root) is True
        assert _state_tree_digest(state_root, exclude_control_database=False) == before
    finally:
        wal_path.unlink(missing_ok=True)


def test_worker_maintenance_probe_uses_immutable_read_for_lone_shm(state_root: Path) -> None:
    maintenance = DomainMaintenanceService(state_root)
    maintenance.initialize()
    _checkpoint_control_database_for_immutable_probe(state_root)
    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    shm_path = database_path.with_name(f"{database_path.name}-shm")
    shm_path.touch()
    before = _state_tree_digest(state_root, exclude_control_database=False)

    try:
        assert _maintenance_is_active_read_only(state_root) is False
        assert _state_tree_digest(state_root, exclude_control_database=False) == before
    finally:
        shm_path.unlink(missing_ok=True)


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
        artifact_sha=V2_ARTIFACT_SHA,
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


class _LaunchEvidenceEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.bound_launch_keys: list[str] = []
        self.armed_launch_keys: list[str] = []

    def bind_runtime_context(self, context: ExecutionContext) -> None:
        if context.runtime_launch_key is not None:
            self.bound_launch_keys.append(context.runtime_launch_key)

    def arm_runtime_launch(self, context: ExecutionContext) -> None:
        if context.runtime_launch_key is not None:
            self.armed_launch_keys.append(context.runtime_launch_key)


@pytest.mark.anyio
async def test_domain_worker_arms_adapter_evidence_before_first_runtime_start(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    engine = _LaunchEvidenceEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-evidence",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    expected_launch_key = f"launch-{task['attempt_id']}"
    assert result.outcome == "completed"
    assert engine.bound_launch_keys == [expected_launch_key]
    assert engine.armed_launch_keys == [expected_launch_key]


@pytest.mark.anyio
async def test_domain_worker_refuses_legacy_state_before_registering_a_participant(
    state_root: Path,
) -> None:
    dispatcher = TaskDispatcher(
        state_root, dispatcher_id="legacy-direct-dispatcher", lease_seconds=3
    )

    with pytest.raises(DomainCutoverError, match="committed v2 cutover"):
        await dispatcher.run_once()
    with pytest.raises(DomainCutoverError, match="committed v2 cutover"):
        dispatcher.start()
    dispatcher.stop()

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        participant = conn.execute(
            "SELECT 1 FROM domain_write_participants WHERE participant_id = ?",
            ("legacy-direct-dispatcher",),
        ).fetchone()
    assert participant is None


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
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        cutover = conn.execute(
            "SELECT first_v2_write_at, first_v2_write_actor_id "
            "FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
    assert cutover is not None
    assert cutover["first_v2_write_at"] is not None
    assert cutover["first_v2_write_actor_id"] == "domain-worker:matching-artifact"


@pytest.mark.anyio
async def test_maintenance_blocks_worker_first_v2_write_before_the_fuse_changes(
    state_root: Path, tmp_path: Path
) -> None:
    prepare_committed_v2_cutover(state_root, tmp_path)
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="maintenance-first-write",
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )
    DomainMaintenanceService(state_root).enter(actor_id="operator", reason="cutover")

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "maintenance_drained"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        cutover = conn.execute(
            "SELECT first_v2_write_at, first_v2_write_actor_id "
            "FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
    assert cutover is not None
    assert cutover["first_v2_write_at"] is None
    assert cutover["first_v2_write_actor_id"] is None


@pytest.mark.anyio
async def test_active_maintenance_worker_never_constructs_writable_services(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restarted worker may add a drained registry row but nothing else."""

    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="staged restore")
    _checkpoint_control_database_for_immutable_probe(state_root)
    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    assert not database_path.with_name(f"{database_path.name}-wal").exists()
    assert not database_path.with_name(f"{database_path.name}-shm").exists()
    wakeup_path = state_root / "runtime" / "domain-worker.wakeup"
    assert not wakeup_path.exists()
    before = _state_tree_digest(state_root, exclude_control_database=False)
    before_non_control = _non_control_state_digest(state_root)
    assert _maintenance_is_active_read_only(state_root) is True
    assert _state_tree_digest(state_root, exclude_control_database=False) == before

    def unexpected_constructor(*_args: object, **_kwargs: object) -> object:
        pytest.fail("active-maintenance worker must not construct a writable service")

    monkeypatch.setattr("ainrf.domain.worker.DomainCutoverController", unexpected_constructor)
    monkeypatch.setattr("ainrf.domain.worker.AttemptService", unexpected_constructor)
    monkeypatch.setattr("ainrf.domain.worker.OverviewSnapshotPlanner", unexpected_constructor)

    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="maintenance-read-only-dispatcher",
        lease_seconds=3,
    )
    assert _state_tree_digest(state_root, exclude_control_database=False) == before
    assert not wakeup_path.exists()

    try:
        result = await dispatcher.run_once()
        assert result.outcome == "maintenance_drained"
        assert _non_control_state_digest(state_root) == before_non_control
        participant = next(
            item
            for item in maintenance.participants()
            if item.participant_id == "maintenance-read-only-dispatcher"
        )
        assert participant.status == "drained"
        assert participant.in_flight_mutations == 0
    finally:
        dispatcher.stop()
        maintenance.exit(actor_id="operator")


@pytest.mark.anyio
async def test_v2_domain_worker_runs_the_durable_overview_planner(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_committed_v2_cutover(state_root, tmp_path)
    auth = AuthService(state_root=state_root)
    overview_owner = seed_user(
        auth,
        username="overview-owner",
        role="member",
        user_id="overview-owner",
    )
    snapshots = OverviewSnapshotService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    queued = snapshots.request_refresh(overview_owner)

    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="overview-domain-worker",
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )
    monkeypatch.setattr(dispatcher._attempts, "claim_next", lambda *_args, **_kwargs: None)
    try:
        result = await dispatcher.run_once()
    finally:
        dispatcher.stop()

    assert result.outcome == "idle"
    completed = snapshots.get_job(overview_owner, str(queued["job_id"]))
    assert completed is not None
    assert completed["status"] in {"succeeded", "partial"}
    assert snapshots.latest(overview_owner) is not None
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        planner = conn.execute(
            "SELECT planner_id, status FROM overview_planner_state WHERE singleton = 1"
        ).fetchone()
    assert planner is not None
    assert planner["planner_id"] == "overview-domain-worker:overview"
    assert planner["status"] == "stopped"


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
        artifact_sha=V2_ARTIFACT_SHA,
    )

    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    cancellation = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).cancel_task(
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
        artifact_sha=V2_ARTIFACT_SHA,
    )
    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    tasks = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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

    TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).cancel_task(
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
        artifact_sha=V2_ARTIFACT_SHA,
    )
    run = asyncio.create_task(dispatcher.run_once())
    for _ in range(100):
        if engine.started_count == 1:
            break
        await asyncio.sleep(0.01)
    assert engine.started_count == 1

    tasks = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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


def test_dispatched_runtime_heartbeat_renews_the_live_dispatch_lease(
    state_root: Path, tmp_path: Path
) -> None:
    """Long-running runtimes keep their recoverable dispatch lease alive."""

    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    claim = attempts.claim_next("dispatcher-a", lease_seconds=1)
    assert claim is not None
    preparation = attempts.prepare_runtime_launch(claim)
    attempts.mark_runtime_running(claim, preparation.runtime_session_id)

    renewed = attempts.heartbeat_claim(claim, lease_seconds=60)
    state = attempts.dispatch_state(task["dispatch_id"])

    assert state["status"] == "dispatched"
    assert state["claim_token"] == claim.claim_token
    assert state["claim_expires_at"] == renewed.claim_expires_at
    assert state["claim_heartbeat_at"] is not None


def test_stop_request_wins_before_the_runtime_launch_fence(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    claim = attempts.claim_next("dispatcher-a", lease_seconds=30)
    assert claim is not None
    preparation = attempts.prepare_runtime_launch(claim)

    cancellation = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).cancel_task(
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
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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
        artifact_sha=V2_ARTIFACT_SHA,
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
    state = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA).dispatch_state(
        task["dispatch_id"]
    )
    assert state["status"] == "launch_unknown"
    assert state["launch_state"] == "unknown"
    assert (
        AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA).claim_next("dispatcher-c") is None
    )


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
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
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
        artifact_sha=V2_ARTIFACT_SHA,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "launch_unknown"
    assert engine.started_count == 0
    state = attempts.dispatch_state(task["dispatch_id"])
    assert state["status"] == "launch_unknown"


@pytest.mark.anyio
async def test_paused_runtime_absence_creates_one_resume_attempt_only_after_a_probe(
    state_root: Path, tmp_path: Path
) -> None:
    """A paused runtime loss never restarts blindly, but a resume intent recovers it."""

    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    original = attempts.claim_next("paused-dispatcher-a", lease_seconds=30)
    assert original is not None
    prepared = attempts.prepare_runtime_launch(original)
    assert attempts.commit_runtime_launch(original, prepared.runtime_session_id)
    attempts.mark_runtime_running(original, prepared.runtime_session_id)
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'paused' WHERE attempt_id = ?",
            (task["attempt_id"],),
        )
        conn.execute("UPDATE tasks SET status = 'paused' WHERE task_id = ?", (task["task_id"],))
        conn.execute(
            "UPDATE agent_runtime_sessions SET status = 'paused' WHERE runtime_session_id = ?",
            (prepared.runtime_session_id,),
        )
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        conn.commit()

    resume = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).resume_task(
        task["task_id"],
        {"id": "owner", "role": "member"},
        idempotency_key="resume-after-paused-worker-crash",
    )
    engine = _AbsentRecoveryEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="paused-dispatcher-b",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )

    recovered = await dispatcher.run_once()
    assert recovered.outcome == "resume_queued"
    assert recovered.attempt_id is not None and recovered.attempt_id != task["attempt_id"]
    assert engine.started_count == 0
    completed = await dispatcher.run_once()
    dispatcher.stop()

    assert completed.outcome == "completed"
    assert engine.started_count == 1
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt_rows = conn.execute(
            """SELECT attempt_id, attempt_seq, trigger, status
               FROM agent_task_attempts WHERE task_id = ? ORDER BY attempt_seq""",
            (task["task_id"],),
        ).fetchall()
        control = conn.execute(
            "SELECT status FROM task_attempt_control_requests WHERE control_request_id = ?",
            (resume["control_request_id"],),
        ).fetchone()

    assert [(row["attempt_seq"], row["trigger"]) for row in attempt_rows] == [
        (1, "initial"),
        (2, "resume"),
    ]
    assert attempt_rows[0]["status"] == "stopped"
    assert attempt_rows[1]["status"] == "succeeded"
    assert control is not None and control["status"] == "completed"


@pytest.mark.anyio
async def test_paused_project_archive_reconciles_after_a_positive_absence_probe(
    state_root: Path, tmp_path: Path
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    original = attempts.claim_next("paused-archive-dispatcher-a", lease_seconds=30)
    assert original is not None
    prepared = attempts.prepare_runtime_launch(original)
    assert attempts.commit_runtime_launch(original, prepared.runtime_session_id)
    attempts.mark_runtime_running(original, prepared.runtime_session_id)
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'paused' WHERE attempt_id = ?",
            (task["attempt_id"],),
        )
        conn.execute("UPDATE tasks SET status = 'paused' WHERE task_id = ?", (task["task_id"],))
        conn.execute(
            "UPDATE agent_runtime_sessions SET status = 'paused' WHERE runtime_session_id = ?",
            (prepared.runtime_session_id,),
        )
        conn.execute(
            "UPDATE task_dispatch_outbox SET claim_expires_at = ? WHERE dispatch_id = ?",
            ("1970-01-01T00:00:00+00:00", task["dispatch_id"]),
        )
        project_id = conn.execute(
            "SELECT project_id FROM tasks WHERE task_id = ?", (task["task_id"],)
        ).fetchone()
        assert project_id is not None
        conn.commit()

    archived = TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).archive_project(
        str(project_id["project_id"]),
        {"id": "owner", "role": "member"},
        reason="archive paused runtime",
        idempotency_key="archive-paused-runtime",
    )
    assert archived["stop_request_ids"]
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="paused-archive-dispatcher-b",
        engine_factory=lambda _engine_type: _AbsentRecoveryEngine(),
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )
    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "stopped_by_project_archive"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (task["attempt_id"],)
        ).fetchone()
        control = conn.execute(
            """SELECT status FROM task_attempt_control_requests
               WHERE attempt_id = ? AND action = 'stop'""",
            (task["attempt_id"],),
        ).fetchone()

    assert attempt is not None and attempt["status"] == "stopped_by_project_archive"
    assert control is not None and control["status"] == "completed"


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
        artifact_sha=V2_ARTIFACT_SHA,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "failed"
    state = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA).dispatch_state(
        task["dispatch_id"]
    )
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
        artifact_sha=V2_ARTIFACT_SHA,
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
    state = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA).dispatch_state(
        task["dispatch_id"]
    )
    assert (state["status"], state["launch_state"]) == ("pending", "none")


@pytest.mark.anyio
async def test_tenant_agent_sdk_is_rejected_before_any_backend_user_launch(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path, harness_engine="agent-sdk")
    monkeypatch.setattr("ainrf.domain.worker._is_container_environment", lambda: True)
    monkeypatch.setattr("ainrf.domain.worker._linux_user_exists", lambda _user: True)
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )

    result = await dispatcher.run_once()
    dispatcher.stop()

    assert result.outcome == "stopped_permission_revoked"
    assert "Agent SDK" in str(result.detail)
    assert engine.started_count == 0


@pytest.mark.anyio
async def test_domain_worker_records_tenant_access_denial_before_runtime_start(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, _, _ = _queued_task(state_root, tmp_path)
    reset_metrics()
    monkeypatch.setattr("ainrf.domain.worker._is_container_environment", lambda: True)
    monkeypatch.setattr("ainrf.domain.worker._linux_user_exists", lambda _user: False)
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-tenant-access-denial",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )

    try:
        result = await dispatcher.run_once()
        assert result.outcome == "stopped_permission_revoked"
        assert "tenant" in str(result.detail).lower()
        assert engine.started_count == 0
        assert (
            'ainrf_domain_permission_denied_total{reason="tenant_owner_required",resource="workspace"} 1.0'
            in get_metrics_text()
        )
    finally:
        dispatcher.stop()
        reset_metrics()


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
        artifact_sha=V2_ARTIFACT_SHA,
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
        artifact_sha=V2_ARTIFACT_SHA,
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
    reset_metrics()
    auth.revoke_environment(environment_id, "owner", reason="revoked before dispatch")
    engine = FakeEngine()
    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="dispatcher-a",
        engine_factory=lambda _engine_type: engine,
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
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
    assert (
        'ainrf_domain_permission_denied_total{reason="environment_grant_required",resource="environment"} 1.0'
        in get_metrics_text()
    )
    reset_metrics()

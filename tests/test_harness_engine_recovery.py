"""Recovery-contract tests for launch-key-aware harness engines."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
    RuntimeProbeStatus,
)
from ainrf.harness_engine.base import EngineEmit
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine
from ainrf.harness_engine.session_state import RuntimeLaunchRegistry
from tests.testutil import FakeEngine

pytestmark = [pytest.mark.unit]


class _DefaultProbeEngine(HarnessEngine):
    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(
        self,
        context: ExecutionContext,
        emit: EngineEmit,
    ) -> None:
        _ = context, emit

    async def cancel(self, task_id: str, *, runtime_launch_key: str | None = None) -> None:
        _ = task_id, runtime_launch_key


async def _discard_event(event: EngineEvent) -> None:
    _ = event


@pytest.mark.anyio
async def test_default_runtime_recovery_contract_is_conservatively_unknown() -> None:
    engine = _DefaultProbeEngine()

    probe = await engine.probe_runtime(task_id="task-1", launch_key="launch-1")
    adoption = await engine.adopt_runtime(task_id="task-1", launch_key="launch-1")

    assert probe.status is RuntimeProbeStatus.UNKNOWN
    assert adoption.status is RuntimeProbeStatus.UNKNOWN


@pytest.mark.anyio
async def test_in_memory_fake_can_probe_adopt_and_confirm_absence() -> None:
    engine = FakeEngine()
    context = ExecutionContext(
        task_id="task-1",
        working_directory="/tmp",
        rendered_prompt="recover this task",
        runtime_launch_key="launch-1",
    )

    await engine.start(context, _discard_event)
    probe = await engine.probe_runtime(task_id="task-1", launch_key="launch-1")
    adoption = await engine.adopt_runtime(task_id="task-1", launch_key="launch-1")

    assert probe.status is RuntimeProbeStatus.RUNNING
    assert probe.engine_session_key == "fake-session-task-1"
    assert adoption.status is RuntimeProbeStatus.RUNNING
    assert adoption.metadata == {"adopted": True}
    assert engine.adopted_runtime_launches == {"launch-1"}

    await engine.cancel("task-1")
    absent = await engine.probe_runtime(task_id="task-1", launch_key="launch-1")

    assert absent.status is RuntimeProbeStatus.ABSENT


@pytest.mark.parametrize(
    "engine_factory",
    [ClaudeCodeEngine, AgentSdkEngine, CodexAppServerEngine],
)
@pytest.mark.anyio
async def test_real_engines_prove_armed_launches_absent_after_dispatcher_crash(
    tmp_path: Path,
    engine_factory: Callable[[], HarnessEngine],
) -> None:
    """An armed record proves no adapter-side external call has happened yet."""

    context = ExecutionContext(
        task_id="task-arm",
        working_directory="/tmp",
        rendered_prompt="recover safely",
        attempt_id="attempt-arm",
        runtime_launch_key="launch-attempt-arm",
        session_state_path=str(tmp_path / "session-states" / "attempt-arm" / "checkpoint.json"),
    )
    predecessor = engine_factory()
    predecessor.bind_runtime_context(context)
    predecessor.arm_runtime_launch(context)

    # Model a worker process restart: only the checkpoint directory survives.
    recovered = engine_factory()
    recovered.bind_runtime_context(context)
    probe = await recovered.probe_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )
    adoption = await recovered.adopt_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )

    assert probe.status is RuntimeProbeStatus.ABSENT
    assert adoption.status is RuntimeProbeStatus.ABSENT


@pytest.mark.parametrize(
    "engine_factory",
    [ClaudeCodeEngine, AgentSdkEngine, CodexAppServerEngine],
)
@pytest.mark.anyio
async def test_real_engines_never_fake_adoption_of_observed_process(
    tmp_path: Path,
    engine_factory: Callable[[], HarnessEngine],
) -> None:
    """PID evidence can prove a runtime lives, not that stdio was reattached."""

    context = ExecutionContext(
        task_id="task-live",
        working_directory="/tmp",
        rendered_prompt="recover safely",
        attempt_id="attempt-live",
        runtime_launch_key="launch-attempt-live",
        session_state_path=str(tmp_path / "session-states" / "attempt-live" / "checkpoint.json"),
    )
    engine_type = engine_factory().engine_type.value
    registry = RuntimeLaunchRegistry(Path(context.session_state_path or ""))
    registry.arm(
        engine_type=engine_type,
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )
    registry.begin_launch(
        engine_type=engine_type,
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
        engine_session_key="engine-session-live",
    )
    registry.mark_running(
        engine_type=engine_type,
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
        process_id=os.getpid(),
        engine_session_key="engine-session-live",
    )

    recovered = engine_factory()
    recovered.bind_runtime_context(context)
    probe = await recovered.probe_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )
    adoption = await recovered.adopt_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )

    assert probe.status is RuntimeProbeStatus.RUNNING
    assert probe.engine_session_key == "engine-session-live"
    assert adoption.status is RuntimeProbeStatus.UNKNOWN
    assert "cannot be reattached" in str(adoption.metadata.get("reason"))


@pytest.mark.anyio
async def test_corrupt_durable_engine_record_is_never_misclassified_as_absent(
    tmp_path: Path,
) -> None:
    context = ExecutionContext(
        task_id="task-corrupt",
        working_directory="/tmp",
        rendered_prompt="recover safely",
        attempt_id="attempt-corrupt",
        runtime_launch_key="launch-attempt-corrupt",
        session_state_path=str(tmp_path / "session-states" / "attempt-corrupt" / "checkpoint.json"),
    )
    registry = RuntimeLaunchRegistry(Path(context.session_state_path or ""))
    registry.arm(
        engine_type=HarnessEngineType.CLAUDE_CODE.value,
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )
    registry.record_path.write_text(json.dumps({"version": 999}), encoding="utf-8")

    engine = ClaudeCodeEngine()
    engine.bind_runtime_context(context)
    probe = await engine.probe_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )

    assert probe.status is RuntimeProbeStatus.UNKNOWN
    assert "Unsupported" in str(probe.metadata.get("reason"))


@pytest.mark.anyio
async def test_agent_sdk_marker_evidence_is_positive_only_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SDK hides child PIDs, so only a positive marker scan is trusted.

    This deliberately stubs the host /proc walk rather than creating an
    unowned subprocess.  The latter can hang under a constrained test runner
    when its child reaper belongs to a different PID namespace; the behaviour
    under test is the adapter's safe interpretation of a positive marker, not
    process management itself.
    """

    context = ExecutionContext(
        task_id="task-sdk-marker",
        working_directory="/tmp",
        rendered_prompt="recover safely",
        attempt_id="attempt-sdk-marker",
        runtime_launch_key="launch-attempt-sdk-marker",
        session_state_path=str(
            tmp_path / "session-states" / "attempt-sdk-marker" / "checkpoint.json"
        ),
    )
    predecessor = AgentSdkEngine()
    predecessor.bind_runtime_context(context)
    predecessor.arm_runtime_launch(context)
    tracker = predecessor._runtime_recovery
    tracker.begin(context, engine_session_key="sdk-session-marker")
    marker_tokens: list[str] = []

    def positively_find_marked_process(token: str) -> int:
        marker_tokens.append(token)
        return os.getpid()

    monkeypatch.setattr(
        "ainrf.harness_engine.session_state._find_marked_process",
        positively_find_marked_process,
    )
    recovered = AgentSdkEngine()
    recovered.bind_runtime_context(context)
    probe = await recovered.probe_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )
    adoption = await recovered.adopt_runtime(
        task_id=context.task_id,
        launch_key=context.runtime_launch_key or "",
    )

    assert marker_tokens
    assert probe.status is RuntimeProbeStatus.RUNNING
    assert probe.engine_session_key == "sdk-session-marker"
    assert adoption.status is RuntimeProbeStatus.UNKNOWN

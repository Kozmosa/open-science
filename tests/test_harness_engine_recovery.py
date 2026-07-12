"""Recovery-contract tests for launch-key-aware harness engines."""

from __future__ import annotations

import pytest

from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
    RuntimeProbeStatus,
)
from ainrf.harness_engine.base import EngineEmit
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

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from ainrf.agentic_researcher import (
    AgenticResearcherService,
    AgenticResearcherType,
    HarnessEngineType,
    TaskStatus,
    vanilla,
)
from ainrf.agentic_researcher.service import TaskNotFoundError
from ainrf.harness_engine import EngineEvent, ExecutionContext, HarnessEngine
from ainrf.harness_engine.base import EngineEmit


class FakeEngine(HarnessEngine):
    def __init__(self) -> None:
        self.pending_prompts: list[str] = []

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        prompt = self.pending_prompts.pop(0) if self.pending_prompts else context.rendered_prompt
        await emit(
            EngineEvent(
                event_type="message",
                payload={"role": "assistant", "content": f"ran: {prompt}"},
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )

    async def cancel(self, task_id: str) -> None:
        _ = task_id
        return None

    async def send_input(self, task_id: str, text: str) -> None:
        _ = task_id
        self.pending_prompts.append(text)


@pytest.fixture
def service() -> Iterator[AgenticResearcherService]:
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = AgenticResearcherService(state_root=Path(tmpdir))
        svc.initialize()
        yield svc


def test_create_task(service: AgenticResearcherService) -> None:
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE, user_skills=["test-skill"])
    task = service.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=researcher,
        prompt="Test prompt",
        owner_user_id="user-001",
        title="Test Task",
    )
    assert task.task_id is not None
    assert task.status == TaskStatus.QUEUED
    assert task.researcher_type == AgenticResearcherType.VANILLA
    assert task.harness_engine == HarnessEngineType.CLAUDE_CODE
    assert task.user_skills == ["test-skill"]


def test_get_task(service: AgenticResearcherService) -> None:
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    created = service.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=researcher,
        prompt="Test prompt",
        owner_user_id="user-001",
    )
    fetched = service.get_task(created.task_id)
    assert fetched.task_id == created.task_id
    assert fetched.prompt == "Test prompt"


def test_get_task_not_found(service: AgenticResearcherService) -> None:
    with pytest.raises(TaskNotFoundError):
        service.get_task("non-existent")


def test_list_tasks(service: AgenticResearcherService) -> None:
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    for i in range(3):
        service.create_task(
            project_id="proj-001",
            workspace_id="ws-001",
            environment_id="env-001",
            researcher=researcher,
            prompt=f"Prompt {i}",
            owner_user_id="user-001",
        )
    tasks = service.list_tasks(project_id="proj-001")
    assert len(tasks) == 3


def test_list_tasks_with_filters(service: AgenticResearcherService) -> None:
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    task = service.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=researcher,
        prompt="Test prompt",
        owner_user_id="user-001",
    )
    # Cancel one task - it should be excluded when include_archived=False
    service.cancel_task(task.task_id)

    # Default: exclude cancelled (archived)
    tasks = service.list_tasks(project_id="proj-001", include_archived=False)
    assert len(tasks) == 0

    # Include archived
    tasks = service.list_tasks(project_id="proj-001", include_archived=True)
    assert len(tasks) == 1

    # Limit
    for i in range(5):
        service.create_task(
            project_id="proj-001",
            workspace_id="ws-001",
            environment_id="env-001",
            researcher=researcher,
            prompt=f"Prompt {i}",
            owner_user_id="user-001",
        )
    tasks = service.list_tasks(project_id="proj-001", limit=2)
    assert len(tasks) == 2

    # Sort by updated
    tasks = service.list_tasks(project_id="proj-001", sort="updated")
    assert len(tasks) == 5
    # Most recently updated should be last created (updated_at set on creation)
    assert tasks[0].prompt == "Prompt 4"


def test_cancel_task(service: AgenticResearcherService) -> None:
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    task = service.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=researcher,
        prompt="Test prompt",
        owner_user_id="user-001",
    )
    cancelled = service.cancel_task(task.task_id)
    assert cancelled.status == TaskStatus.CANCELLED


@pytest.mark.anyio
async def test_run_task_persists_output_and_succeeds(tmp_path: Path) -> None:
    fake_engine = FakeEngine()
    svc = AgenticResearcherService(
        state_root=tmp_path,
        engine_factory=lambda _name: fake_engine,
    )
    svc.initialize()
    task = svc.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
        prompt="Test prompt",
        owner_user_id="user-001",
    )

    await svc.run_task(task.task_id)

    completed = svc.get_task(task.task_id)
    assert completed.status == TaskStatus.SUCCEEDED
    output = svc.get_output(task.task_id)
    assert [item.content for item in output] == [
        "ran: Test prompt",
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
    ]
    assert completed.latest_output_seq == 2


@pytest.mark.anyio
async def test_send_prompt_to_succeeded_task_schedules_followup(tmp_path: Path) -> None:
    fake_engine = FakeEngine()
    svc = AgenticResearcherService(
        state_root=tmp_path,
        engine_factory=lambda _name: fake_engine,
    )
    svc.initialize()
    task = svc.create_task(
        project_id="proj-001",
        workspace_id="ws-001",
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
        prompt="Initial prompt",
        owner_user_id="user-001",
    )

    await svc.run_task(task.task_id)
    prompt_event = await svc.send_prompt(task.task_id, "Follow up")

    for _ in range(20):
        current = svc.get_task(task.task_id)
        if current.status == TaskStatus.SUCCEEDED and current.latest_output_seq >= 5:
            break
        await asyncio.sleep(0.05)

    completed = svc.get_task(task.task_id)
    output = svc.get_output(task.task_id)
    assert prompt_event.seq == 3
    assert completed.status == TaskStatus.SUCCEEDED
    assert [item.content for item in output] == [
        "ran: Initial prompt",
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        '{"role": "user", "content": "Follow up"}',
        "ran: Follow up",
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
    ]

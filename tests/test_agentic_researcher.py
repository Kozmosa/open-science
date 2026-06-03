from __future__ import annotations

import tempfile
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


@pytest.fixture
def service() -> AgenticResearcherService:
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
    assert task.status == TaskStatus.PENDING
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

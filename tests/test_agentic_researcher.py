from __future__ import annotations

import asyncio
import json
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
from tests.testutil import FakeEngine

pytestmark = [pytest.mark.unit]


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
    assert [item.kind for item in output] == ["message", "message", "lifecycle"]
    assert [item.content for item in output] == [
        '{"role": "user", "content": "Test prompt"}',
        '{"role": "assistant", "content": "ran: Test prompt"}',
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
    ]
    assert completed.latest_output_seq == 3


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
        if current.status == TaskStatus.SUCCEEDED and current.latest_output_seq >= 6:
            break
        await asyncio.sleep(0.05)

    completed = svc.get_task(task.task_id)
    output = svc.get_output(task.task_id)
    assert prompt_event.seq == 4
    assert completed.status == TaskStatus.SUCCEEDED
    assert [item.content for item in output] == [
        '{"role": "user", "content": "Initial prompt"}',
        '{"role": "assistant", "content": "ran: Initial prompt"}',
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        '{"role": "user", "content": "Follow up"}',
        '{"role": "assistant", "content": "ran: Follow up"}',
        '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
    ]


def test_resolve_skill_load_dir_returns_none_when_no_skills(tmp_path: Path) -> None:
    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    assert svc._resolve_skill_load_dir(task) is None


def test_resolve_skill_load_dir_returns_none_when_load_dir_missing(tmp_path: Path) -> None:
    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE, user_skills=["research-lit"])
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    # No skill load directory exists yet
    assert svc._resolve_skill_load_dir(task) is None


def test_resolve_skill_load_dir_finds_installed_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_resolve_skill_load_dir returns the load dir when skills exist."""
    # Pretend HOME is tmp_path so RuntimePathConfig.default_workspace_dir lands there
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace_dir = tmp_path / ".ainrf_workspaces" / "default"
    load_dir = workspace_dir / "skills"
    skill_dir = load_dir / "research-lit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# research-lit\n")

    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE, user_skills=["research-lit"])
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    result = svc._resolve_skill_load_dir(task)
    assert result is not None
    assert "skills" in result
    assert (Path(result) / "research-lit").is_dir()


def test_build_execution_context_includes_skill_load_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_build_execution_context populates skill_load_dir when skills are available."""
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace_dir = tmp_path / ".ainrf_workspaces" / "default"
    load_dir = workspace_dir / "skills"
    skill_dir = load_dir / "arxiv"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# arxiv\n")

    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE, user_skills=["arxiv"])
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    ctx = svc._build_execution_context(task)
    assert ctx.skill_load_dir is not None
    assert ctx.skills == ["arxiv"]


def test_build_execution_context_adds_codex_mcp_when_skill_declares_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP is automatically added when a selected skill declares it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace_dir = tmp_path / ".ainrf_workspaces" / "default"
    load_dir = workspace_dir / "skills"
    skill_dir = load_dir / "research-lit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# research-lit\n")
    (skill_dir / "skill.json").write_text(
        json.dumps({"skill_id": "research-lit", "mcp_servers": ["codex"]})
    )

    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE, user_skills=["research-lit"])
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    ctx = svc._build_execution_context(task)
    assert ctx.mcp_servers is not None
    assert "codex" in ctx.mcp_servers
    assert ctx.mcp_servers["codex"]["command"] == "codex"
    assert ctx.mcp_servers["codex"]["args"] == ["mcp-server"]


def test_build_execution_context_no_codex_mcp_without_skills(
    tmp_path: Path,
) -> None:
    """Codex MCP is NOT added when no ARIS skills are loaded."""
    svc = AgenticResearcherService(state_root=tmp_path)
    svc.initialize()
    researcher = vanilla(engine=HarnessEngineType.CLAUDE_CODE)
    task = svc.create_task(
        project_id="p",
        workspace_id="ws",
        environment_id="env",
        researcher=researcher,
        prompt="test",
        owner_user_id="u",
    )
    ctx = svc._build_execution_context(task)
    # No skills loaded → no codex MCP (mcp_servers may be None or empty)
    if ctx.mcp_servers:
        assert "codex" not in ctx.mcp_servers

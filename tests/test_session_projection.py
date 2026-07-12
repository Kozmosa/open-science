"""V2 Session API projection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.domain import (
    AttemptService,
    DomainService,
    ProjectContextService,
    SessionProjectionService,
)

pytestmark = [pytest.mark.unit]


def test_task_attempts_project_to_session_and_attempts(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    domain = DomainService(state_root)
    project = domain.create_project(owner, name="Project")
    context = ProjectContextService(state_root)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    task = tasks.create_task(
        str(project["project_id"]),
        "workspace",
        "environment",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "prompt",
        "owner",
    )
    AttemptService(state_root).create_attempt(task.task_id, trigger="initial")

    session, attempts = SessionProjectionService(state_root).get_session(task.task_id, owner)

    assert session["id"] == task.task_id
    assert session["task_count"] == 1
    assert attempts[0]["task_id"] == task.task_id

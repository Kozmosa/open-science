"""Project Context immutability and Task pin tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.domain import DomainService, ProjectContextService

pytestmark = [pytest.mark.unit]


def _admin() -> dict[str, object]:
    return {"id": "admin", "role": "admin"}


def _user(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def test_publish_is_immutable_and_task_pins_active_version(state_root: Path) -> None:
    domain = DomainService(state_root)
    context = ProjectContextService(state_root)
    owner = _user("owner")
    project = domain.create_project(owner, name="Project")
    project_id = str(project["project_id"])
    context.save_draft(project_id, "first", owner)
    first = context.publish(project_id, owner)
    context.save_draft(project_id, "second", owner)
    second = context.publish(project_id, owner)
    assert first["context_version_id"] != second["context_version_id"]

    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    task = tasks.create_task(
        project_id,
        "workspace",
        "environment",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "prompt",
        "owner",
    )
    snapshot_id = context.pin_active_context(task.task_id, project_id)
    assert snapshot_id.startswith("snapshot-")
    with tasks._connect() as conn:
        pinned = conn.execute(
            "SELECT project_context_version_id FROM tasks WHERE task_id = ?", (task.task_id,)
        ).fetchone()
        snapshot = conn.execute(
            "SELECT content FROM context_snapshots WHERE context_snapshot_id = ?", (snapshot_id,)
        ).fetchone()
    assert pinned["project_context_version_id"] == second["context_version_id"]
    assert "## Project Brief\nsecond" in snapshot["content"]

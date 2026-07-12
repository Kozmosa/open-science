"""Durable Attempt/outbox claim and RuntimeSession tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.domain import AttemptService, DomainService, ProjectContextService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def test_attempt_creation_claim_and_runtime_launch(state_root: Path) -> None:
    domain = DomainService(state_root)
    owner: dict[str, object] = {"id": "owner", "role": "member"}
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

    attempts = AttemptService(state_root)
    attempt_id = attempts.create_attempt(task.task_id, trigger="initial")
    claim = attempts.claim_next("dispatcher-a")
    assert claim is not None and claim.attempt_id == attempt_id
    assert attempts.claim_next("dispatcher-b") is None
    runtime_id = attempts.mark_runtime_started(claim)
    assert runtime_id.startswith("runtime-")

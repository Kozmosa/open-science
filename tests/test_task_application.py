"""Standard Task application service atomic/idempotent workflow tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain import DomainService, ProjectContextService, TaskApplicationService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def test_create_and_retry_task_share_task_id_and_outbox(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = DomainService(state_root)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    project = domain.create_project(owner, name="Project")
    workspace = domain.create_workspace(
        owner,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/task-app",
        label="Task",
    )
    domain.attach_workspace(
        str(project["project_id"]), str(workspace["workspace_id"]), owner, idempotency_key="link"
    )
    context = ProjectContextService(state_root)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    tasks = TaskApplicationService(state_root)

    created = tasks.create_task(
        owner,
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
        title="Task",
        prompt="Prompt",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="create",
    )
    repeated = tasks.create_task(
        owner,
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
        title="Task",
        prompt="Prompt",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="create",
    )
    retry = tasks.retry_task(created["task_id"], owner, idempotency_key="retry")

    assert repeated == created
    assert retry["task_id"] == created["task_id"]
    assert retry["attempt_id"] != created["attempt_id"]

"""Project Context immutability and Task pin tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextlib import closing

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService, TaskApplicationService
from ainrf.domain.service import DomainConflictError

pytestmark = [pytest.mark.unit]


def _admin() -> dict[str, object]:
    return {"id": "admin", "role": "admin"}


def _user(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def test_publish_is_immutable_and_task_pins_active_version(
    state_root: Path,
    tmp_path: Path,
    committed_v2_state: str,
) -> None:
    domain = DomainService(state_root, artifact_sha=committed_v2_state)
    context = ProjectContextService(state_root, artifact_sha=committed_v2_state)
    owner = _user("owner")
    admin = _admin()
    environment = domain.create_environment(
        admin,
        alias="project-context-host",
        display_name="Project context host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="project context pin test",
    )
    project = domain.create_project(owner, name="Project")
    project_id = str(project["project_id"])
    context.save_draft(project_id, "first", owner)
    first = context.publish(project_id, owner)
    context.save_draft(project_id, "second", owner)
    second = context.publish(project_id, owner)
    assert first["context_version_id"] != second["context_version_id"]

    workspace_path = tmp_path / "project-context-workspace"
    workspace_path.mkdir()
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Project context workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, owner, idempotency_key="project-context-link")
    task = TaskApplicationService(state_root, artifact_sha=committed_v2_state).create_task(
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        title="Context pinned task",
        prompt="prompt",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="project-context-task",
    )
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        pinned = conn.execute(
            """SELECT project_context_version_id, project_context_snapshot_id
               FROM tasks WHERE task_id = ?""",
            (task["task_id"],),
        ).fetchone()
        snapshot = conn.execute(
            "SELECT content FROM context_snapshots WHERE context_snapshot_id = ?",
            (pinned["project_context_snapshot_id"],),
        ).fetchone()
    assert pinned is not None
    assert pinned["project_context_version_id"] == second["context_version_id"]
    assert "## Project Brief\nsecond" in snapshot["content"]
    with pytest.raises(DomainConflictError, match="Task Context mutations"):
        context.pin_active_context(str(task["task_id"]), project_id)

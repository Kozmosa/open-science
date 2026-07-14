"""Standard Task application service atomic/idempotent workflow tests."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService, TaskApplicationService
from ainrf.auth.service import AuthService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def test_create_and_retry_task_share_task_id_and_outbox(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = DomainService(state_root, artifact_sha=committed_v2_state)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="task application test",
    )
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
    context = ProjectContextService(state_root, artifact_sha=committed_v2_state)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    tasks = TaskApplicationService(state_root, artifact_sha=committed_v2_state)

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
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        snapshot = conn.execute(
            """SELECT snapshot.content, snapshot.source_manifest_json
               FROM tasks AS task
               JOIN context_snapshots AS snapshot
                 ON snapshot.context_snapshot_id = task.project_context_snapshot_id
               WHERE task.task_id = ?""",
            (created["task_id"],),
        ).fetchone()
        retry_snapshot = conn.execute(
            """SELECT context_snapshot_id FROM agent_task_attempts
               WHERE attempt_id = ?""",
            (retry["attempt_id"],),
        ).fetchone()
        initial_snapshot = conn.execute(
            """SELECT context_snapshot_id FROM agent_task_attempts
               WHERE attempt_id = ?""",
            (created["attempt_id"],),
        ).fetchone()
    assert snapshot is not None
    assert "## Project Brief\ncontext" in snapshot["content"]
    assert "## Task Request\nPrompt" in snapshot["content"]
    manifest = json.loads(snapshot["source_manifest_json"])
    assert [entry["source_type"] for entry in manifest] == [
        "platform_constraints",
        "project_brief",
        "workspace_context",
        "task_request",
    ]
    assert retry_snapshot is not None
    assert initial_snapshot is not None
    assert retry_snapshot["context_snapshot_id"] == initial_snapshot["context_snapshot_id"]

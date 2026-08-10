"""Project Context immutability and Task pin tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from contextlib import closing

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import ConversationApplicationService, ProjectContextService, build_domain_modules

pytestmark = [pytest.mark.unit]


def _admin() -> dict[str, object]:
    return {"id": "admin", "role": "admin"}


def _user(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def test_context_service_has_one_active_snapshot_helper() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    source_path = repository_root / "src" / "ainrf" / "domain" / "context.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    services = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProjectContextService"
    ]
    assert len(services) == 1

    helpers = [
        node
        for node in services[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_create_active_snapshot_for_task_in_transaction"
    ]
    assert len(helpers) == 1
    assert helpers[0].decorator_list == []
    called_methods = {
        node.func.attr
        for node in ast.walk(helpers[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"_active_version", "_assemble_for_task", "_insert_snapshot"} <= called_methods


def test_publish_is_immutable_and_task_pins_active_version(
    state_root: Path,
    tmp_path: Path,
    committed_v2_state: str,
) -> None:
    domain = build_domain_modules(state_root, artifact_sha=committed_v2_state)
    context = ProjectContextService(state_root, artifact_sha=committed_v2_state)
    owner = _user("owner")
    admin = _admin()
    environment = domain.environments.create_environment(
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
    project = domain.projects.create_project(owner, name="Project")
    project_id = str(project["project_id"])
    context.save_draft(project_id, "first", owner)
    first = context.publish(project_id, owner)
    context.save_draft(project_id, "second", owner)
    second = context.publish(project_id, owner)
    assert first["context_version_id"] != second["context_version_id"]

    workspace_path = tmp_path / "project-context-workspace"
    workspace_path.mkdir()
    workspace = domain.workspaces.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Project context workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.projects.attach_workspace(
        project_id, workspace_id, owner, idempotency_key="project-context-link"
    )
    task = ConversationApplicationService(state_root, artifact_sha=committed_v2_state).create_task(
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
    assert not hasattr(context, "pin_active_context")

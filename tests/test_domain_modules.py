"""Observable behavior at the Project, Workspace, and Environment Interfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain import ProjectModule, build_domain_modules
from ainrf.auth.service import AuthService
from tests.testutil import seed_user

pytestmark = [pytest.mark.unit]


def test_domain_modules_share_one_transactional_write_kernel(
    state_root: Path, committed_v2_state: str
) -> None:
    modules = build_domain_modules(state_root, artifact_sha=committed_v2_state)
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    auth = AuthService(state_root=state_root)
    auth.initialize()
    seed_user(auth, username="module-owner", role="member", user_id="owner")
    seed_user(auth, username="module-admin", role="admin", user_id="admin")

    environment = modules.environments.create_environment(
        admin,
        alias="host",
        display_name="Host",
        connection={},
        idempotency_key="environment-create",
    )
    project = modules.projects.create_project(
        owner, name="Project", idempotency_key="project-create"
    )
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="domain module interface test",
    )
    workspace = modules.workspaces.create_workspace(
        owner,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/domain-module-workspace",
        label="Workspace",
        idempotency_key="workspace-create",
    )
    link = modules.projects.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        owner,
        idempotency_key="workspace-link",
    )

    assert link["project_id"] == project["project_id"]
    assert modules.projects.project(str(project["project_id"]), owner)["name"] == "Project"
    assert modules.workspaces.workspace(str(workspace["workspace_id"]), owner)["status"] == "active"
    assert (
        modules.environments.environment(str(environment["environment_id"]), admin)["alias"]
        == "host"
    )


def test_aggregate_interfaces_do_not_expose_other_aggregate_methods(
    state_root: Path, committed_v2_state: str
) -> None:
    modules = build_domain_modules(state_root, artifact_sha=committed_v2_state)

    assert "create_workspace" not in ProjectModule.__dict__
    assert not hasattr(modules, "repository")

"""Read-only v2 Workspace facade contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.domain import DomainService
from ainrf.domain.workspace_facade import PersistentWorkspaceFacade

pytestmark = [pytest.mark.unit]


def test_persistent_workspace_facade_reads_domain_workspace_without_json_registry(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    domain = DomainService(state_root, artifact_sha=committed_v2_state)
    environment = domain.create_environment(
        admin,
        alias="workspace-facade-host",
        display_name="Workspace facade host",
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
        reason="workspace facade test",
    )
    project = domain.create_project(owner, name="Facade project")
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Facade workspace",
    )
    domain.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        owner,
        idempotency_key="facade-link",
    )

    facade = PersistentWorkspaceFacade(state_root)
    resolved = facade.get_workspace(str(workspace["workspace_id"]))
    linked = facade.list_workspaces(project_id=str(project["project_id"]))

    assert resolved.workspace_id == workspace["workspace_id"]
    assert resolved.default_workdir == str(workspace_path.resolve())
    assert resolved.project_id == ""
    assert [item.workspace_id for item in linked] == [workspace["workspace_id"]]
    assert not (state_root / "runtime" / "workspaces.json").exists()

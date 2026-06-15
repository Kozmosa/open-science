"""Direct tests for WorkspaceRegistryService."""

from __future__ import annotations

import pytest

from ainrf.workspaces.service import WorkspaceDeletionError, WorkspaceNotFoundError

pytestmark = [pytest.mark.unit]


class TestWorkspaceRegistryService:
    def test_create_and_get_workspace(self, workspace_service):
        ws = workspace_service.create_workspace(
            label="Research",
            description="desc",
            default_workdir=None,
            workspace_prompt="prompt",
            owner_user_id="user-1",
        )
        fetched = workspace_service.get_workspace(ws.workspace_id)
        assert fetched.workspace_id == ws.workspace_id
        assert fetched.label == "Research"
        assert fetched.owner_user_id == "user-1"

    def test_list_workspaces_filters_by_owner(self, workspace_service):
        w1 = workspace_service.create_workspace(
            label="A",
            description="a",
            default_workdir=None,
            workspace_prompt="p",
            owner_user_id="user-1",
        )
        workspace_service.create_workspace(
            label="B",
            description="b",
            default_workdir=None,
            workspace_prompt="p",
            owner_user_id="user-2",
        )

        results = workspace_service.list_workspaces(owner_user_id="user-1")
        assert len(results) == 1
        assert results[0].workspace_id == w1.workspace_id

    def test_update_workspace(self, workspace_service):
        ws = workspace_service.create_workspace(
            label="Old",
            description="old",
            default_workdir=None,
            workspace_prompt="p",
            owner_user_id="user-1",
        )
        updated = workspace_service.update_workspace(
            ws.workspace_id, label="New", description="new"
        )
        assert updated.label == "New"
        assert updated.description == "new"

    def test_delete_default_workspace_is_rejected(self, workspace_service):
        with pytest.raises(WorkspaceDeletionError, match="Default workspace cannot be deleted"):
            workspace_service.delete_workspace("workspace-default")

    def test_get_nonexistent_workspace_raises(self, workspace_service):
        with pytest.raises(WorkspaceNotFoundError):
            workspace_service.get_workspace("does-not-exist")

    def test_create_workspace_with_workdir(self, tmp_path, workspace_service):
        workdir = tmp_path / "workspaces" / "research"
        ws = workspace_service.create_workspace(
            label="WithDir",
            description="d",
            default_workdir=str(workdir),
            workspace_prompt="p",
            owner_user_id="user-1",
        )
        assert ws.default_workdir == str(workdir.resolve())
        assert workdir.exists()

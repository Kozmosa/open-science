"""JSON-file persistence edge cases for project/workspace registries."""

from __future__ import annotations

import json

import pytest

from ainrf.projects.service import ProjectRegistryService
from ainrf.workspaces.service import WorkspaceRegistryService
from tests.testutil import corrupt_json_file, load_json, truncate_file

pytestmark = [pytest.mark.unit, pytest.mark.json_edge]


class TestProjectsRegistryEdgeCases:
    def test_projects_registry_empty_file_creates_seed(self, state_root):
        registry_path = state_root / "runtime" / "projects.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        truncate_file(registry_path)

        svc = ProjectRegistryService(state_root=state_root)
        svc.initialize()

        projects = svc.list_projects()
        assert any(p.project_id == "default" for p in projects)

    def test_projects_registry_malformed_json_raises(self, state_root):
        registry_path = state_root / "runtime" / "projects.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_json_file(registry_path)

        svc = ProjectRegistryService(state_root=state_root)
        with pytest.raises(json.JSONDecodeError):
            svc.initialize()

    def test_projects_registry_persists_unicode(self, state_root):
        svc = ProjectRegistryService(state_root=state_root)
        svc.initialize()
        project = svc.create_project(
            name="中文项目", description="unicode test", owner_user_id="user-1"
        )

        # Re-load from disk to verify round-trip.
        svc2 = ProjectRegistryService(state_root=state_root)
        svc2.initialize()
        reloaded = svc2.get_project(project.project_id)
        assert reloaded.name == "中文项目"

    def test_task_edges_registry_roundtrip(self, state_root):
        svc = ProjectRegistryService(state_root=state_root)
        svc.initialize()
        project = svc.create_project(name="p", description="p", owner_user_id="user-1")

        edge = svc.create_task_edge(
            project_id=project.project_id,
            source_task_id="task-a",
            target_task_id="task-b",
        )

        svc2 = ProjectRegistryService(state_root=state_root)
        svc2.initialize()
        edges = svc2.list_task_edges(project.project_id)
        assert any(e.edge_id == edge.edge_id for e in edges)


class TestWorkspacesRegistryEdgeCases:
    def test_workspaces_registry_empty_file_creates_seed(self, state_root):
        registry_path = state_root / "runtime" / "workspaces.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        truncate_file(registry_path)

        svc = WorkspaceRegistryService(state_root=state_root)
        svc.initialize()

        workspaces = svc.list_workspaces()
        assert any(w.workspace_id == "workspace-default" for w in workspaces)

    def test_workspaces_registry_malformed_json_raises(self, state_root):
        registry_path = state_root / "runtime" / "workspaces.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_json_file(registry_path)

        svc = WorkspaceRegistryService(state_root=state_root)
        with pytest.raises(json.JSONDecodeError):
            svc.initialize()

    def test_atomic_write_json_produces_valid_json(self, state_root):
        svc = WorkspaceRegistryService(state_root=state_root)
        svc.initialize()
        svc.create_workspace(
            label="test",
            description="d",
            default_workdir=None,
            workspace_prompt="p",
            owner_user_id="user-1",
        )

        registry_path = state_root / "runtime" / "workspaces.json"
        data = load_json(registry_path)
        assert "items" in data
        assert len(data["items"]) >= 1

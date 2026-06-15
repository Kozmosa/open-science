"""Direct tests for ProjectRegistryService."""

from __future__ import annotations

import pytest

from ainrf.projects.service import ProjectNotFoundError

pytestmark = [pytest.mark.unit]


class TestProjectRegistryService:
    def test_create_and_get_project(self, project_service):
        project = project_service.create_project(
            name="Research", description="desc", owner_user_id="user-1"
        )
        fetched = project_service.get_project(project.project_id)
        assert fetched.project_id == project.project_id
        assert fetched.name == "Research"
        assert fetched.owner_user_id == "user-1"

    def test_list_projects_filters_by_owner(self, project_service):
        p1 = project_service.create_project(name="A", description="a", owner_user_id="user-1")
        _p2 = project_service.create_project(name="B", description="b", owner_user_id="user-2")

        results = project_service.list_projects(owner_user_id="user-1")
        assert len(results) == 1
        assert results[0].project_id == p1.project_id

    def test_update_project(self, project_service):
        project = project_service.create_project(
            name="Old", description="old", owner_user_id="user-1"
        )
        updated = project_service.update_project(project.project_id, name="New", description="new")
        assert updated.name == "New"
        assert updated.description == "new"

    def test_delete_default_project_is_rejected(self, project_service):
        with pytest.raises(ValueError, match="Default project cannot be deleted"):
            project_service.delete_project("default")

    def test_get_nonexistent_project_raises(self, project_service):
        with pytest.raises(ProjectNotFoundError):
            project_service.get_project("does-not-exist")

    def test_task_edges_create_and_delete(self, project_service):
        project = project_service.create_project(name="p", description="p", owner_user_id="user-1")
        edge = project_service.create_task_edge(
            project_id=project.project_id,
            source_task_id="task-a",
            target_task_id="task-b",
        )

        # Duplicate edge is idempotent.
        edge2 = project_service.create_task_edge(
            project_id=project.project_id,
            source_task_id="task-a",
            target_task_id="task-b",
        )
        assert edge.edge_id == edge2.edge_id

        edges = project_service.list_task_edges(project.project_id)
        assert len(edges) == 1

        project_service.delete_task_edge(edge.edge_id)
        assert len(project_service.list_task_edges(project.project_id)) == 0

    def test_delete_project_cascades_to_task_edges(self, project_service):
        project = project_service.create_project(name="p", description="p", owner_user_id="user-1")
        edge = project_service.create_task_edge(
            project_id=project.project_id,
            source_task_id="task-a",
            target_task_id="task-b",
        )

        # Create another project so deletion is allowed.
        project_service.create_project(name="p2", description="p2", owner_user_id="user-1")
        project_service.delete_project(project.project_id)

        assert edge.edge_id not in project_service._task_edges

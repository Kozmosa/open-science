from __future__ import annotations

import asyncio

import httpx

from ainrf.environments.models import EnvironmentAuthKind
from ainrf.environments.service import InMemoryEnvironmentService
from ainrf.task_harness.service import TaskHarnessService
from ainrf.workspaces.service import WorkspaceRegistryService


def _make_service(tmp_path):
    environment_service = InMemoryEnvironmentService()
    environment = environment_service.create_environment(
        alias="profile-lab",
        display_name="Profile Lab",
        host="127.0.0.1",
        auth_kind=EnvironmentAuthKind.SSH_KEY,
        default_workdir=str(tmp_path),
    )
    workspace_service = WorkspaceRegistryService(tmp_path, default_workspace_dir=tmp_path)
    workspace_service.initialize()
    service = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    service.initialize()
    return service, environment


def test_create_and_list_task_edges(tmp_path, monkeypatch):
    service, _environment = _make_service(tmp_path)
    task1 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 1",
    )
    task2 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 2",
    )
    edge = service.create_task_edge("default", task1.task_id, task2.task_id)
    assert edge.source_task_id == task1.task_id
    assert edge.target_task_id == task2.task_id
    edges = service.get_task_edges("default")
    assert len(edges) == 1
    assert edges[0].edge_id == edge.edge_id


def test_delete_task_edge(tmp_path, monkeypatch):
    service, _environment = _make_service(tmp_path)
    task1 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 1",
    )
    task2 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 2",
    )
    edge = service.create_task_edge("default", task1.task_id, task2.task_id)
    assert len(service.get_task_edges("default")) == 1
    service.delete_task_edge(edge.edge_id)
    assert len(service.get_task_edges("default")) == 0


def test_auto_connect_on_create_task(tmp_path, monkeypatch):
    service, _environment = _make_service(tmp_path)
    task1 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 1",
    )
    task2 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 2",
        auto_connect=True,
    )
    edges = service.get_task_edges("default")
    assert len(edges) == 1
    assert edges[0].source_task_id == task1.task_id
    assert edges[0].target_task_id == task2.task_id


def test_auto_connect_skips_archived_task(tmp_path, monkeypatch):
    service, _environment = _make_service(tmp_path)
    task1 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 1",
    )
    service.archive_task(task1.task_id)
    task2 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 2",
    )
    task3 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 3",
        auto_connect=True,
    )
    edges = service.get_task_edges("default")
    assert len(edges) == 1
    assert edges[0].source_task_id == task2.task_id
    assert edges[0].target_task_id == task3.task_id


API_HEADERS = {"X-API-Key": "test-key"}


def test_api_create_and_list_edges(tmp_path, monkeypatch):
    from ainrf.api.app import create_app
    from ainrf.api.config import ApiConfig, hash_api_key

    config = ApiConfig(
        state_root=tmp_path,
        api_key_hashes=frozenset({hash_api_key("test-key")}),
        code_server_host="127.0.0.1",
        code_server_port=8080,
    )
    app = create_app(config)
    service = app.state.task_harness_service
    task1 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 1",
    )
    task2 = service.create_task(
        project_id="default",
        workspace_id="workspace-default",
        environment_id="env-localhost",
        task_profile="claude-code",
        task_input="task 2",
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            create_resp = await client.post(
                "/projects/default/task-edges",
                headers=API_HEADERS,
                json={"source_task_id": task1.task_id, "target_task_id": task2.task_id},
            )
            assert create_resp.status_code == 201
            created = create_resp.json()
            assert created["source_task_id"] == task1.task_id

            list_resp = await client.get("/projects/default/task-edges", headers=API_HEADERS)
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]
            assert len(items) == 1

            delete_resp = await client.delete(
                f"/projects/default/task-edges/{created['edge_id']}", headers=API_HEADERS
            )
            assert delete_resp.status_code == 204

    asyncio.run(run())

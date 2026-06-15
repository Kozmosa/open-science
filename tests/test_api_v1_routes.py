from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.execution import ContainerConfig
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


def make_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


def make_auth_client(
    tmp_path: Path, username: str = "admin", password: str = "test-admin-password"
):
    """Create an authenticated async client with JWT Bearer headers."""
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    headers = get_jwt_headers(app, username=username, password=password)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/health", "/v1/health"])
async def test_health_routes_are_public(tmp_path: Path, path: str) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_openapi_registers_projects_terminal_task_harness_and_code_routes(
    tmp_path: Path,
) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    # Routes are registered under /, /v1/, and /api/ prefixes
    non_root_prefixes = {p for p in payload["paths"] if not p.startswith(("/v1/", "/api/"))}
    assert {f"/v1{p}" for p in non_root_prefixes} == {
        p for p in payload["paths"] if p.startswith("/v1/") and not p.startswith("/v1/api/")
    }
    assert {f"/api{p}" for p in non_root_prefixes} == {
        p for p in payload["paths"] if p.startswith("/api/") and not p.startswith("/api/v1/")
    }
    assert "/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/v1/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/api/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/projects/{project_id}/task-edges" in payload["paths"]
    assert "/task-edges/{edge_id}" in payload["paths"]
    assert "/v1/projects/{project_id}/task-edges" in payload["paths"]
    assert "/v1/task-edges/{edge_id}" in payload["paths"]
    assert "/workspaces" in payload["paths"]
    assert "/workspaces/{workspace_id}" in payload["paths"]
    assert "/v1/workspaces" in payload["paths"]
    assert "/v1/workspaces/{workspace_id}" in payload["paths"]
    assert "post" in payload["paths"]["/workspaces"]
    assert "patch" in payload["paths"]["/workspaces/{workspace_id}"]
    assert "delete" in payload["paths"]["/workspaces/{workspace_id}"]
    assert "post" in payload["paths"]["/v1/workspaces"]
    assert "patch" in payload["paths"]["/v1/workspaces/{workspace_id}"]
    assert "delete" in payload["paths"]["/v1/workspaces/{workspace_id}"]
    assert "/terminal/session" in payload["paths"]
    assert "/terminal/session-pairs" in payload["paths"]
    assert "/terminal/session/reset" in payload["paths"]
    assert "/v1/terminal/session" in payload["paths"]
    assert "/v1/terminal/session-pairs" in payload["paths"]
    assert "/v1/terminal/session/reset" in payload["paths"]
    assert "/tasks" in payload["paths"]
    assert "/tasks/{task_id}" in payload["paths"]
    assert "/tasks/{task_id}/output" in payload["paths"]
    assert "/tasks/{task_id}/stream" in payload["paths"]
    assert "/v1/tasks" in payload["paths"]
    assert "/v1/tasks/{task_id}" in payload["paths"]
    assert "/v1/tasks/{task_id}/output" in payload["paths"]
    assert "/v1/tasks/{task_id}/stream" in payload["paths"]
    assert "/tasks/{task_id}/cancel" in payload["paths"]
    assert "/tasks/{task_id}/terminal" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/open" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/takeover" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/release" not in payload["paths"]
    assert "/v1/tasks/{task_id}/cancel" in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/open" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/takeover" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/release" not in payload["paths"]


@pytest.mark.anyio
async def test_project_task_edges_are_persisted_and_idempotent(tmp_path: Path) -> None:
    async with make_auth_client(tmp_path) as client:
        project_response = await client.post(
            "/projects",
            json={"name": "Edge Project", "description": "for edges"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["project_id"]

        empty_response = await client.get(f"/projects/{project_id}/task-edges")
        assert empty_response.status_code == 200
        assert empty_response.json() == {"items": []}

        create_response = await client.post(
            f"/projects/{project_id}/task-edges",
            json={"source_task_id": "task-a", "target_task_id": "task-b"},
        )
        assert create_response.status_code == 201
        edge = create_response.json()
        assert edge["project_id"] == project_id
        assert edge["source_task_id"] == "task-a"
        assert edge["target_task_id"] == "task-b"

        duplicate_response = await client.post(
            f"/projects/{project_id}/task-edges",
            json={"source_task_id": "task-a", "target_task_id": "task-b"},
        )
        assert duplicate_response.status_code == 201
        assert duplicate_response.json()["edge_id"] == edge["edge_id"]

        list_response = await client.get(f"/projects/{project_id}/task-edges")
        assert list_response.status_code == 200
        assert list_response.json()["items"] == [edge]

        delete_response = await client.delete(f"/task-edges/{edge['edge_id']}")
        assert delete_response.status_code == 204
        assert (await client.get(f"/projects/{project_id}/task-edges")).json() == {"items": []}


@pytest.mark.anyio
async def test_project_task_edges_require_existing_project(tmp_path: Path) -> None:
    async with make_auth_client(tmp_path) as client:
        response = await client.get("/projects/missing/task-edges")
        assert response.status_code == 404

        create_response = await client.post(
            "/projects/missing/task-edges",
            json={"source_task_id": "task-a", "target_task_id": "task-b"},
        )
        assert create_response.status_code == 404


@pytest.mark.anyio
async def test_lifespan_records_startup_runtime_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    monkeypatch.setattr(
        "ainrf.api.app.check_runtime_readiness",
        lambda: type(
            "FakeReadiness",
            (),
            {
                "as_public_payload": lambda self: {
                    "ready": True,
                    "dependencies": {
                        "tmux": {"available": True, "path": "/usr/bin/tmux", "detail": None},
                        "uv": {"available": True, "path": "/usr/bin/uv", "detail": None},
                    },
                }
            },
        )(),
    )

    async with app.router.lifespan_context(app):
        assert app.state.runtime_readiness["ready"] is True


@pytest.mark.anyio
async def test_health_uses_startup_runtime_readiness_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.runtime_readiness = {
        "ready": False,
        "dependencies": {"tmux": {"available": False, "path": None, "detail": "Install tmux."}},
    }
    monkeypatch.setattr(
        "ainrf.api.routes.health.check_runtime_readiness",
        lambda: pytest.fail("health should reuse startup readiness snapshot"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["runtime_readiness"] == app.state.runtime_readiness


@pytest.mark.anyio
async def test_workspace_crud_routes_persist_changes(tmp_path: Path) -> None:
    workdir = str(tmp_path / "workspace" / "paper")
    async with make_auth_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            json={
                "label": "Paper Experiments",
                "description": "Runs for the paper figures",
                "default_workdir": workdir,
                "workspace_prompt": "Focus on reproducible experiments.",
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        workspace_id = created["workspace_id"]
        assert created["label"] == "Paper Experiments"
        assert created["description"] == "Runs for the paper figures"
        assert created["default_workdir"] == workdir
        assert created["workspace_prompt"] == "Focus on reproducible experiments."

        list_response = await client.get("/v1/workspaces")
        assert list_response.status_code == 200
        assert workspace_id in {item["workspace_id"] for item in list_response.json()["items"]}

        updated_workdir = str(tmp_path / "workspace" / "updated")
        update_response = await client.patch(
            f"/v1/workspaces/{workspace_id}",
            json={
                "label": "Updated Experiments",
                "description": None,
                "default_workdir": updated_workdir,
                "workspace_prompt": "Updated prompt.",
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["workspace_id"] == workspace_id
        assert updated["label"] == "Updated Experiments"
        assert updated["description"] is None
        assert updated["default_workdir"] == updated_workdir
        assert updated["workspace_prompt"] == "Updated prompt."
        assert updated["created_at"] == created["created_at"]
        assert updated["updated_at"] >= created["updated_at"]

        delete_response = await client.delete(f"/v1/workspaces/{workspace_id}")
        assert delete_response.status_code == 204

        read_deleted_response = await client.get(f"/v1/workspaces/{workspace_id}")
        assert read_deleted_response.status_code == 404


@pytest.mark.anyio
async def test_create_workspace_auto_creates_missing_directory(tmp_path: Path) -> None:
    target_dir = tmp_path / "auto-created" / "workspace"
    assert not target_dir.exists()

    async with make_auth_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            json={
                "label": "Auto Created",
                "description": None,
                "default_workdir": str(target_dir),
                "workspace_prompt": "Auto create test.",
            },
        )

    assert create_response.status_code == 200
    assert target_dir.exists()
    assert target_dir.is_dir()


@pytest.mark.anyio
async def test_create_workspace_rejects_unavailable_directory(tmp_path: Path) -> None:
    # 创建一个文件来阻塞目录创建（同名文件存在时 mkdir 会失败）
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("i am a file", encoding="utf-8")

    async with make_auth_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            json={
                "label": "Blocked",
                "description": None,
                "default_workdir": str(blocked_path),
                "workspace_prompt": "Blocked test.",
            },
        )

        assert create_response.status_code == 400
        detail = create_response.json()["detail"]
        assert "Failed to create workspace directory" in detail

        # 验证 workspace 未被写入 registry
        list_response = await client.get("/v1/workspaces")
        assert list_response.status_code == 200
        labels = {item["label"] for item in list_response.json()["items"]}
        assert "Blocked" not in labels


@pytest.mark.anyio
async def test_workspace_delete_rejects_seed_workspace(tmp_path: Path) -> None:
    async with make_auth_client(tmp_path) as client:
        response = await client.delete("/v1/workspaces/workspace-default")

    assert response.status_code == 409
    assert response.json()["detail"] == "Default workspace cannot be deleted"


@pytest.mark.anyio
async def test_get_resources_returns_list(tmp_path: Path) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            container_config=ContainerConfig(host="gpu-server-01", user="root"),
        )
    )
    jwt_headers = get_jwt_headers(app)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=jwt_headers,
    ) as client:
        response = await client.get("/resources")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)

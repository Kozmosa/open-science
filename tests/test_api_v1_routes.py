from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key


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
    assert {path for path in payload["paths"] if path.startswith("/v1/")} == {
        f"/v1{path}" for path in payload["paths"] if not path.startswith("/v1/")
    }
    assert "/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/v1/projects/{project_id}/environment-refs" in payload["paths"]
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
    assert "/code/session" in payload["paths"]
    assert "/v1/code/session" in payload["paths"]
    assert "/tasks" in payload["paths"]
    assert "/tasks/{task_id}" in payload["paths"]
    assert "/tasks/{task_id}/output" in payload["paths"]
    assert "/tasks/{task_id}/stream" in payload["paths"]
    assert "/v1/tasks" in payload["paths"]
    assert "/v1/tasks/{task_id}" in payload["paths"]
    assert "/v1/tasks/{task_id}/output" in payload["paths"]
    assert "/v1/tasks/{task_id}/stream" in payload["paths"]
    assert "/tasks/{task_id}/cancel" not in payload["paths"]
    assert "/tasks/{task_id}/terminal" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/open" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/takeover" not in payload["paths"]
    assert "/tasks/{task_id}/terminal/release" not in payload["paths"]
    assert "/v1/tasks/{task_id}/cancel" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/open" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/takeover" not in payload["paths"]
    assert "/v1/tasks/{task_id}/terminal/release" not in payload["paths"]


@pytest.mark.anyio
async def test_lifespan_attaches_environment_aware_code_server_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ainrf.api.app.check_runtime_readiness",
        lambda code_server_path=None: type(
            "FakeReadiness",
            (),
            {
                "as_public_payload": lambda self: {
                    "ready": True,
                    "dependencies": {
                        "tmux": {"available": True, "path": "/usr/bin/tmux", "detail": None},
                        "uv": {"available": True, "path": "/usr/bin/uv", "detail": None},
                        "code_server": {
                            "available": True,
                            "path": "/usr/bin/code-server",
                            "detail": None,
                        },
                    },
                }
            },
        )(),
    )
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )

    async with app.router.lifespan_context(app):
        manager = app.state.code_server_manager
        assert manager is app.state.code_server_supervisor
        assert manager.base_url is None


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
        lambda code_server_path=None: type(
            "FakeReadiness",
            (),
            {
                "as_public_payload": lambda self: {
                    "ready": True,
                    "dependencies": {
                        "tmux": {"available": True, "path": "/usr/bin/tmux", "detail": None},
                        "uv": {"available": True, "path": "/usr/bin/uv", "detail": None},
                        "code_server": {
                            "available": True,
                            "path": "/usr/bin/code-server",
                            "detail": None,
                        },
                    },
                }
            },
        )(),
    )

    async with app.router.lifespan_context(app):
        assert app.state.runtime_readiness["ready"] is True
        assert app.state.runtime_readiness["dependencies"]["code_server"] == {
            "available": True,
            "path": "/usr/bin/code-server",
            "detail": None,
        }


@pytest.mark.anyio
async def test_lifespan_records_readiness_even_when_code_server_missing(
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
        lambda code_server_path=None: type(
            "FakeReadiness",
            (),
            {
                "as_public_payload": lambda self: {
                    "ready": False,
                    "dependencies": {
                        "tmux": {"available": True, "path": "/usr/bin/tmux", "detail": None},
                        "uv": {"available": True, "path": "/usr/bin/uv", "detail": None},
                        "code_server": {
                            "available": False,
                            "path": None,
                            "detail": "Install code-server.",
                        },
                    },
                }
            },
        )(),
    )

    async with app.router.lifespan_context(app):
        assert app.state.runtime_readiness["ready"] is False
        assert app.state.runtime_readiness["dependencies"]["code_server"] == {
            "available": False,
            "path": None,
            "detail": "Install code-server.",
        }


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
        lambda code_server_path=None: pytest.fail("health should reuse startup readiness snapshot"),
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
    async with make_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            headers={"X-API-Key": "secret-key"},
            json={
                "label": "Paper Experiments",
                "description": "Runs for the paper figures",
                "default_workdir": "/workspace/paper",
                "workspace_prompt": "Focus on reproducible experiments.",
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        workspace_id = created["workspace_id"]
        assert created["label"] == "Paper Experiments"
        assert created["description"] == "Runs for the paper figures"
        assert created["default_workdir"] == "/workspace/paper"
        assert created["workspace_prompt"] == "Focus on reproducible experiments."

        list_response = await client.get(
            "/v1/workspaces",
            headers={"X-API-Key": "secret-key"},
        )
        assert list_response.status_code == 200
        assert workspace_id in {item["workspace_id"] for item in list_response.json()["items"]}

        update_response = await client.patch(
            f"/v1/workspaces/{workspace_id}",
            headers={"X-API-Key": "secret-key"},
            json={
                "label": "Updated Experiments",
                "description": None,
                "default_workdir": "/workspace/updated",
                "workspace_prompt": "Updated prompt.",
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["workspace_id"] == workspace_id
        assert updated["label"] == "Updated Experiments"
        assert updated["description"] is None
        assert updated["default_workdir"] == "/workspace/updated"
        assert updated["workspace_prompt"] == "Updated prompt."
        assert updated["created_at"] == created["created_at"]
        assert updated["updated_at"] >= created["updated_at"]

        delete_response = await client.delete(
            f"/v1/workspaces/{workspace_id}",
            headers={"X-API-Key": "secret-key"},
        )
        assert delete_response.status_code == 204

        read_deleted_response = await client.get(
            f"/v1/workspaces/{workspace_id}",
            headers={"X-API-Key": "secret-key"},
        )
        assert read_deleted_response.status_code == 404


@pytest.mark.anyio
async def test_workspace_delete_rejects_seed_workspace(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.delete(
            "/v1/workspaces/workspace-default",
            headers={"X-API-Key": "secret-key"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Default workspace cannot be deleted"

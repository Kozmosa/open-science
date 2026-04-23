from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.anyio
async def test_environment_list_starts_empty(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with make_client(app) as client:
        response = await client.get("/environments", headers={"X-API-Key": "secret-key"})
        v1_response = await client.get("/v1/environments", headers={"X-API-Key": "secret-key"})

    assert response.status_code == 200
    assert [item["alias"] for item in response.json()["items"]] == ["localhost"]
    assert response.json()["items"][0]["is_seed"] is True
    assert v1_response.status_code == 200
    assert [item["alias"] for item in v1_response.json()["items"]] == ["localhost"]


@pytest.mark.anyio
async def test_environment_create_returns_saved_fields_and_null_latest_detection(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "description": "Primary CUDA environment",
        "tags": ["gpu", "research"],
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
        "auth_kind": "ssh_key",
        "identity_file": "/keys/gpu-lab",
        "proxy_jump": "bastion",
        "proxy_command": "ssh -W %h:%p bastion",
        "ssh_options": {"StrictHostKeyChecking": "no"},
        "default_workdir": "/workspace/project",
        "preferred_python": "python3.13",
        "preferred_env_manager": "uv",
        "preferred_runtime_notes": "Use CUDA 12 image",
        "task_harness_profile": "Use the configured GPU environment.",
    }

    async with make_client(app) as client:
        response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=payload,
        )

    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["id"], str)
    assert data["id"].startswith("env-")
    assert data["alias"] == payload["alias"]
    assert data["display_name"] == payload["display_name"]
    assert data["description"] == payload["description"]
    assert data["tags"] == payload["tags"]
    assert data["host"] == payload["host"]
    assert data["port"] == payload["port"]
    assert data["user"] == payload["user"]
    assert data["auth_kind"] == payload["auth_kind"]
    assert data["identity_file"] == payload["identity_file"]
    assert data["proxy_jump"] == payload["proxy_jump"]
    assert data["proxy_command"] == payload["proxy_command"]
    assert data["ssh_options"] == payload["ssh_options"]
    assert data["default_workdir"] == payload["default_workdir"]
    assert data["preferred_python"] == payload["preferred_python"]
    assert data["preferred_env_manager"] == payload["preferred_env_manager"]
    assert data["preferred_runtime_notes"] == payload["preferred_runtime_notes"]
    assert data["task_harness_profile"] == payload["task_harness_profile"]
    assert data["latest_detection"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


@pytest.mark.anyio
async def test_environment_lifecycle_supports_update_detect_and_delete(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    create_payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=create_payload,
        )
        environment_id = create_response.json()["id"]

        detail_response = await client.get(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )
        update_response = await client.patch(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
            json={
                "display_name": "GPU Lab Updated",
                "default_workdir": "/workspace/project-a",
                "task_harness_profile": "Updated task harness profile.",
            },
        )
        detect_response = await client.post(
            f"/environments/{environment_id}/detect",
            headers={"X-API-Key": "secret-key"},
            json={},
        )
        listed_response = await client.get(
            "/v1/environments",
            headers={"X-API-Key": "secret-key"},
        )
        delete_response = await client.delete(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )
        missing_response = await client.get(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert detail_response.status_code == 200
    assert detail_response.json()["alias"] == "gpu-lab"

    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "GPU Lab Updated"
    assert update_response.json()["default_workdir"] == "/workspace/project-a"
    assert update_response.json()["task_harness_profile"] == "Updated task harness profile."

    assert detect_response.status_code == 200
    assert detect_response.json()["latest_detection"]["environment_id"] == environment_id
    assert detect_response.json()["latest_detection"]["status"] == "success"
    assert (
        detect_response.json()["latest_detection"]["summary"]
        == "Manual detection completed for gpu-lab."
    )

    assert listed_response.status_code == 200
    listed_items = listed_response.json()["items"]
    assert any(
        item["latest_detection"] is not None
        and item["latest_detection"]["environment_id"] == environment_id
        for item in listed_items
    )

    assert delete_response.status_code == 204
    assert missing_response.status_code == 404


@pytest.mark.anyio
async def test_environment_alias_conflicts_and_reference_protection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=payload,
        )
        environment_id = create_response.json()["id"]
        conflict_response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=payload,
        )

        app.state.environment_service.upsert_project_reference(
            project_id="project-a",
            environment_id=environment_id,
            is_default=True,
        )
        delete_response = await client.delete(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert conflict_response.status_code == 409
    assert "alias" in conflict_response.json()["detail"].lower()
    assert delete_response.status_code == 409
    assert "referenced" in delete_response.json()["detail"].lower()


@pytest.mark.anyio
async def test_localhost_environment_is_present_and_cannot_be_deleted(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with make_client(app) as client:
        list_response = await client.get("/environments", headers={"X-API-Key": "secret-key"})
        localhost_id = list_response.json()["items"][0]["id"]
        delete_response = await client.delete(
            f"/environments/{localhost_id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["alias"] == "localhost"
    assert delete_response.status_code == 409
    assert "cannot be deleted" in delete_response.json()["detail"].lower()


@pytest.mark.anyio
async def test_project_environment_reference_crud_and_delete_protection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_environment_response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=payload,
        )
        environment_id = create_environment_response.json()["id"]

        create_reference_response = await client.post(
            "/projects/default/environment-refs",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment_id,
                "is_default": True,
                "override_workdir": "/workspace/project-a",
            },
        )
        update_reference_response = await client.patch(
            f"/projects/default/environment-refs/{environment_id}",
            headers={"X-API-Key": "secret-key"},
            json={
                "override_env_name": "research-env",
                "override_env_manager": "conda",
                "override_runtime_notes": "Prefer the project runtime image",
            },
        )
        list_reference_response = await client.get(
            "/projects/default/environment-refs",
            headers={"X-API-Key": "secret-key"},
        )
        delete_environment_response = await client.delete(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )
        delete_reference_response = await client.delete(
            f"/projects/default/environment-refs/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )
        delete_environment_after_unbind = await client.delete(
            f"/environments/{environment_id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert create_reference_response.status_code == 201
    assert create_reference_response.json()["environment_id"] == environment_id
    assert create_reference_response.json()["is_default"] is True
    assert create_reference_response.json()["override_workdir"] == "/workspace/project-a"

    assert update_reference_response.status_code == 200
    assert update_reference_response.json()["override_env_name"] == "research-env"
    assert update_reference_response.json()["override_env_manager"] == "conda"
    assert (
        update_reference_response.json()["override_runtime_notes"]
        == "Prefer the project runtime image"
    )

    assert list_reference_response.status_code == 200
    assert list_reference_response.json()["items"] == [update_reference_response.json()]

    assert delete_environment_response.status_code == 409
    assert "referenced" in delete_environment_response.json()["detail"].lower()
    assert delete_reference_response.status_code == 204
    assert delete_environment_after_unbind.status_code == 204


@pytest.mark.anyio
async def test_project_environment_reference_routes_are_mirrored_under_v1(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    payload = {
        "alias": "cpu-lab",
        "display_name": "CPU Lab",
        "host": "cpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_environment_response = await client.post(
            "/environments",
            headers={"X-API-Key": "secret-key"},
            json=payload,
        )
        environment_id = create_environment_response.json()["id"]

        create_reference_response = await client.post(
            "/v1/projects/default/environment-refs",
            headers={"X-API-Key": "secret-key"},
            json={"environment_id": environment_id},
        )
        list_reference_response = await client.get(
            "/v1/projects/default/environment-refs",
            headers={"X-API-Key": "secret-key"},
        )

    assert create_reference_response.status_code == 201
    assert create_reference_response.json()["environment_id"] == environment_id
    assert list_reference_response.status_code == 200
    assert list_reference_response.json()["items"] == [create_reference_response.json()]

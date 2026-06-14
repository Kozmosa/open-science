from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.skills import SkillsDiscoveryService
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]

def _make_app(tmp_path: Path, scan_roots: list[Path] | None = None) -> FastAPI:
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config)
    if scan_roots is not None:
        app.state.skills_discovery_service = SkillsDiscoveryService(scan_roots=scan_roots)
    return app


def make_client(tmp_path: Path, scan_roots: list[Path] | None = None) -> httpx.AsyncClient:
    app = _make_app(tmp_path, scan_roots=scan_roots)
    headers = get_jwt_headers(app)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


@pytest.mark.anyio
async def test_list_registries(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/skill-registries")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    aris = next((r for r in data["items"] if r["registry_id"] == "aris"), None)
    assert aris is not None
    assert aris["display_name"] == "ARIS"
    assert aris["git_url"] == "https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git"


@pytest.mark.anyio
async def test_get_status_not_installed(tmp_path: Path) -> None:
    # Use an empty scan root so no skills are found
    async with make_client(tmp_path, scan_roots=[tmp_path / "empty"]) as client:
        response = await client.get("/skill-registries/aris/status")

    assert response.status_code == 200
    data = response.json()
    assert data["registry_id"] == "aris"
    assert data["installed"] is False
    assert data["has_update"] is False


@pytest.mark.anyio
async def test_get_nonexistent_registry_returns_404(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/skill-registries/nonexistent/status")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_install_already_installed_returns_400(tmp_path: Path) -> None:
    # Create the registry marker file to simulate installed state
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / ".ainrf-registry").write_text("aris", encoding="utf-8")

    async with make_client(tmp_path, scan_roots=[tmp_path]) as client:
        response = await client.post("/skill-registries/aris/install")

    assert response.status_code == 400
    assert "already installed" in response.json()["detail"]


@pytest.mark.anyio
async def test_update_not_installed_returns_400(tmp_path: Path) -> None:
    # Use an empty scan root so no skills are found
    async with make_client(tmp_path, scan_roots=[tmp_path / "empty"]) as client:
        response = await client.post("/skill-registries/aris/update", json={"force": False})

    assert response.status_code == 400
    assert "not installed" in response.json()["detail"]


@pytest.mark.anyio
async def test_create_update_delete_custom_registry(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        create_resp = await client.post(
            "/skill-registries",
            json={
                "registry_id": "custom-repo",
                "display_name": "Custom Registry",
                "git_url": "https://github.com/example/custom-skills.git",
                "git_ref": "main",
                "source_skills_path": "skills",
                "core_skill_ids": ["core-one"],
                "install_mode": "copy",
                "enabled": True,
            },
        )
        assert create_resp.status_code == 200
        data = create_resp.json()
        assert data["registry_id"] == "custom-repo"
        assert data["display_name"] == "Custom Registry"
        assert data["git_url"] == "https://github.com/example/custom-skills.git"

        list_resp = await client.get("/skill-registries")
        assert list_resp.status_code == 200
        ids = [r["registry_id"] for r in list_resp.json()["items"]]
        assert "custom-repo" in ids

        update_resp = await client.put(
            "/skill-registries/custom-repo",
            json={
                "display_name": "Updated Custom Registry",
                "git_ref": "develop",
                "enabled": False,
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["display_name"] == "Updated Custom Registry"

        status_resp = await client.get("/skill-registries/custom-repo/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["registry_id"] == "custom-repo"

        delete_resp = await client.delete("/skill-registries/custom-repo")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"

        list_resp = await client.get("/skill-registries")
        ids = [r["registry_id"] for r in list_resp.json()["items"]]
        assert "custom-repo" not in ids


@pytest.mark.anyio
async def test_create_duplicate_registry_returns_409(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        payload = {
            "registry_id": "dup-repo",
            "display_name": "Duplicate Registry",
            "git_url": "https://github.com/example/dup-skills.git",
        }
        first = await client.post("/skill-registries", json=payload)
        assert first.status_code == 200

        second = await client.post("/skill-registries", json=payload)
        assert second.status_code == 409


@pytest.mark.anyio
async def test_delete_builtin_registry_returns_403(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.delete("/skill-registries/aris")

    assert response.status_code == 403
    assert "default" in response.json()["detail"].lower() or "built-in" in response.json()["detail"].lower()

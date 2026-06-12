from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
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


@pytest.mark.anyio
async def test_health_is_public(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_non_api_route_is_not_auth_gated(tmp_path: Path) -> None:
    """Non-API paths (e.g. SPA routes) skip auth — frontend handles its own auth flow."""
    async with make_client(tmp_path) as client:
        response = await client.get("/some-spa-route")

    # Not 401 — SPA routes are exempt from backend auth
    assert response.status_code in (200, 404)


@pytest.mark.anyio
async def test_terminal_session_requires_api_key(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/terminal/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.anyio
async def test_unknown_route_returns_not_found_with_valid_jwt(tmp_path: Path) -> None:
    """Unknown routes should bypass the JWT middleware and reach the 404 handler."""
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    jwt_headers = get_jwt_headers(app)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/retired", headers=jwt_headers)

    assert response.status_code == 404


def test_api_config_reads_onboard_minimal_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AINRF_API_KEY_HASHES", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"api_key_hashes": [hash_api_key("bootstrap-secret")]}),
        encoding="utf-8",
    )

    config = ApiConfig.from_env(tmp_path)

    assert config.verify_api_key("bootstrap-secret") is True
    assert config.state_root == tmp_path


def test_api_config_loads_default_container_profile_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AINRF_API_KEY_HASHES", raising=False)
    monkeypatch.delenv("AINRF_CONTAINER_HOST", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "api_key_hashes": [hash_api_key("secret-key")],
                "container_profiles": {
                    "gpu-main": {
                        "host": "gpu-server-01",
                        "port": 2200,
                        "user": "researcher",
                        "ssh_key_path": "/tmp/id_ed25519",
                        "ssh_password": "secret-pass",
                        "project_dir": "/workspace/project-a",
                        "connect_timeout": 20,
                        "command_timeout": 300,
                    }
                },
                "default_container_profile": "gpu-main",
            }
        ),
        encoding="utf-8",
    )

    config = ApiConfig.from_env(tmp_path)

    assert config.container_config is not None
    assert config.container_config.host == "gpu-server-01"
    assert config.container_config.user == "researcher"
    assert config.container_config.port == 2200
    assert config.container_config.ssh_password == "secret-pass"


def test_api_config_seeds_localhost_container_profile_when_config_is_minimal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AINRF_API_KEY_HASHES", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"api_key_hashes": [hash_api_key("secret-key")]}),
        encoding="utf-8",
    )

    config = ApiConfig.from_env(tmp_path)

    assert config.container_config is not None
    assert config.container_config.host == "127.0.0.1"
    assert config.container_config.port == 2222
    assert config.container_config.project_dir == "/workspace/projects"
    assert config.container_config.ssh_key_path == "/opt/ainrf/.ssh/ainrf_local"


def test_api_config_uses_login_shell_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PwRecord:
        pw_shell = "/bin/zsh"

    monkeypatch.setattr("ainrf.api.config.pwd.getpwuid", lambda uid: PwRecord())
    monkeypatch.setenv("SHELL", "/bin/fish")

    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )

    assert config.terminal_command == ("/bin/zsh",)


@pytest.mark.anyio
async def test_registration_creates_per_user_default_project(tmp_path: Path) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            public_registration_enabled=True,
        )
    )
    app.state.auth_service.initialize()
    # ensure_tenant_workspace creates dirs under /home/ainrf_tenants (container-only);
    # it is not under test here, so stub it out to reach the project-provisioning hook.
    app.state.workspace_service.ensure_tenant_workspace = lambda **_kwargs: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/auth/register",
            json={"username": "alice", "display_name": "Alice", "password": "secret123"},
        )
        assert response.status_code == 201, response.text
        default_project = app.state.project_service.get_project("alice_default")
        assert default_project.name == "alice's Project"
        assert default_project.owner_user_id is not None

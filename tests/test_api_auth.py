from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from tests._testutil import get_jwt_headers


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


def make_auth_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    headers = get_jwt_headers(app)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


@pytest.mark.anyio
async def test_health_is_public(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_missing_unknown_route_stays_unauthorized_without_api_key(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/retired")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.anyio
async def test_terminal_session_requires_api_key(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/terminal/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.anyio
async def test_unknown_route_returns_not_found_with_valid_jwt_token(tmp_path: Path) -> None:
    async with make_auth_client(tmp_path) as client:
        response = await client.get("/retired")

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
    assert config.container_config.port == 22
    assert config.container_config.project_dir == "/workspace/projects"


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

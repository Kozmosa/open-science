from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.testutil import create_v2_test_app as create_app
from ainrf.api.config import ApiConfig, hash_api_key
from tests.testutil import CURRENT_ARTIFACT_SHA, get_jwt_headers, prepare_current_test_state

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
        response = await client.get("/api/health")

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
        response = await client.get("/api/terminal/session")

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


def test_api_config_reads_runtime_reconciliation_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AINRF_API_KEY_HASHES", hash_api_key("bootstrap-secret"))
    monkeypatch.setenv("AINRF_RUNTIME_RECONCILIATION_ENABLED", "false")

    config = ApiConfig.from_env(tmp_path)

    assert config.runtime_reconciliation_enabled is False


@pytest.mark.anyio
async def test_interactive_auth_can_be_disabled_without_disabling_api_key_auth(
    tmp_path: Path,
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("clone-review-key")}),
            state_root=tmp_path,
            interactive_auth_enabled=False,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "not-used"},
        )
        refresh_response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "not-used"},
        )
        health_response = await client.get("/api/health", headers={"X-API-Key": "clone-review-key"})

    assert login_response.status_code == 403
    assert refresh_response.status_code == 403
    assert health_response.status_code == 200


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


def test_api_config_prefers_ainrf_backend_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENSCIENCE_STATE_ROOT", str(tmp_path / "open"))
    monkeypatch.setenv("AINRF_STATE_ROOT", str(tmp_path / "ainrf"))
    monkeypatch.setenv("OPENSCIENCE_API_KEY_HASHES", "a" * 64)
    monkeypatch.setenv("AINRF_API_KEY_HASHES", "b" * 64)

    config = ApiConfig.from_env()

    assert config.state_root == tmp_path / "ainrf"
    assert config.api_key_hashes == frozenset({"b" * 64})


def test_api_config_accepts_openscience_compatibility_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AINRF_STATE_ROOT", raising=False)
    monkeypatch.delenv("AINRF_API_KEY_HASHES", raising=False)
    monkeypatch.setenv("OPENSCIENCE_STATE_ROOT", str(tmp_path / "compatibility"))
    monkeypatch.setenv("OPENSCIENCE_API_KEY_HASHES", "a" * 64)

    config = ApiConfig.from_env()

    assert config.state_root == tmp_path / "compatibility"
    assert config.api_key_hashes == frozenset({"a" * 64})


def test_api_config_builds_namespaced_auth_cookie_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AINRF_API_KEY_HASHES", "a" * 64)
    monkeypatch.setenv("AINRF_AUTH_COOKIE_NAMESPACE", "staging")

    config = ApiConfig.from_env(tmp_path)

    assert config.access_cookie_names == (
        "openscience_staging_access_token",
        "ainrf_staging_access_token",
    )


def test_api_config_rejects_invalid_auth_cookie_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AINRF_API_KEY_HASHES", "a" * 64)
    monkeypatch.setenv("AINRF_AUTH_COOKIE_NAMESPACE", "Staging Unsafe")

    with pytest.raises(ValueError, match="cookie namespace"):
        ApiConfig.from_env(tmp_path)


def test_api_config_uses_login_shell_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PwRecord:
        pw_shell = "/bin/zsh"

    monkeypatch.setattr("ainrf.runtime.product_config.pwd.getpwuid", lambda uid: PwRecord())
    monkeypatch.setenv("SHELL", "/bin/fish")

    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )

    assert config.terminal_command == ("/bin/zsh",)


@pytest.mark.anyio
async def test_v2_registration_uses_durable_default_project_provisioning(
    tmp_path: Path,
) -> None:
    prepare_current_test_state(tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            domain_artifact_sha=CURRENT_ARTIFACT_SHA,
            public_registration_enabled=True,
        )
    )
    app.state.auth_service.initialize()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/auth/register",
            json={"username": "v2alice", "display_name": "V2 Alice", "password": "secret123"},
        )

    assert response.status_code == 201, response.text
    users = [user for user in app.state.auth_service.list_users() if user.username == "v2alice"]
    assert len(users) == 1
    user = users[0]
    projects = app.state.project_module.list_projects({"id": user.id, "role": "member"})
    defaults = [project for project in projects if bool(project["is_default"])]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "v2alice's Project"
    assert app.state.auth_service.pending_domain_default_project_provisioning() == []
    assert not hasattr(app.state, "project_service")


@pytest.mark.anyio
async def test_registration_transport_rejects_username_outside_tenant_policy(
    tmp_path: Path,
) -> None:
    prepare_current_test_state(tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            domain_artifact_sha=CURRENT_ARTIFACT_SHA,
            public_registration_enabled=True,
        )
    )
    app.state.auth_service.initialize()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for username in ("a", "_alice", "Alice", "alice.test", "a" * 32):
            response = await client.post(
                "/api/auth/register",
                json={
                    "username": username,
                    "display_name": "Rejected User",
                    "password": "secret123",
                },
            )
            assert response.status_code == 422, (username, response.text)

    assert app.state.auth_service.list_users() == []

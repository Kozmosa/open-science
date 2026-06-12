from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.execution import ContainerConfig, ContainerHealth
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


async def _noop_async(self: object, **kwargs: object) -> None:
    """No-op for mocking SSHExecutor connect/close."""


@pytest.mark.anyio
async def test_health_reports_container_probe_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ping(self: object, **kwargs: object) -> ContainerHealth:
        return ContainerHealth(
            ssh_ok=True,
            claude_ok=True,
            project_dir_writable=True,
            warnings=[],
        )

    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.ping", fake_ping)
    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.connect", _noop_async)
    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.close", _noop_async)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            container_config=ContainerConfig(host="gpu-server-01", user="root"),
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["container_health"]["ssh_ok"] is True
    assert "anthropic_api_key_ok" not in response.json()["container_health"]


@pytest.mark.anyio
async def test_health_reports_degraded_container_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ping(self: object, **kwargs: object) -> ContainerHealth:
        return ContainerHealth(
            ssh_ok=False,
            claude_ok=False,
            project_dir_writable=False,
            warnings=["ssh_unreachable"],
        )

    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.ping", fake_ping)
    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.connect", _noop_async)
    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.close", _noop_async)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            container_config=ContainerConfig(host="gpu-server-01", user="root"),
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


@pytest.mark.anyio
async def test_settings_codex_defaults_reads_local_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "fake-home"
    codex_home = fake_home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    (codex_home / "auth.json").write_text('{"token":"abc"}\n', encoding="utf-8")
    monkeypatch.setattr("ainrf.api.routes.settings.Path.home", lambda: fake_home)

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
        response = await client.get(
            "/settings/codex-defaults",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "codex_config_toml": 'model = "gpt-5-codex"\n',
        "codex_auth_json": '{"token":"abc"}\n',
    }


@pytest.mark.anyio
async def test_settings_deployment_version_reads_backend_build_info(
    tmp_path: Path,
) -> None:
    # The backend reports its OWN build provenance (baked at backend-image
    # build time), not the frontend's build-info, which is built separately.
    (tmp_path / "backend-build-info.json").write_text(
        '{"short_commit":"abc123","committed_at":"20260612-2017"}',
        encoding="utf-8",
    )
    # A frontend build-info artifact must NOT leak into the backend version.
    frontend_public = tmp_path / "frontend" / "public"
    frontend_public.mkdir(parents=True, exist_ok=True)
    (frontend_public / "build-info.json").write_text(
        '{"short_commit":"deadbeef","committed_at":"19990101-0000"}',
        encoding="utf-8",
    )

    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            startup_cwd=tmp_path,
        )
    )
    jwt_headers = get_jwt_headers(app)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/settings/deployment-version",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "short_commit": "abc123",
        "committed_at": "20260612-2017",
    }

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.domain_control import DomainMaintenanceService
from ainrf.execution import ContainerConfig, ContainerHealth
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


async def _noop_async(self: object, **kwargs: object) -> None:
    """No-op for mocking SSHExecutor connect/close."""


def _state_tree_digest(root: Path) -> str:
    """Return a content and metadata digest without mutating the state tree."""

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix()
        stat = path.lstat()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mode).encode("ascii"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


@pytest.mark.anyio
async def test_health_does_not_mutate_a_maintenance_startup_state_tree(tmp_path: Path) -> None:
    """A staged-restore API may be probed without recreating health_check state."""

    maintenance = DomainMaintenanceService(tmp_path)
    maintenance.enter(actor_id="operator", reason="staged restore")
    try:
        before = _state_tree_digest(tmp_path)
        app = create_app(
            ApiConfig(
                api_key_hashes=frozenset({hash_api_key("secret-key")}),
                state_root=tmp_path,
            )
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert not (tmp_path / "health_check").exists()
        assert _state_tree_digest(tmp_path) == before
    finally:
        maintenance.exit(actor_id="operator")


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
async def test_health_skips_remote_container_probe_when_runtime_reconciliation_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unexpected_ping(self: object, **kwargs: object) -> ContainerHealth:
        _ = self, kwargs
        pytest.fail("clone health must not probe a copied remote runtime")

    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.ping", unexpected_ping)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            container_config=ContainerConfig(host="production-runtime", user="root"),
            runtime_reconciliation_enabled=False,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["container_health"] is None
    assert response.json()["detail"] == "Remote runtime probes disabled by configuration"


@pytest.mark.anyio
async def test_settings_codex_defaults_never_reads_host_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    jwt_headers = get_jwt_headers(app)

    def fail_home() -> Path:
        raise AssertionError("host HOME must not be read")

    monkeypatch.setattr("ainrf.api.routes.settings.Path.home", fail_home)

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
        "codex_config_toml": None,
        "codex_auth_json": None,
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

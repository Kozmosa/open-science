from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.execution import ContainerConfig, ContainerHealth


@pytest.mark.anyio
async def test_health_reports_container_probe_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ping(self: object) -> ContainerHealth:
        return ContainerHealth(
            ssh_ok=True,
            claude_ok=True,
            project_dir_writable=True,
            warnings=[],
        )

    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.ping", fake_ping)
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
    async def fake_ping(self: object) -> ContainerHealth:
        return ContainerHealth(
            ssh_ok=False,
            claude_ok=False,
            project_dir_writable=False,
            warnings=["ssh_unreachable"],
        )

    monkeypatch.setattr("ainrf.api.routes.health.SSHExecutor.ping", fake_ping)
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

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"

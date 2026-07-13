"""Read-only API contract for a process restarted during domain maintenance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.api.middleware.domain_maintenance import (
    build_maintenance_startup_read_only_middleware,
)
from ainrf.auth.jwt_utils import create_access_token
from ainrf.domain_control import DomainMaintenanceService

pytestmark = [pytest.mark.api]


def _tree_digest(root: Path) -> str:
    """Return a deterministic content/metadata digest without writing state."""

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


def _config(state_root: Path, *, metrics_enabled: bool = False) -> ApiConfig:
    return ApiConfig(
        api_key_hashes=frozenset({hash_api_key("maintenance-startup-key")}),
        state_root=state_root,
        metrics_enabled=metrics_enabled,
    )


@pytest.mark.anyio
async def test_maintenance_startup_exposes_only_evidence_without_initializing_services(
    tmp_path: Path,
) -> None:
    """A restarted API must fail closed before auth or a missing service runs."""

    maintenance = DomainMaintenanceService(tmp_path)
    maintenance.enter(actor_id="operator", reason="staged restore")
    try:
        # Test JWT creation writes its isolated signing-secret fixture beneath
        # ``tmp_path``.  Create it before taking the source-state snapshot so
        # the assertion below measures the API process, not test setup.
        bearer = create_access_token("maintenance-user", "maintenance-user", "member")
        before = _tree_digest(tmp_path)
        app = create_app(_config(tmp_path))
        assert app.state.maintenance_startup_read_only is True

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/health")
            capabilities = await client.get(
                "/domain/capabilities",
                headers={"Authorization": f"Bearer {bearer}"},
            )
            blocked_reads = [
                await client.get("/tasks?api_key=maintenance-startup-key"),
                await client.get("/v1/sessions?api_key=maintenance-startup-key"),
                await client.get("/token-usage?api_key=maintenance-startup-key"),
                await client.get(
                    "/projects",
                    headers={"Authorization": f"Bearer {bearer}"},
                ),
            ]
            blocked_write = await client.post(
                "/auth/login",
                json={"username": "maintenance-user", "password": "not-used"},
            )

        assert health.status_code == 200
        assert capabilities.status_code == 200
        assert capabilities.json()["domain_contract_version"] == 1
        for response in [*blocked_reads, blocked_write]:
            assert response.status_code == 503
            assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"
        # The gate runs before JWT lookup, which would otherwise open and
        # initialize auth.sqlite3 through the regular connection factory.
        assert not (tmp_path / "runtime" / "auth.sqlite3").exists()
        assert _tree_digest(tmp_path) == before
    finally:
        maintenance.exit(actor_id="operator")


@pytest.mark.anyio
async def test_maintenance_startup_allows_the_static_spa_fallback_to_handle_its_route() -> None:
    """The narrow API fence must not intercept a frontend deep link."""

    app = FastAPI()
    app.state.maintenance_startup_read_only = True
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/console/maintenance",
            "raw_path": b"/console/maintenance",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 8000),
            "server": ("testserver", 80),
            "app": app,
        }
    )
    called = False

    async def static_fallback(_request: Request) -> PlainTextResponse:
        nonlocal called
        called = True
        return PlainTextResponse("frontend fallback")

    response = await build_maintenance_startup_read_only_middleware(metrics_path="/metrics")(
        request, static_fallback
    )

    assert called is True
    assert response.status_code == 200
    assert response.body == b"frontend fallback"


@pytest.mark.anyio
async def test_maintenance_startup_gate_does_not_change_an_initialized_app_read_route() -> None:
    """The gate is only for a process assembled during an active epoch."""

    app = FastAPI()
    app.state.maintenance_startup_read_only = False
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/tasks",
            "raw_path": b"/tasks",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 8000),
            "server": ("testserver", 80),
            "app": app,
        }
    )
    called = False

    async def initialized_read(_request: Request) -> PlainTextResponse:
        nonlocal called
        called = True
        return PlainTextResponse("existing read projection")

    response = await build_maintenance_startup_read_only_middleware(metrics_path="/metrics")(
        request, initialized_read
    )

    assert called is True
    assert response.status_code == 200
    assert response.body == b"existing read projection"

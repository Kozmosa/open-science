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
async def test_openapi_registers_projects_terminal_and_code_session_routes(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert "/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/v1/projects/{project_id}/environment-refs" in payload["paths"]
    assert "/terminal/session" in payload["paths"]
    assert "/terminal/session/reset" in payload["paths"]
    assert "/v1/terminal/session" in payload["paths"]
    assert "/v1/terminal/session/reset" in payload["paths"]
    assert "/code/session" in payload["paths"]
    assert "/v1/code/session" in payload["paths"]
    assert "/tasks" not in payload["paths"]
    assert "/v1/tasks" not in payload["paths"]


@pytest.mark.anyio
async def test_lifespan_attaches_environment_aware_code_server_manager(tmp_path: Path) -> None:
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

    stopped_state = await app.state.code_server_manager.stop()
    assert stopped_state.status.value == "unavailable"

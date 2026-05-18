from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from tests._testutil import get_jwt_headers
from ainrf.code_server import (
    CodeServerLifecycleStatus,
    CodeServerState,
    EnvironmentCodeServerManager,
)
from ainrf.environments import EnvironmentAuthKind


class ReadyManager:
    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:18080"

    async def status(self, environment_id: str | None = None) -> CodeServerState:
        _ = environment_id
        return CodeServerState(
            status=CodeServerLifecycleStatus.READY,
            environment_id="env-1",
            environment_alias="gpu-lab",
            workspace_dir="/workspace/project",
        )

    async def ensure(self, environment_id: str) -> CodeServerState:
        _ = environment_id
        return await self.status(environment_id)

    async def stop(self) -> CodeServerState:
        return CodeServerState(
            status=CodeServerLifecycleStatus.UNAVAILABLE,
            environment_id="env-1",
            environment_alias="gpu-lab",
            workspace_dir="/workspace/project",
            detail="code-server stopped",
        )


@pytest.mark.anyio
async def test_code_status_reports_unavailable_without_manager(tmp_path: Path) -> None:
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
        response = await client.get("/code/status", headers=get_jwt_headers(app))

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "environment_id": None,
        "environment_alias": None,
        "workspace_dir": None,
        "detail": "code-server supervisor not initialized",
        "managed": True,
    }


@pytest.mark.anyio
async def test_code_session_returns_conflict_for_password_environment(tmp_path: Path) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    environment = app.state.environment_service.create_environment(
        alias="password-lab",
        display_name="Password Lab",
        host="gpu.example.com",
        auth_kind=EnvironmentAuthKind.PASSWORD,
    )
    manager = EnvironmentCodeServerManager(
        state_root=tmp_path,
        environment_service=app.state.environment_service,
    )
    app.state.code_server_manager = manager
    app.state.code_server_supervisor = manager

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/code/session",
            headers=get_jwt_headers(app),
            json={"environment_id": environment.id},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Workspace does not support password-auth environments"}


@pytest.mark.anyio
async def test_code_proxy_forwards_ready_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.code_server_manager = ReadyManager()
    app.state.code_server_supervisor = app.state.code_server_manager

    original_request = httpx.AsyncClient.request

    async def fake_request(
        self: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if str(url).startswith("/") or str(url).startswith("http://testserver"):
            return await original_request(self, method, url, **kwargs)

        assert method == "GET"
        assert url == "http://127.0.0.1:18080/"
        headers = cast(dict[str, str], kwargs["headers"])
        assert headers["accept"] == "text/html"
        assert kwargs["follow_redirects"] is False
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8", "x-upstream": "code-server"},
            text="<html>ok</html>",
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/code/",
            headers={**get_jwt_headers(app), "Accept": "text/html"},
        )

    assert response.status_code == 200
    assert response.text == "<html>ok</html>"
    assert response.headers["x-upstream"] == "code-server"


@pytest.mark.anyio
async def test_code_proxy_forwards_query_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.code_server_manager = ReadyManager()
    app.state.code_server_supervisor = app.state.code_server_manager

    original_request = httpx.AsyncClient.request

    async def fake_request(
        self: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if str(url).startswith("/") or str(url).startswith("http://testserver"):
            return await original_request(self, method, url, **kwargs)
        assert method == "GET"
        assert (
            url
            == "http://127.0.0.1:18080/proxy/assets/app.js?folder=/workspace/project&view=preview"
        )
        return httpx.Response(status_code=204)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/code/proxy/assets/app.js?folder=/workspace/project&view=preview",
            headers=get_jwt_headers(app),
        )

    assert response.status_code == 204


@pytest.mark.anyio
async def test_code_proxy_returns_upstream_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.code_server_manager = ReadyManager()
    app.state.code_server_supervisor = app.state.code_server_manager

    original_request = httpx.AsyncClient.request

    async def fake_request_timeout(
        self: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if str(url).startswith("/") or str(url).startswith("http://testserver"):
            return await original_request(self, method, url, **kwargs)
        raise httpx.ReadTimeout("upstream timed out")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request_timeout)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        timeout_response = await client.get("/code/", headers=get_jwt_headers(app))

    assert timeout_response.status_code == 503
    assert timeout_response.json() == {"detail": "code-server upstream timed out"}

    async def fake_request_transport(
        self: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if str(url).startswith("/") or str(url).startswith("http://testserver"):
            return await original_request(self, method, url, **kwargs)
        request = httpx.Request(method, url)
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request_transport)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        transport_response = await client.get("/code/", headers=get_jwt_headers(app))

    assert transport_response.status_code == 502
    assert transport_response.json() == {"detail": "code-server upstream request failed"}

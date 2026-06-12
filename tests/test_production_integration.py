"""Production integration tests.

These tests verify behavior that only manifests in production-like setups:
- Frontend SPA serving from dist directory
- /api prefix routing (no Vite proxy)
- Production mode (docs disabled, auth enforced)
- Health endpoint with degraded container connectivity
- Static asset serving

Run:  uv run pytest tests/test_production_integration.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.execution import ContainerConfig, ContainerHealth
pytestmark = [pytest.mark.integration]

async def _noop_async(self: object, **kwargs: object) -> None:
    """No-op for mocking SSHExecutor connect/close."""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fake_frontend(tmp_path: Path) -> Path:
    """Create a minimal frontend dist tree for SPA tests."""
    dist = tmp_path / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)

    (dist / "index.html").write_text(
        "<!DOCTYPE html><html><body>AINRF SPA</body></html>"
    )
    (assets / "main.js").write_text("console.log('ainrf');")
    (assets / "style.css").write_text("body{margin:0}")
    (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    (dist / "vite.svg").write_text("<svg></svg>")
    return dist


def _make_production_app(
    tmp_path: Path,
    *,
    frontend_dist: Path | None = None,
) -> tuple[FastAPI, httpx.AsyncClient]:
    """Create an app in production mode, optionally with frontend dist."""
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("test-key")}),
        state_root=tmp_path,
        production=True,
    )
    if frontend_dist is not None:
        os.environ["AINRF_FRONTEND_DIR"] = str(frontend_dist)
    try:
        app = create_app(api_config)
    finally:
        os.environ.pop("AINRF_FRONTEND_DIR", None)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )
    return app, client


def _activate_user(app: FastAPI, username: str) -> None:
    """Activate a registered user with admin role."""
    auth_service = app.state.auth_service
    with auth_service._connect() as conn:
        conn.execute(
            "UPDATE users SET status='active',"
            " activated_at='2025-01-01T00:00:00+00:00', role='admin'"
            f" WHERE username='{username}'"
        )
        conn.commit()


async def _register_activate_login(
    app: FastAPI, client: httpx.AsyncClient, *, username: str = "testadmin", password: str = "TestPassword123!"
) -> dict[str, str]:
    """Register, activate, and login — returns tokens."""
    auth_service = app.state.auth_service
    auth_service.initialize()
    auth_service.register(username=username, display_name=username.title(), password=password)
    _activate_user(app, username)
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# /api prefix routing
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_prefix_login_round_trip(tmp_path: Path) -> None:
    """POST /api/auth/login works without Vite proxy (production path)."""
    app, client = _make_production_app(tmp_path)
    async with client:
        data = await _register_activate_login(app, client)
        assert "access_token" in data
        assert "refresh_token" in data


@pytest.mark.anyio
async def test_api_prefix_auth_endpoints(tmp_path: Path) -> None:
    """All auth endpoints respond under /api prefix."""
    app, client = _make_production_app(tmp_path)
    async with client:
        # Register + activate + login
        tokens = await _register_activate_login(app, client, username="newuser", password="Password123!")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Me
        resp = await client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "newuser"

        # Refresh
        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()


@pytest.mark.anyio
async def test_api_prefix_health(tmp_path: Path) -> None:
    """GET /api/health returns 200 (same as /health)."""
    _, client = _make_production_app(tmp_path)
    async with client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# SPA frontend serving
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spa_root_returns_index_html(tmp_path: Path) -> None:
    """GET / returns index.html from frontend dist."""
    dist = _build_fake_frontend(tmp_path)
    _, client = _make_production_app(tmp_path, frontend_dist=dist)
    async with client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "AINRF SPA" in resp.text
        assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.anyio
async def test_spa_assets_served(tmp_path: Path) -> None:
    """Static assets under /assets/ are served correctly."""
    dist = _build_fake_frontend(tmp_path)
    _, client = _make_production_app(tmp_path, frontend_dist=dist)
    async with client:
        resp_js = await client.get("/assets/main.js")
        assert resp_js.status_code == 200
        assert "ainrf" in resp_js.text

        resp_css = await client.get("/assets/style.css")
        assert resp_css.status_code == 200
        assert "margin" in resp_css.text


@pytest.mark.anyio
async def test_spa_client_routes_return_index_html(tmp_path: Path) -> None:
    """SPA client-side routes (e.g. /dashboard) return index.html, not 401."""
    dist = _build_fake_frontend(tmp_path)
    _, client = _make_production_app(tmp_path, frontend_dist=dist)
    async with client:
        # These are SPA-only routes (not in API prefix list) — should get index.html
        for path in ["/dashboard", "/profile", "/about"]:
            resp = await client.get(path)
            assert resp.status_code == 200, f"GET {path} returned {resp.status_code}"
            assert "AINRF SPA" in resp.text


@pytest.mark.anyio
async def test_api_routes_not_intercepted_by_spa(tmp_path: Path) -> None:
    """API routes (e.g. POST /api/auth/login) are not caught by SPA fallback."""
    dist = _build_fake_frontend(tmp_path)
    _, client = _make_production_app(tmp_path, frontend_dist=dist)
    async with client:
        # POST to login should return JSON, not HTML
        resp = await client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert resp.headers.get("content-type", "").startswith("application/json")


# ---------------------------------------------------------------------------
# Production mode
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_production_disables_docs(tmp_path: Path) -> None:
    """OpenAPI docs are disabled in production mode."""
    _, client = _make_production_app(tmp_path)
    async with client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404


@pytest.mark.anyio
async def test_production_api_routes_require_auth(tmp_path: Path) -> None:
    """Protected API routes require authentication in production."""
    _, client = _make_production_app(tmp_path)
    async with client:
        for path in [
            "/api/tasks",
            "/api/sessions",
            "/api/environments",
            "/api/settings/codex-defaults",
            "/api/settings/deployment-version",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 401, f"GET {path} should be 401, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Health & container connectivity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_health_degraded_returns_200(tmp_path: Path) -> None:
    """Health returns 200 with status=degraded when SSH is unreachable."""
    app, client = _make_production_app(tmp_path)
    # Replace container config to trigger SSH health check
    app.state.api_config = ApiConfig(
        api_key_hashes=frozenset(),
        state_root=tmp_path,
        production=True,
        container_config=ContainerConfig(
            host="127.0.0.1",
            port=22,
            user="test",
            project_dir="/workspace",
            connect_timeout=1,
            command_timeout=1,
        ),
    )

    async def fake_ping(self: object, **kw: object) -> ContainerHealth:
        return ContainerHealth(
            ssh_ok=False,
            claude_ok=False,
            project_dir_writable=False,
            claude_version=None,
            gpu_models=[],
            cuda_version=None,
            disk_free_bytes=0,
            warnings=["SSH connection refused"],
        )

    import ainrf.api.routes.health as health_module

    _orig_ping = health_module.SSHExecutor.ping
    _orig_connect = health_module.SSHExecutor.connect
    _orig_close = health_module.SSHExecutor.close
    health_module.SSHExecutor.ping = fake_ping  # type: ignore[assignment]
    health_module.SSHExecutor.connect = _noop_async  # type: ignore[assignment]
    health_module.SSHExecutor.close = _noop_async  # type: ignore[assignment]
    try:
        async with client:
            resp = await client.get("/health")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            assert resp.json()["status"] == "degraded"
    finally:
        health_module.SSHExecutor.ping = _orig_ping
        health_module.SSHExecutor.connect = _orig_connect
        health_module.SSHExecutor.close = _orig_close


# ---------------------------------------------------------------------------
# Full auth + API flow under /api prefix
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_auth_flow_with_api_prefix(tmp_path: Path) -> None:
    """Complete auth flow: register -> login -> access API -> refresh -> change password."""
    app, client = _make_production_app(tmp_path)
    async with client:
        # Register + activate + login
        tokens = await _register_activate_login(app, client, username="flowuser", password="InitialPass1!")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Access protected endpoint
        resp = await client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200

        # Refresh token
        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert resp.status_code == 200
        new_access = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {new_access}"}
        # Change password
        resp = await client.post(
            "/api/auth/change-password",
            json={
                "old_password": "InitialPass1!",
                "new_password": "NewPassword2!",
            },
            headers=headers,
        )
        assert resp.status_code == 204

        # Login with new password
        resp = await client.post(
            "/api/auth/login",
            json={"username": "flowuser", "password": "NewPassword2!"},
        )
        assert resp.status_code == 200

        # Old password should fail
        resp = await client.post(
            "/api/auth/login",
            json={"username": "flowuser", "password": "InitialPass1!"},
        )
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_no_frontend_dist_no_spa_routes(tmp_path: Path) -> None:
    """Without frontend dist, app works as API-only (no SPA mount)."""
    _, client = _make_production_app(tmp_path)
    async with client:
        # API routes still work
        resp = await client.get("/api/health")
        assert resp.status_code == 200

        # Non-API routes without frontend: get 401 (auth required for API paths)
        # or 404 for unknown paths (no SPA fallback)
        resp = await client.get("/some-unknown-path")
        assert resp.status_code == 404

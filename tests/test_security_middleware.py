"""Tests for production security middleware: IP allowlist, request size, production mode."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key

pytestmark = [pytest.mark.middleware]

_API_KEY = "test-secret-key"


def _make_app(
    *,
    production: bool = False,
    allowed_cidrs: tuple[str, ...] = (),
) -> tuple[httpx.AsyncClient, Path]:
    tmp = Path(tempfile.mkdtemp())
    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
        state_root=tmp,
        production=production,
        allowed_cidrs=allowed_cidrs,
    )
    app = create_app(config)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )
    return client, tmp


@pytest.mark.anyio
class TestIpAllowlist:
    async def test_no_cidrs_allows_all(self):
        """When no CIDRs are configured, all IPs are allowed."""
        client, tmp = _make_app(allowed_cidrs=())
        try:
            resp = await client.get("/health")
            assert resp.status_code == 200
        finally:
            await client.aclose()

    async def test_matching_cidr_allows(self):
        client, tmp = _make_app(allowed_cidrs=("127.0.0.0/8",))
        try:
            resp = await client.get("/health")
            assert resp.status_code == 200
        finally:
            await client.aclose()

    async def test_non_matching_cidr_rejects(self):
        """A client IP not in the allowlist gets 403."""
        # httpx test client uses 127.0.0.1 which is in 10.0.0.0/8? No.
        client, tmp = _make_app(allowed_cidrs=("10.0.0.0/8",))
        try:
            resp = await client.get("/health")
            assert resp.status_code == 403
        finally:
            await client.aclose()

    async def test_forwarded_for_header_respected(self):
        client, tmp = _make_app(allowed_cidrs=("10.0.0.0/8",))
        try:
            resp = await client.get(
                "/health",
                headers={"X-Forwarded-For": "10.1.2.3"},
            )
            assert resp.status_code == 200
        finally:
            await client.aclose()


@pytest.mark.anyio
class TestRequestSizeLimit:
    async def test_small_body_passes(self):
        client, tmp = _make_app()
        try:
            # The default limit is 50 MB; a tiny body is fine.
            resp = await client.post(
                "/auth/login",
                json={"username": "x", "password": "y"},
            )
            # 401 is expected (bad creds), not 413.
            assert resp.status_code == 401
        finally:
            await client.aclose()

    async def test_oversized_body_rejected(self):
        """A request with Content-Length exceeding the limit gets 413."""
        tmp = Path(tempfile.mkdtemp())
        config = ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=tmp,
            max_request_body_bytes=100,  # 100 bytes
        )
        app = create_app(config)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )
        try:
            big_body = "x" * 200
            resp = await client.post(
                "/auth/login",
                content=big_body,
                headers={"Content-Length": str(len(big_body))},
            )
            assert resp.status_code == 413
        finally:
            await client.aclose()


@pytest.mark.anyio
class TestProductionMode:
    async def test_dev_mode_docs_accessible(self):
        client, tmp = _make_app(production=False)
        try:
            resp = await client.get("/openapi.json")
            assert resp.status_code == 200
        finally:
            await client.aclose()

    async def test_production_mode_docs_disabled(self):
        """In production, /openapi.json is not served (404 at route level) or
        blocked at middleware level (401). Either way, no schema is returned."""
        client, tmp = _make_app(production=True)
        try:
            resp = await client.get("/openapi.json")
            assert resp.status_code in (401, 404)
        finally:
            await client.aclose()

    async def test_production_mode_docs_page_disabled(self):
        client, tmp = _make_app(production=True)
        try:
            resp = await client.get("/docs")
            assert resp.status_code in (401, 404)
        finally:
            await client.aclose()

    async def test_production_mode_redoc_disabled(self):
        client, tmp = _make_app(production=True)
        try:
            resp = await client.get("/redoc")
            assert resp.status_code in (401, 404)
        finally:
            await client.aclose()

    async def test_external_model_probe_paths_are_exempt_in_both_modes(self):
        """Compatibility probes bypass API-key middleware in every deployment mode."""
        for production in (False, True):
            for path in ("/v1/models", "/v1/messages"):
                client, tmp = _make_app(production=production)
                try:
                    resp = await client.get(path)
                    # A route may intentionally be absent or use another
                    # method, but middleware must never turn a probe into 401.
                    assert resp.status_code != 401
                finally:
                    await client.aclose()

    async def test_health_always_accessible(self):
        """Health endpoint is exempt in both modes."""
        for production in (False, True):
            client, tmp = _make_app(production=production)
            try:
                resp = await client.get("/health")
                assert resp.status_code == 200
            finally:
                await client.aclose()

    async def test_auth_routes_always_accessible(self):
        """Login/register/refresh are always exempt."""
        for path in ("/auth/login", "/auth/register", "/auth/refresh"):
            client, tmp = _make_app(production=True)
            try:
                resp = await client.post(path, json={})
                # 422 (bad input) is expected, not 401.
                assert resp.status_code in (400, 422)
            finally:
                await client.aclose()

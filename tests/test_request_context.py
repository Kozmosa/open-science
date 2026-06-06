"""Tests for request_context middleware (request_id propagation)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key

pytestmark = [pytest.mark.middleware]


def _make_config(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        api_key_hashes=frozenset({hash_api_key("test")}),
        state_root=tmp_path,
    )


class TestRequestId:
    @pytest.mark.anyio
    async def test_response_has_request_id_header(self, tmp_path: Path) -> None:
        app = create_app(_make_config(tmp_path))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            request_id = resp.headers.get("x-request-id", "")
            assert len(request_id) == 36  # UUID4 format: 8-4-4-4-12
            assert request_id.count("-") == 4

    @pytest.mark.anyio
    async def test_unique_per_request(self, tmp_path: Path) -> None:
        app = create_app(_make_config(tmp_path))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/health")
            r2 = await client.get("/health")
            assert r1.headers["x-request-id"] != r2.headers["x-request-id"]

    @pytest.mark.anyio
    async def test_health_still_works(self, tmp_path: Path) -> None:
        app = create_app(_make_config(tmp_path))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

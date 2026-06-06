"""Tests for ainrf.api.routes.metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.api.routes.metrics import (
    dec_gauge,
    get_metrics_text,
    inc_counter,
    inc_gauge,
    observe_histogram,
    reset_metrics,
)
from tests.testutil import get_jwt_headers


pytestmark = [pytest.mark.unit]
@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    reset_metrics()
    yield
    reset_metrics()


def _make_config(tmp_path: Path, *, metrics: bool = False) -> ApiConfig:
    return ApiConfig(
        api_key_hashes=frozenset({hash_api_key("test")}),
        state_root=tmp_path,
        metrics_enabled=metrics,
    )


class TestCounterOps:
    def test_inc_counter_increments(self) -> None:
        inc_counter("ainrf_auth_login_success_total")
        text = get_metrics_text()
        assert "ainrf_auth_login_success_total" in text

    def test_inc_counter_with_labels(self) -> None:
        inc_counter("ainrf_auth_login_failed_total", labels={"reason": "locked"})
        text = get_metrics_text()
        assert 'reason="locked"' in text

    def test_inc_counter_accumulates(self) -> None:
        inc_counter("ainrf_auth_login_success_total")
        inc_counter("ainrf_auth_login_success_total")
        text = get_metrics_text()
        assert "2" in text


class TestHistogramOps:
    def test_observe_histogram(self) -> None:
        observe_histogram("ainrf_http_request_duration_seconds", 0.5)
        text = get_metrics_text()
        assert "ainrf_http_request_duration_seconds" in text
        assert "le=" in text


class TestGaugeOps:
    def test_gauge_inc_dec(self) -> None:
        inc_gauge("ainrf_terminal_ws_active")
        dec_gauge("ainrf_terminal_ws_active")
        text = get_metrics_text()
        assert "ainrf_terminal_ws_active 0" in text


class TestMetricsFormat:
    def test_prometheus_text_format(self) -> None:
        text = get_metrics_text()
        assert "# TYPE" in text or "# HELP" in text


class TestMetricsEndpoint:
    @pytest.mark.anyio
    async def test_returns_404_when_disabled(self, tmp_path: Path) -> None:
        app = create_app(_make_config(tmp_path, metrics=False))
        headers = get_jwt_headers(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/metrics", headers=headers)
            assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_returns_200_when_enabled(self, tmp_path: Path) -> None:
        app = create_app(_make_config(tmp_path, metrics=True))
        headers = get_jwt_headers(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/metrics", headers=headers)
            assert resp.status_code == 200
            assert "text/plain" in resp.headers.get("content-type", "")

    @pytest.mark.anyio
    async def test_includes_counters(self, tmp_path: Path) -> None:
        inc_counter("ainrf_auth_login_success_total")
        app = create_app(_make_config(tmp_path, metrics=True))
        headers = get_jwt_headers(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/metrics", headers=headers)
            assert "ainrf_auth_login_success_total" in resp.text

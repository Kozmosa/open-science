"""Tests for ainrf.api.routes.metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.api.routes.metrics import (
    dec_gauge,
    build_http_metrics_middleware,
    get_metrics_text,
    inc_counter,
    inc_gauge,
    observe_histogram,
    reset_metrics,
    set_counter,
    set_gauge,
)
from ainrf.api.routes.sla_metrics import rate_limited
from ainrf.api.routes import client_metrics
from tests.testutil import get_jwt_headers


pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    reset_metrics()
    client_metrics._ip_counts.clear()
    yield
    reset_metrics()
    client_metrics._ip_counts.clear()


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
        observe_histogram(
            "ainrf_http_request_duration_seconds",
            0.5,
            labels={"method": "GET", "path": "/test"},
        )
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


class TestPublicMetricPrivacy:
    def test_rate_limit_metric_rejects_raw_dynamic_paths(self) -> None:
        opaque_path = "/literature/papers/arxiv:2401.12345"

        rate_limited("user_quota", opaque_path)

        text = get_metrics_text()
        assert 'ainrf_rate_limited_total{reason="user_quota",route="/unmatched"}' in text
        assert opaque_path not in text

    def test_aggregates_ssh_and_literature_resource_labels(self) -> None:
        private_host = "tenant-gpu-42.internal"
        private_subscription_id = "subscription-tenant-42"
        private_target = "tenant-target-42"
        private_scope = "tenant-scope-42"
        inc_counter(
            "ainrf_ssh_connection_error_total",
            {"host": private_host, "target": private_target, "error_type": "TimeoutError"},
        )
        observe_histogram(
            "ainrf_ssh_command_duration_seconds",
            0.5,
            {"host": private_host},
        )
        inc_counter(
            "ainrf_literature_fetch_total",
            {
                "subscription_id": private_subscription_id,
                "scope": private_scope,
                "status": "success",
            },
        )
        set_counter(
            "ainrf_literature_papers_fetched_total",
            1.0,
            {"subscription_id": private_subscription_id},
        )
        set_gauge(
            "ainrf_literature_last_fetch_timestamp_seconds",
            1.0,
            {"subscription_id": private_subscription_id},
        )
        inc_gauge(
            "ainrf_literature_last_fetch_timestamp_seconds",
            {"subscription_id": private_subscription_id},
        )
        dec_gauge(
            "ainrf_literature_last_fetch_timestamp_seconds",
            {"subscription_id": private_subscription_id},
        )

        text = get_metrics_text()
        public_metrics = "\n".join(line for line in text.splitlines() if line.startswith("ainrf_"))

        assert 'target="all"' in public_metrics
        assert 'scope="all"' in public_metrics
        assert private_host not in public_metrics
        assert private_subscription_id not in public_metrics
        assert private_target not in public_metrics
        assert private_scope not in public_metrics
        assert "host=" not in public_metrics
        assert "subscription_id=" not in public_metrics

    @pytest.mark.anyio
    async def test_http_metrics_use_route_template_not_raw_url(self) -> None:
        app = FastAPI()

        @app.get("/literature/papers/{paper_id}")
        async def paper_detail(paper_id: str) -> dict[str, str]:
            return {"paper_id": paper_id}

        app.middleware("http")(build_http_metrics_middleware())
        opaque_paper_id = "arxiv:2401.12345"
        query_secret = "private-query-token"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/literature/papers/{opaque_paper_id}?token={query_secret}"
            )

        assert response.status_code == 200
        text = get_metrics_text()
        assert 'path="/literature/papers/{paper_id}"' in text
        assert opaque_paper_id not in text
        assert query_secret not in text

    @pytest.mark.anyio
    async def test_http_metrics_use_unmatched_series_before_routing(self) -> None:
        app = FastAPI()
        app.middleware("http")(build_http_metrics_middleware())
        opaque_path = "not-a-route-tenant-42"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/{opaque_path}")

        assert response.status_code == 404
        text = get_metrics_text()
        assert 'path="/unmatched"' in text
        assert opaque_path not in text

    @pytest.mark.anyio
    async def test_client_web_vitals_use_only_predeclared_bounded_metric_names_and_ratings(
        self, tmp_path: Path
    ) -> None:
        app = create_app(_make_config(tmp_path, metrics=True))
        private_name = "SECRET_TENANT_VITAL_42"
        private_rating = "tenant-secret-rating"
        private_url = "/tasks/tenant-private-task?token=private-query-token"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/client-metrics",
                json={
                    "metrics": [
                        {"name": "LCP", "value": 2.5, "rating": "good", "url": private_url},
                        {
                            "name": "CLS",
                            "value": 0.2,
                            "rating": private_rating,
                            "url": private_url,
                        },
                        {
                            "name": private_name,
                            "value": 1.0,
                            "rating": private_rating,
                            "url": private_url,
                        },
                    ]
                },
            )
            assert response.status_code == 204
            metrics = await client.get("/metrics")

        assert metrics.status_code == 200
        assert 'ainrf_client_lcp_seconds_bucket{le="0.005",rating="good"}' in metrics.text
        assert 'ainrf_client_cls_seconds_bucket{le="0.005",rating="unknown"}' in metrics.text
        assert private_name not in metrics.text
        assert private_rating not in metrics.text
        assert private_url not in metrics.text


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

    @pytest.mark.anyio
    async def test_public_endpoint_hides_resource_identifiers(self, tmp_path: Path) -> None:
        private_subscription_id = "subscription-tenant-42"
        inc_counter(
            "ainrf_literature_fetch_total",
            {"subscription_id": private_subscription_id, "status": "success"},
        )
        app = create_app(_make_config(tmp_path, metrics=True))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        assert 'scope="all"' in resp.text
        assert private_subscription_id not in resp.text
        assert "subscription_id=" not in resp.text

"""Privacy tests for HTTP request logging middleware."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import structlog
from fastapi import FastAPI

from ainrf.api.config import ApiConfig
from ainrf.api.middleware.request_logging import build_request_logging_middleware

pytestmark = [pytest.mark.middleware]


def _config(tmp_path: Path) -> ApiConfig:
    return ApiConfig(api_key_hashes=frozenset(), state_root=tmp_path)


@pytest.mark.anyio
async def test_request_log_uses_route_template_without_query_or_raw_path(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/literature/papers/{paper_id}")
    async def paper_detail(paper_id: str) -> dict[str, str]:
        return {"paper_id": paper_id}

    app.middleware("http")(build_request_logging_middleware(_config(tmp_path)))
    opaque_paper_id = "arxiv:2401.12345"
    query_secret = "private-query-token"

    with structlog.testing.capture_logs() as logs:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/literature/papers/{opaque_paper_id}?token={query_secret}"
            )

    assert response.status_code == 200
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == "request"
    assert entry["route"] == "/literature/papers/{paper_id}"
    assert "path" not in entry
    assert "query" not in entry
    assert opaque_paper_id not in str(entry)
    assert query_secret not in str(entry)

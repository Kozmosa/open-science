from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.literature.models import LiteraturePaper, LiteratureSubscription
from tests.testutil import get_jwt_headers


def make_auth_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.literature_service.initialize()
    headers = get_jwt_headers(app, username="admin", password="test-admin-password")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


async def fake_fetch_for_subscription(sub: LiteratureSubscription) -> list[LiteraturePaper]:
    await asyncio.sleep(0.02)
    return [
        LiteraturePaper(
            paper_id="2401.00001",
            subscription_id=sub.subscription_id,
            title="Async Literature Fetch",
            authors=["Ada Lovelace"],
            abstract="A test paper.",
            published_at="2026-01-01T00:00:00+00:00",
            arxiv_category="cs.AI",
        )
    ]


@pytest.mark.anyio
async def test_literature_fetch_status_reports_background_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ainrf.literature.fetcher.fetch_for_subscription",
        fake_fetch_for_subscription,
    )
    async with make_auth_client(tmp_path) as client:
        create_response = await client.post(
            "/literature/subscriptions",
            json={"label": "Agents", "keywords": ["agent"], "arxiv_categories": ["cs.AI"]},
        )
        subscription_id = create_response.json()["subscription_id"]

        trigger_response = await client.post(f"/literature/subscriptions/{subscription_id}/fetch")
        assert trigger_response.status_code == 202
        assert trigger_response.json()["status"] == "fetch_started"

        running_response = await client.get(f"/literature/subscriptions/{subscription_id}/fetch-status")
        assert running_response.status_code == 200
        assert running_response.json()["status"] in {"running", "completed"}

        for _ in range(10):
            status_response = await client.get(f"/literature/subscriptions/{subscription_id}/fetch-status")
            if status_response.json()["status"] == "completed":
                break
            await asyncio.sleep(0.01)

        assert status_response.json() == {"status": "completed", "error": None}
        papers_response = await client.get(
            f"/literature/papers?subscription_id={subscription_id}&limit=50"
        )
        assert papers_response.status_code == 200
        assert [paper["paper_id"] for paper in papers_response.json()["items"]] == ["2401.00001"]

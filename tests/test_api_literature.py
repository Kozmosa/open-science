from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest

from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.literature.tracking import DiscoveredPaper
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


def make_auth_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    app.state.literature_service.initialize()
    app.state.literature_tracking_service.initialize()
    headers = get_jwt_headers(app, username="admin", password="test-admin-password")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


@pytest.mark.anyio
async def test_legacy_fetch_routes_create_a_durable_check(
    tmp_path: Path,
) -> None:
    async with make_auth_client(tmp_path) as client:
        create_response = await client.post(
            "/literature/subscriptions",
            json={"label": "Agents", "keywords": ["agent"], "arxiv_categories": ["cs.AI"]},
        )
        subscription_id = create_response.json()["subscription_id"]

        trigger_response = await client.post(f"/literature/subscriptions/{subscription_id}/fetch")
        assert trigger_response.status_code == 202
        assert trigger_response.json()["status"] == "fetch_started"
        assert trigger_response.json()["check_id"]

        status_response = await client.get(
            f"/literature/subscriptions/{subscription_id}/fetch-status"
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "running"


@pytest.mark.anyio
async def test_tracking_api_uses_topics_user_states_and_durable_checks(tmp_path: Path) -> None:
    async with make_auth_client(tmp_path) as client:
        created = await client.post(
            "/literature/topics",
            json={
                "label": "Agents",
                "include_terms": ["agent"],
                "exclude_terms": [],
                "categories": ["cs.AI"],
            },
        )
        assert created.status_code == 201
        topic_id = created.json()["topic_id"]

        app = cast(FastAPI, cast(httpx.ASGITransport, client._transport).app)
        app.state.literature_tracking_service.store_discovered_papers(
            "seed",
            [
                DiscoveredPaper(
                    provider="arxiv",
                    external_id="2401.99999",
                    provider_version="v1",
                    title="Agent work",
                    authors=["Ada"],
                    abstract="An agent paper",
                    primary_category="cs.AI",
                    categories=["cs.AI"],
                    published_at=None,
                    updated_at=None,
                    source_url="https://arxiv.org/abs/2401.99999",
                    pdf_url="https://arxiv.org/pdf/2401.99999",
                )
            ],
        )

        papers = await client.get("/literature/papers?view=all")
        assert papers.status_code == 200
        item = papers.json()["items"][0]
        assert item["paper_id"] == "arxiv:2401.99999"
        assert item["matched_topics"][0]["topic_id"] == topic_id

        updated = await client.patch(
            f"/literature/papers/{item['paper_id']}/state", json={"is_saved": True}
        )
        assert updated.status_code == 200
        assert updated.json()["user_state"]["is_saved"] is True

        first_check = await client.post("/literature/checks", json={"topic_ids": [topic_id]})
        second_check = await client.post("/literature/checks", json={"topic_ids": [topic_id]})
        assert first_check.status_code == 202
        assert second_check.json()["check_id"] == first_check.json()["check_id"]

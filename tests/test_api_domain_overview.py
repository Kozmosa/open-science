"""V2 Today overview snapshot HTTP contracts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.domain.overview_jobs import OverviewSnapshotPlanner
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]

_API_KEY = "overview-api-key"


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )


def _payload(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


@pytest.mark.anyio
async def test_today_overview_uses_durable_refresh_jobs_and_real_planner_readiness(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-api-test-planner",
        artifact_sha=V2_ARTIFACT_SHA,
        active_user_ids=lambda: (),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            unavailable = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
            assert unavailable.status_code == 200
            unavailable_payload = _payload(unavailable)
            assert unavailable_payload["overview_snapshot"] is False
            assert unavailable_payload["overview_snapshot_job_store"] is True
            # A planner process alone cannot dispatch Task or Literature saga
            # work; those capabilities require the separate domain worker.
            assert unavailable_payload["literature_research_task"] is False

            before_refresh = await client.get(f"/domain/overview/today?api_key={_API_KEY}")
            assert before_refresh.status_code == 404

            first = await client.post(f"/domain/overview/today/refresh?api_key={_API_KEY}")
            second = await client.post(f"/domain/overview/today/refresh?api_key={_API_KEY}")
            assert first.status_code == 202
            assert second.status_code == 202
            first_job = _payload(first)
            second_job = _payload(second)
            assert first_job["job_id"] == second_job["job_id"]
            assert first_job["status"] == "queued"
            assert first_job["retry_count"] == 0
            assert first_job["next_retry_at"] is None
            assert first_job["last_failure_at"] is None

            job_id = str(first_job["job_id"])
            status_response = await client.get(
                f"/domain/overview/refresh/{job_id}?api_key={_API_KEY}"
            )
            assert status_response.status_code == 200
            status_payload = _payload(status_response)
            assert status_payload["owner_user_id"] == "api-key-user"
            assert status_payload["retry_count"] == 0
            assert status_payload["next_retry_at"] is None

            planner_result = planner.run_once()
            assert job_id in planner_result.completed_job_ids

            available = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
            assert available.status_code == 200
            available_payload = _payload(available)
            assert available_payload["overview_snapshot"] is True
            planner_status = available_payload["overview_snapshot_planner"]
            assert isinstance(planner_status, dict)
            assert cast(dict[str, object], planner_status)["planner_ready"] is True

            refreshed = await client.get(f"/domain/overview/today?api_key={_API_KEY}")
            assert refreshed.status_code == 200
            snapshot = _payload(refreshed)
            cards = snapshot["cards"]
            assert isinstance(cards, list)
            card_payloads = [
                cast(dict[str, object], card) for card in cards if isinstance(card, dict)
            ]
            assert {card["id"] for card in card_payloads} == {
                "domain",
                "literature",
                "resources",
            }
            assert all(
                isinstance(card.get("data_cutoff_at"), str)
                and isinstance(card.get("source_status"), str)
                and isinstance(card.get("attention_required"), bool)
                for card in card_payloads
            )
            display_cards = snapshot["display_cards"]
            assert isinstance(display_cards, list)
            display_payloads = [
                cast(dict[str, object], card) for card in display_cards if isinstance(card, dict)
            ]
            assert [card["id"] for card in display_payloads] == [
                "attention",
                "progress",
                "literature",
                "continue",
                "resources",
            ]
            assert all(
                isinstance(card.get("data_cutoff_at"), str)
                and isinstance(card.get("source_status"), str)
                and isinstance(card.get("attention_required"), bool)
                and "error_summary" in card
                for card in display_payloads
            )
            assert isinstance(snapshot["next_scheduled_at"], str)
    finally:
        planner.stop()

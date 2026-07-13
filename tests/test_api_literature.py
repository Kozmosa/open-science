from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest

from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain import DomainService, ProjectContextService
from ainrf.domain_control import DomainModelMode
from ainrf.literature.tracking import DiscoveredPaper
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


def _body(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


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
async def test_research_task_routes_reject_malformed_json_without_server_error(
    tmp_path: Path,
) -> None:
    async with make_auth_client(tmp_path) as client:
        formal = await client.post(
            "/literature/papers/arxiv:missing/research-task",
            content="{",
            headers={"Content-Type": "application/json"},
        )
        assert formal.status_code == 400

        deprecated = await client.post(
            "/literature/papers/arxiv:missing/convert",
            content="{",
            headers={"Content-Type": "application/json"},
        )
    assert deprecated.status_code == 400
    assert deprecated.headers["deprecation"] == "true"


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


def _v2_literature_app(state_root: Path, tmp_path: Path) -> tuple[FastAPI, str]:
    api_key = "literature-v2-key"
    prepare_committed_v2_cutover(state_root, tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(api_key)}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )
    owner: dict[str, object] = {"id": "api-key-user", "role": "user"}
    admin: dict[str, object] = {"id": "literature-v2-admin", "role": "admin"}
    domain: DomainService = app.state.domain_service
    environment = domain.create_environment(
        admin,
        alias="literature-v2-host",
        display_name="Literature V2 Host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="literature-v2-admin",
        reason="Literature v2 saga route test",
    )
    project = domain.create_project(owner, name="Literature V2 Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(state_root / "literature-v2-workspace"),
        label="Literature V2 Workspace",
    )
    domain.attach_workspace(
        project_id,
        str(workspace["workspace_id"]),
        owner,
        idempotency_key="literature-v2-attach",
    )
    domain.set_primary_workspace(
        project_id,
        str(workspace["workspace_id"]),
        owner,
        idempotency_key="literature-v2-primary",
    )
    context: ProjectContextService = app.state.project_context_service
    context.save_draft(project_id, "Literature v2 context", owner)
    context.publish(project_id, owner, idempotency_key="literature-v2-context")
    tracking = app.state.literature_tracking_service
    tracking.initialize()
    tracking.create_topic(
        user_id="api-key-user",
        label="Literature route test",
        include_terms=["agent"],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    tracking.store_discovered_papers(
        "literature-v2-seed",
        [
            DiscoveredPaper(
                provider="arxiv",
                external_id="2607.00001",
                provider_version="v1",
                title="Agent route paper",
                authors=["Ada"],
                abstract="An agent research paper",
                primary_category="cs.AI",
                categories=["cs.AI"],
                published_at=None,
                updated_at=None,
                source_url="https://arxiv.org/abs/2607.00001",
                pdf_url="https://arxiv.org/pdf/2607.00001",
            )
        ],
    )
    return app, project_id


@pytest.mark.anyio
async def test_v2_research_task_routes_are_idempotent_and_reject_environment_input(
    state_root: Path, tmp_path: Path
) -> None:
    app, project_id = _v2_literature_app(state_root, tmp_path)
    paper_id = "arxiv:2607.00001"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        body = {"project_id": project_id, "task_preset": "overview"}
        first = await client.post(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key",
            headers={"Idempotency-Key": "literature-route-a"},
            json=body,
        )
        assert first.status_code == 201
        first_payload = _body(first)
        assert first_payload["status"] == "completed"
        assert first_payload["task_id"]

        repeated = await client.post(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key",
            headers={"Idempotency-Key": "literature-route-a"},
            json=body,
        )
        assert repeated.status_code == 201
        assert _body(repeated)["task_id"] == first_payload["task_id"]

        different = await client.post(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key",
            headers={"Idempotency-Key": "literature-route-b"},
            json=body,
        )
        assert different.status_code == 201
        assert _body(different)["task_id"] != first_payload["task_id"]

        listed = await client.get(
            f"/literature/papers/{paper_id}/research-tasks?api_key=literature-v2-key"
        )
        assert listed.status_code == 200
        listed_items = _body(listed)["items"]
        assert isinstance(listed_items, list)
        assert len(listed_items) == 2

        one = await client.get(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key"
            "&idempotency_key=literature-route-a"
        )
        assert one.status_code == 200
        assert _body(one)["task_id"] == first_payload["task_id"]

        mismatch = await client.post(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key",
            headers={"Idempotency-Key": "header-key"},
            json={**body, "idempotency_key": "body-key"},
        )
        assert mismatch.status_code == 409

        environment = await client.post(
            f"/literature/papers/{paper_id}/research-task?api_key=literature-v2-key",
            headers={"Idempotency-Key": "environment-key"},
            json={**body, "environment_id": "must-not-be-accepted"},
        )
        assert environment.status_code == 400


@pytest.mark.anyio
async def test_v2_convert_proxy_rejects_external_task_id_and_marks_deprecation(
    state_root: Path, tmp_path: Path
) -> None:
    app, project_id = _v2_literature_app(state_root, tmp_path)
    paper_id = "arxiv:2607.00001"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        rejected = await client.post(
            f"/literature/papers/{paper_id}/convert?api_key=literature-v2-key",
            json={"project_id": project_id, "task_id": "arbitrary-task"},
        )
        assert rejected.status_code == 400
        assert rejected.headers["deprecation"] == "true"

        converted = await client.post(
            f"/literature/papers/{paper_id}/convert?api_key=literature-v2-key",
            headers={"Idempotency-Key": "convert-proxy-key"},
            json={"project_id": project_id},
        )
    assert converted.status_code == 201
    assert converted.headers["deprecation"] == "true"
    assert converted.headers["sunset"]
    assert _body(converted)["status"] == "completed"

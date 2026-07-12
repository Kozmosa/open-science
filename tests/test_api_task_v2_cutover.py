"""B7 v2 Task route, Attempt projection, and compatibility contracts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]

_API_KEY = "task-v2-key"
_OWNER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "task-v2-admin", "role": "admin"}


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )
    return app


def _prepare_task_scope(app: FastAPI, state_root: Path) -> tuple[str, str, str]:
    domain = app.state.domain_service
    environment = domain.create_environment(
        _ADMIN,
        alias="task-v2-host",
        display_name="Task V2 Host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="task-v2-admin",
        reason="Task v2 adapter test",
    )
    project = domain.create_project(_OWNER, name="Task V2 Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        _OWNER,
        environment_id=environment_id,
        canonical_path=str(state_root / "task-v2-workspace"),
        label="Task V2 Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, _OWNER, idempotency_key="task-v2-link")
    context = app.state.project_context_service
    context.save_draft(project_id, "Task v2 context", _OWNER)
    context.publish(project_id, _OWNER, idempotency_key="task-v2-context")
    return project_id, workspace_id, environment_id


def _body(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


@pytest.mark.anyio
async def test_v2_task_routes_return_task_attempt_dispatch_and_retry_same_task(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Inspect the durable Task contract",
                "skills": [],
            },
        )
        assert created.status_code == 201
        assert created.headers["deprecation"] == "true"
        created_payload = _body(created)
        task = cast(dict[str, object], created_payload["task"])
        attempt = cast(dict[str, object], created_payload["attempt"])
        dispatch = cast(dict[str, object], created_payload["dispatch"])
        task_id = str(task["task_id"])
        assert created_payload["task_id"] == task_id
        assert attempt["task_id"] == task_id
        assert dispatch["attempt_id"] == attempt["attempt_id"]
        assert dispatch["status"] == "pending"

        attempts = await client.get(f"/tasks/{task_id}/attempts?api_key={_API_KEY}")
        assert attempts.status_code == 200
        attempt_items = cast(list[dict[str, object]], _body(attempts)["items"])
        assert [item["attempt_id"] for item in attempt_items] == [attempt["attempt_id"]]
        assert (
            cast(dict[str, object], attempt_items[0]["dispatch"])["dispatch_id"]
            == dispatch["dispatch_id"]
        )

        retried = await client.post(
            f"/tasks/{task_id}/retry?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-retry"},
            json={},
        )
        assert retried.status_code == 201
        assert retried.headers["deprecation"] == "true"
        retried_payload = _body(retried)
        assert cast(dict[str, object], retried_payload["new_task"])["task_id"] == task_id
        assert cast(dict[str, object], retried_payload["task"])["task_id"] == task_id
        retried_attempt = cast(dict[str, object], retried_payload["attempt"])
        assert retried_attempt["attempt_seq"] == 2
        assert (
            cast(dict[str, object], retried_payload["dispatch"])["attempt_id"]
            == retried_attempt["attempt_id"]
        )


@pytest.mark.anyio
async def test_v2_task_capabilities_and_idempotency_contract(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        capabilities = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
        assert capabilities.status_code == 200
        capability_payload = _body(capabilities)
        assert capability_payload["standard_task_create"] is True
        assert capability_payload["task_attempts"] is True
        assert capability_payload["literature_research_task"] is True
        assert capability_payload["overview_snapshot"] is False

        mismatch = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "header-key"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Reject conflicting idempotency transport",
                "skills": [],
                "idempotency_key": "body-key",
            },
        )
        assert mismatch.status_code == 409

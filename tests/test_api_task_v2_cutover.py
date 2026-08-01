"""Canonical Conversation HTTP cutover contracts."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain.conversation_contracts import TurnItemActor, TurnItemType, TurnStatus
from ainrf.domain.conversation_execution import ConversationExecutionService
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]

_API_KEY = "conversation-v3-key"
_OWNER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "conversation-v3-admin", "role": "admin"}


def _app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )


def _scope(app: FastAPI, state_root: Path) -> tuple[str, str]:
    domain = app.state.project_module
    environment = domain.create_environment(
        _ADMIN, alias="conversation-host", display_name="Conversation Host", connection={}
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="conversation-v3-admin",
        reason="Conversation HTTP contract",
    )
    project = domain.create_project(_OWNER, name="Conversation Project")
    project_id = str(project["project_id"])
    workspace_path = state_root / "conversation-workspace"
    workspace_path.mkdir(parents=True)
    workspace = domain.create_workspace(
        _OWNER,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Conversation Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, _OWNER, idempotency_key="scope-link")
    context = app.state.project_context_service
    context.save_draft(project_id, "Canonical context", _OWNER)
    context.publish(project_id, _OWNER, idempotency_key="scope-context")
    return project_id, workspace_id


def _body(response: httpx.Response) -> dict[str, object]:
    value = response.json()
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.anyio
async def test_create_task_uses_submission_authority_without_attempt_dual_write(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root, tmp_path)
    project_id, workspace_id = _scope(app, state_root)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "create-conversation-task"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Inspect the canonical contract",
                "skills": [],
            },
        )
    assert created.status_code == 202
    payload = _body(created)
    task = cast(dict[str, object], payload["task"])
    submission = cast(dict[str, object], payload["submission"])
    assert submission["task_id"] == task["task_id"]
    assert submission["status"] == "queued"
    assert "attempt" not in payload and "dispatch" not in payload
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM agent_task_attempts WHERE task_id = ?", (task["task_id"],)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.anyio
async def test_conversation_http_reads_turns_items_and_hides_runtime_identity(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root, tmp_path)
    project_id, workspace_id = _scope(app, state_root)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "conversation-history"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Show canonical history",
                "skills": [],
            },
        )
        task_id = str(cast(dict[str, object], _body(created)["task"])["task_id"])
        execution_service = ConversationExecutionService(state_root, artifact_sha=V2_ARTIFACT_SHA)
        claim = execution_service.claim_next_submission()
        assert claim is not None
        execution_service.begin_delivery(claim.submission_id)
        execution = execution_service.accept_and_open_execution(
            claim,
            engine_family="claude",
            engine_driver="claude-code",
            native_turn_kind="cli_process",
            native_turn_ref="native-turn",
            native_runtime_kind="process",
            native_runtime_ref="native-runtime",
            evidence={"accepted": True},
        )
        execution_service.append_item(
            execution,
            item_type=TurnItemType.AGENT_MESSAGE,
            actor=TurnItemActor.AGENT,
            payload={"text": "Canonical answer"},
            native_provenance={"source": "test"},
        )
        execution_service.finish_execution(
            execution, status=TurnStatus.COMPLETED, evidence={"terminal": True}
        )

        turns = await client.get(f"/api/tasks/{task_id}/turns?api_key={_API_KEY}")
        assert turns.status_code == 200
        turn = cast(list[dict[str, object]], _body(turns)["items"])[0]
        items = await client.get(
            f"/api/tasks/{task_id}/turns/{turn['turn_id']}/items?api_key={_API_KEY}"
        )
    assert items.status_code == 200
    item_values = cast(list[dict[str, object]], _body(items)["items"])
    assert [item["item_type"] for item in item_values] == ["user_message", "agent_message"]
    assert all("runtime_execution_id" not in item for item in item_values)


@pytest.mark.anyio
async def test_retired_attempt_pause_resume_continue_and_output_routes_are_unroutable(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root, tmp_path)
    retired = [
        ("GET", "/api/tasks/task-id/attempts"),
        ("POST", "/api/tasks/task-id/pause"),
        ("POST", "/api/tasks/task-id/resume"),
        ("POST", "/api/tasks/task-id/continue"),
        ("GET", "/api/tasks/task-id/output"),
        ("GET", "/api/tasks/task-id/messages"),
        ("GET", "/api/tasks/task-id/stream"),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for method, path in retired:
            response = await client.request(method, f"{path}?api_key={_API_KEY}")
            assert response.status_code == 404, (method, path, response.text)

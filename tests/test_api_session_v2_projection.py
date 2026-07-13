"""V2 Session compatibility routes read durable TaskAttempt projections only."""

from __future__ import annotations

import json
from collections.abc import Mapping
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
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import seed_user

pytestmark = [pytest.mark.api]

_API_KEY = "session-v2-key"
_USER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "session-v2-admin", "role": "admin"}


def _body(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, Mapping)
    return {str(key): item for key, item in cast(Mapping[object, object], value).items()}


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


def _headers(app: FastAPI, username: str, user_id: str, role: str) -> dict[str, str]:
    auth = app.state.auth_service
    seed_user(auth, username, "session-v2-output-password", role=role, user_id=user_id)
    token = auth.login(username=username, password="session-v2-output-password")
    return {"Authorization": f"Bearer {token['access_token']}"}


def _prepare_task_scope(app: FastAPI, state_root: Path) -> tuple[str, str, str]:
    domain = app.state.domain_service
    environment = domain.create_environment(
        _ADMIN,
        alias="session-v2-host",
        display_name="Session V2 Host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="session-v2-admin",
        reason="Session v2 projection test",
    )
    project = domain.create_project(_USER, name="Session V2 Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        _USER,
        environment_id=environment_id,
        canonical_path=str(state_root / "session-v2-workspace"),
        label="Session V2 Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, _USER, idempotency_key="session-v2-link")
    context = app.state.project_context_service
    context.save_draft(project_id, "Session v2 context", _USER)
    context.publish(project_id, _USER, idempotency_key="session-v2-context")
    return project_id, workspace_id, environment_id


@pytest.mark.anyio
async def test_v2_sessions_are_task_attempt_projections_and_never_open_legacy_db(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    assert app.state.session_service is None
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "session-v2-task"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Project durable Session compatibility",
                "skills": [],
            },
        )
        assert created.status_code == 201
        created_payload = _body(created)
        task = cast(dict[str, object], created_payload["task"])
        attempt = cast(dict[str, object], created_payload["attempt"])
        task_id = str(task["task_id"])
        attempt_id = str(attempt["attempt_id"])

        with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
            conn.execute(
                """UPDATE agent_task_attempts
                   SET status = 'succeeded', token_usage_json = ?, cost_usd = ?,
                       failure_reason = ?, stop_reason = ?, authorization_environment_id = ?,
                       authorization_grant_version = ?, authorization_checked_at = ?,
                       stop_requested_at = ?, stop_requested_reason = ?
                   WHERE attempt_id = ?""",
                (
                    json.dumps(
                        {
                            "total": {
                                "input_tokens": 5,
                                "output_tokens": 3,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 1,
                                "cost_usd": 0.08,
                            }
                        }
                    ),
                    0.19,
                    "/home/tenant/private-attempt-error",
                    "/home/tenant/private-stop-reason",
                    "environment-private-id",
                    7,
                    "2026-07-12T00:00:01+00:00",
                    "2026-07-12T00:00:02+00:00",
                    "/home/tenant/private-stop-request",
                    attempt_id,
                ),
            )
            conn.execute(
                """INSERT INTO agent_runtime_sessions (
                       runtime_session_id, attempt_id, launch_key, status, created_at,
                       started_at, finished_at, engine_name
                   ) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)""",
                (
                    "runtime-api-session-1",
                    attempt_id,
                    "launch-api-session-1",
                    "2026-07-12T00:00:00+00:00",
                    "2026-07-12T00:00:02+00:00",
                    "2026-07-12T00:00:05+00:00",
                    "claude-code",
                ),
            )
            conn.execute(
                """UPDATE agent_runtime_sessions
                   SET engine_session_key = ?, failure_reason = ?
                   WHERE runtime_session_id = ?""",
                (
                    "tenant-engine-session-secret",
                    "/home/tenant/private-engine-error",
                    "runtime-api-session-1",
                ),
            )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET runtime_launch_key = ?, dispatcher_id = ?, last_error = ?
                   WHERE attempt_id = ?""",
                (
                    "tenant-runtime-launch-secret",
                    "dispatcher-private-id",
                    "/home/tenant/private-dispatch-error",
                    attempt_id,
                ),
            )
            # The former Task-level usage cache is deliberately not a v2
            # authority.  Every compatibility view below must ignore it.
            conn.execute(
                "UPDATE tasks SET token_usage_json = ? WHERE task_id = ?",
                (
                    json.dumps(
                        {
                            "total": {
                                "input_tokens": 999,
                                "output_tokens": 999,
                                "cost_usd": 999.0,
                            }
                        }
                    ),
                    task_id,
                ),
            )
            conn.commit()

        listed = await client.get(f"/sessions?api_key={_API_KEY}")
        assert listed.status_code == 200
        listed_payload = _body(listed)
        sessions = cast(list[dict[str, object]], listed_payload["items"])
        assert sessions == [
            {
                "id": task_id,
                "project_id": project_id,
                "title": task["title"],
                "status": task["status"],
                "task_count": 1,
                "total_duration_ms": 3000,
                "total_cost_usd": 0.19,
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
                "owner_user_id": "api-key-user",
            }
        ]

        detail = await client.get(f"/sessions/{task_id}?api_key={_API_KEY}")
        assert detail.status_code == 200
        detail_payload = _body(detail)
        attempts = cast(list[dict[str, object]], detail_payload["attempts"])
        assert attempts[0]["id"] == attempt_id
        assert attempts[0]["duration_ms"] == 3000
        assert attempts[0]["token_usage_json"] is not None

        attempt_list = await client.get(f"/sessions/{task_id}/attempts?api_key={_API_KEY}")
        assert attempt_list.status_code == 200
        assert _body(attempt_list)["items"] == attempts

        batch = await client.get(f"/sessions/batch-detail?api_key={_API_KEY}&ids={task_id}")
        assert batch.status_code == 200
        assert _body(batch) == {"items": {task_id: attempts}}

        task_detail = await client.get(f"/tasks/{task_id}?api_key={_API_KEY}")
        assert task_detail.status_code == 200
        task_detail_payload = _body(task_detail)
        # Timeline consumes Task summaries for compatibility, but v2 Task
        # timestamps must come from the Attempt/Runtime projection rather
        # than the stale ``tasks`` cache columns.
        assert task_detail_payload["started_at"] == "2026-07-12T00:00:02+00:00"
        assert task_detail_payload["completed_at"] == "2026-07-12T00:00:05+00:00"
        task_usage = json.loads(str(task_detail_payload["token_usage_json"]))
        assert task_usage["total"] == {
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1,
            "cost_usd": 0.19,
            "input_tokens": 5,
            "output_tokens": 3,
        }

        usage_summary = await client.get(f"/tasks/token-usage?api_key={_API_KEY}")
        assert usage_summary.status_code == 200
        usage_payload = _body(usage_summary)
        assert usage_payload["task_count"] == 1
        assert usage_payload["tasks_with_usage"] == 1
        assert usage_payload["total_tokens"] == 9
        assert usage_payload["total_cost_usd"] == 0.19
        assert usage_payload["total_duration_ms"] == 3000
        assert usage_payload["median_duration_ms"] == 3000
        assert usage_payload["total"] == task_usage["total"]
        assert usage_payload["by_engine"] == {
            "claude-code": {
                "task_count": 1,
                "tasks_with_usage": 1,
                "tokens": 9,
                "cost_usd": 0.19,
            }
        }

        cost = await client.get(f"/projects/{project_id}/cost-summary?api_key={_API_KEY}")
        assert cost.status_code == 200
        assert _body(cost) == {
            "project_id": project_id,
            "total_cost_usd": 0.19,
            "total_tokens": 9,
            "session_count": 1,
            "by_model": {},
        }

        assert (
            await client.post(
                f"/sessions?api_key={_API_KEY}",
                json={
                    "project_id": project_id,
                    "title": "must not write",
                },
            )
        ).status_code == 405
        # A v2 Session write is rejected before body validation, so a client
        # cannot observe a different contract merely by sending malformed
        # historical request data.
        assert (
            await client.post(f"/sessions?api_key={_API_KEY}", content=b"not-json")
        ).status_code == 405
        assert (
            await client.patch(f"/sessions/{task_id}?api_key={_API_KEY}", json={})
        ).status_code == 405
        assert (
            await client.patch(f"/sessions/{task_id}?api_key={_API_KEY}", content=b"not-json")
        ).status_code == 405
        assert (await client.delete(f"/sessions/{task_id}?api_key={_API_KEY}")).status_code == 405

        # The compatibility projection has no delete/archive side effect.  A
        # rejected Session write must leave the authoritative Task and its
        # durable Attempt history exactly where the read projection found it.
        task_after_session_writes = await client.get(f"/tasks/{task_id}?api_key={_API_KEY}")
        assert task_after_session_writes.status_code == 200
        assert _body(task_after_session_writes)["task_id"] == task_id
        attempts_after_session_writes = await client.get(
            f"/tasks/{task_id}/attempts?api_key={_API_KEY}"
        )
        assert attempts_after_session_writes.status_code == 200
        after_items = cast(list[dict[str, object]], _body(attempts_after_session_writes)["items"])
        assert [(item["attempt_id"], item["status"]) for item in after_items] == [
            (attempt_id, "succeeded")
        ]
        public_runtime_values = after_items[0]["runtime_sessions"]
        assert isinstance(public_runtime_values, list) and public_runtime_values
        public_runtime = _mapping(public_runtime_values[0])
        public_dispatch = _mapping(after_items[0]["dispatch"])
        assert public_runtime["engine_session_key"] is None
        assert public_runtime["failure_reason"] is None
        assert public_dispatch["runtime_launch_key"] is None
        assert public_dispatch["dispatcher_id"] is None
        assert public_dispatch["last_error"] is None
        assert after_items[0]["failure_reason"] is None
        assert after_items[0]["stop_reason"] is None
        assert after_items[0]["authorization_environment_id"] is None
        assert after_items[0]["authorization_grant_version"] is None
        assert after_items[0]["authorization_checked_at"] is None
        assert after_items[0]["stop_requested_at"] is None
        assert after_items[0]["stop_requested_reason"] is None

    assert not (state_root / "runtime" / "sessions.sqlite3").exists()


@pytest.mark.anyio
async def test_v2_project_viewer_output_routes_and_sse_redact_durable_secrets(
    state_root: Path,
    tmp_path: Path,
) -> None:
    """A Project viewer sees dialogue, never another tenant's runtime detail."""

    app = _v2_app(state_root, tmp_path)
    owner_headers = _headers(app, "output-owner", "api-key-user", "member")
    viewer_headers = _headers(app, "output-viewer", "output-viewer", "member")
    administrator_headers = _headers(app, "output-admin", "output-admin", "admin")
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)
    app.state.domain_service.add_member(project_id, "output-viewer", "viewer", False, _USER)
    durable_output = json.dumps(
        {
            "role": "assistant",
            "content": (
                "Authorization: Bearer viewer-route-token; "
                "API key: sk-viewer-route-secret; "
                "cwd=/home/ainrf_tenants/api-key-user/private-workspace"
            ),
            "metadata": {
                "OPENAI_API_KEY": "sk-viewer-route-secret",
                "bearerToken": "camel-bearer-token-value",
                "keyValue": "camel-key-value",
                "cwd": "/home/ainrf_tenants/api-key-user/private-workspace",
            },
        },
        separators=(",", ":"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/tasks",
            headers={**owner_headers, "Idempotency-Key": "viewer-output-route-task"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Shared output redaction",
                "skills": [],
            },
        )
        assert created.status_code == 201
        created_task = cast(dict[str, object], _body(created)["task"])
        task_id = str(created_task["task_id"])

        # This direct fixture write models pre-existing engine evidence.  The
        # public API must only transform it on the shared viewer read path.
        with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
            conn.execute(
                """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
                   VALUES (?, 1, 'message', ?, ?)""",
                (task_id, durable_output, "2026-07-13T00:00:00+00:00"),
            )
            conn.execute(
                """UPDATE tasks
                   SET status = 'succeeded', latest_output_seq = 1
                   WHERE task_id = ?""",
                (task_id,),
            )
            conn.commit()

        viewer_output = await client.get(f"/tasks/{task_id}/output", headers=viewer_headers)
        viewer_messages = await client.get(f"/tasks/{task_id}/messages", headers=viewer_headers)
        owner_output = await client.get(f"/tasks/{task_id}/output", headers=owner_headers)
        administrator_output = await client.get(
            f"/tasks/{task_id}/output", headers=administrator_headers
        )
        async with client.stream(
            "GET", f"/tasks/{task_id}/stream", headers=viewer_headers
        ) as viewer_stream:
            assert viewer_stream.status_code == 200
            viewer_stream_body = "".join([part async for part in viewer_stream.aiter_text()])

    assert viewer_output.status_code == 200
    assert viewer_messages.status_code == 200
    assert owner_output.status_code == 200
    assert administrator_output.status_code == 200
    owner_items = cast(list[dict[str, object]], _body(owner_output)["items"])
    administrator_items = cast(list[dict[str, object]], _body(administrator_output)["items"])
    assert owner_items[0]["content"] == durable_output
    assert administrator_items[0]["content"] == durable_output

    viewer_items = cast(list[dict[str, object]], _body(viewer_output)["items"])
    viewer_content = str(viewer_items[0]["content"])
    assert '"bearerToken":"[REDACTED]"' in viewer_content
    assert '"keyValue":"[REDACTED]"' in viewer_content

    viewer_response_text = json.dumps(_body(viewer_output))
    viewer_messages_text = json.dumps(_body(viewer_messages))
    for rendered_view in (viewer_response_text, viewer_messages_text, viewer_stream_body):
        assert "viewer-route-token" not in rendered_view
        assert "sk-viewer-route-secret" not in rendered_view
        assert "camel-bearer-token-value" not in rendered_view
        assert "camel-key-value" not in rendered_view
        assert "/home/ainrf_tenants/api-key-user/private-workspace" not in rendered_view
        assert "[REDACTED]" in rendered_view
        assert "[REDACTED_PATH]" in rendered_view

"""V2 Session compatibility routes read durable TaskAttempt projections only."""

from __future__ import annotations

import json
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

pytestmark = [pytest.mark.api]

_API_KEY = "session-v2-key"
_USER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "session-v2-admin", "role": "admin"}


def _body(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


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
                   SET status = 'succeeded', token_usage_json = ?, cost_usd = ?
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
        task_usage = json.loads(str(_body(task_detail)["token_usage_json"]))
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
        assert (
            await client.patch(f"/sessions/{task_id}?api_key={_API_KEY}", json={})
        ).status_code == 405
        assert (await client.delete(f"/sessions/{task_id}?api_key={_API_KEY}")).status_code == 405

    assert not (state_root / "runtime" / "sessions.sqlite3").exists()

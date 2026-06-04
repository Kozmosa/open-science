from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.agentic_researcher import (
    AgenticResearcherService,
    HarnessEngineType,
    TaskStatus,
    vanilla,
)
from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.harness_engine import EngineEvent, ExecutionContext, HarnessEngine
from ainrf.harness_engine.base import EngineEmit
from tests.testutil import get_jwt_headers


class FakeEngine(HarnessEngine):
    def __init__(self) -> None:
        self.pending_prompts: list[str] = []

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        prompt = self.pending_prompts.pop(0) if self.pending_prompts else context.rendered_prompt
        await emit(
            EngineEvent(
                event_type="message",
                payload={"role": "assistant", "content": f"ran: {prompt}"},
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )

    async def send_input(self, task_id: str, text: str) -> None:
        _ = task_id
        self.pending_prompts.append(text)

    async def cancel(self, task_id: str) -> None:
        _ = task_id




class TokenEngine(FakeEngine):
    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        await emit(
            EngineEvent(
                event_type="token",
                payload={"turn": 1},
                token_usage={
                    "source": "agent-sdk",
                    "total": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_creation_input_tokens": 3,
                        "cache_read_input_tokens": 2,
                        "cost_usd": 0.01,
                    },
                    "by_model": {
                        "claude-sonnet": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cost_usd": 0.01,
                        }
                    },
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="system",
                payload={"subtype": "task_completed", "total_cost_usd": 0.02},
                token_usage={
                    "source": "agent-sdk",
                    "total": {
                        "input_tokens": 20,
                        "output_tokens": 8,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "cost_usd": 0.02,
                    },
                    "by_model": {
                        "claude-sonnet": {
                            "input_tokens": 20,
                            "output_tokens": 8,
                            "cost_usd": 0.02,
                        }
                    },
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )
def make_app(tmp_path: Path, engine: FakeEngine) -> FastAPI:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    service = AgenticResearcherService(
        state_root=tmp_path,
        workspace_service=app.state.workspace_service,
        engine_factory=lambda _name: engine,
    )
    service.initialize()
    app.state.agentic_researcher_service = service
    return app


async def wait_for_status(
    client: httpx.AsyncClient,
    task_id: str,
    status: str,
) -> dict:
    payload: dict = {}
    for _ in range(20):
        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not reach {status}: {payload}")


@pytest.mark.anyio
async def test_tasks_api_create_output_stream_and_prompt(tmp_path: Path) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        workspace = app.state.workspace_service.create_workspace(
            project_id="proj-001",
            label="Task workspace",
            description=None,
            default_workdir=str(tmp_path / "workspace"),
            workspace_prompt="Use the task workspace.",
            owner_user_id=None,
        )
        create_response = await client.post(
            "/tasks",
            json={
                "project_id": "proj-001",
                "workspace_id": workspace.workspace_id,
                "environment_id": "env-001",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "title": "Smoke task",
                "prompt": "Initial prompt",
                "skills": [],
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]

        detail = await wait_for_status(client, task_id, "succeeded")
        assert detail["latest_output_seq"] == 3

        output = await client.get(f"/tasks/{task_id}/output")
        assert output.status_code == 200
        assert [item["content"] for item in output.json()["items"]] == [
            '{"role": "user", "content": "Initial prompt"}',
            '{"role": "assistant", "content": "ran: Initial prompt"}',
            '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        ]

        messages = await client.get(f"/tasks/{task_id}/messages?after_seq=0&limit=200")
        assert messages.status_code == 200
        messages_payload = messages.json()
        assert messages_payload["has_more"] is False
        assert messages_payload["next_sequence"] is None
        assert [(item["type"], item["content"]) for item in messages_payload["messages"]] == [
            ("user", "Initial prompt"),
            ("assistant", "ran: Initial prompt"),
            ("system_event", "lifecycle"),
        ]

        async with client.stream("GET", f"/tasks/{task_id}/stream?after_seq=1") as stream:
            stream_text = await stream.aread()
        decoded_stream = stream_text.decode("utf-8")
        assert "event: output" in decoded_stream
        assert '"role": "user", "content": "Initial prompt"' not in decoded_stream
        assert "event: done" in decoded_stream

        prompt_response = await client.post(
            f"/tasks/{task_id}/prompt",
            json={"prompt": "Follow up"},
        )
        assert prompt_response.status_code == 200
        assert prompt_response.json()["sequence"] == 4

        detail = await wait_for_status(client, task_id, "succeeded")
        assert detail["latest_output_seq"] == 6
        output = await client.get(f"/tasks/{task_id}/output?after_seq=4")
        assert [item["content"] for item in output.json()["items"]] == [
            '{"role": "assistant", "content": "ran: Follow up"}',
            '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        ]


@pytest.mark.anyio
async def test_task_token_usage_is_tracked_and_summarized(tmp_path: Path) -> None:
    app = make_app(tmp_path, TokenEngine())
    headers = get_jwt_headers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        workspace = app.state.workspace_service.create_workspace(
            project_id="proj-token",
            label="Token workspace",
            description=None,
            default_workdir=str(tmp_path / "workspace"),
            workspace_prompt="Track tokens.",
            owner_user_id=None,
        )
        create_response = await client.post(
            "/tasks",
            json={
                "project_id": "proj-token",
                "workspace_id": workspace.workspace_id,
                "environment_id": "env-001",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "title": "Token task",
                "prompt": "Track token usage.",
                "skills": [],
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]
        detail = await wait_for_status(client, task_id, "succeeded")

        usage = json.loads(detail["token_usage_json"])
        assert usage["source"] == "agent-sdk"
        assert usage["total"] == {
            "input_tokens": 20,
            "output_tokens": 8,
            "cache_creation_input_tokens": 4,
            "cache_read_input_tokens": 2,
            "cost_usd": 0.02,
        }
        assert usage["by_model"]["claude-sonnet"]["output_tokens"] == 8

        list_response = await client.get("/tasks?include_archived=false")
        listed = list_response.json()["items"][0]
        assert json.loads(listed["token_usage_json"])["total"]["input_tokens"] == 20

        summary_response = await client.get("/tasks/token-usage")
        assert summary_response.status_code == 200
        assert summary_response.json() == {
            "task_count": 1,
            "tasks_with_usage": 1,
            "total_tokens": 34,
            "total_cost_usd": 0.02,
            "total": {
                "input_tokens": 20,
                "output_tokens": 8,
                "cache_creation_input_tokens": 4,
                "cache_read_input_tokens": 2,
                "cost_usd": 0.02,
            },
            "by_model": {
                "claude-sonnet": {
                    "input_tokens": 20,
                    "output_tokens": 8,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cost_usd": 0.02,
                    "tokens": 28,
                }
            },
            "by_engine": {
                "claude-code": {
                    "task_count": 1,
                    "tasks_with_usage": 1,
                    "tokens": 34,
                    "cost_usd": 0.02,
                }
            },
        }


@pytest.mark.anyio
async def test_archive_succeeded_task_hides_it_from_default_list(tmp_path: Path) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        workspace = app.state.workspace_service.create_workspace(
            project_id="proj-archive",
            label="Archive workspace",
            description=None,
            default_workdir=str(tmp_path / "workspace"),
            workspace_prompt="Use the archive workspace.",
            owner_user_id=None,
        )
        create_response = await client.post(
            "/tasks",
            json={
                "project_id": "proj-archive",
                "workspace_id": workspace.workspace_id,
                "environment_id": "env-001",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "title": "Archive me",
                "prompt": "Finish then archive.",
                "skills": [],
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]
        await wait_for_status(client, task_id, "succeeded")

        archive_response = await client.delete(f"/tasks/{task_id}")
        assert archive_response.status_code == 200
        assert archive_response.json()["status"] == "cancelled"

        default_list = await client.get("/tasks?include_archived=false")
        assert task_id not in [item["task_id"] for item in default_list.json()["items"]]
        archived_list = await client.get("/tasks?include_archived=true")
        assert task_id in [item["task_id"] for item in archived_list.json()["items"]]



@pytest.mark.anyio
async def test_task_messages_normalize_wrapped_codex_events_and_drop_user_echo(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app)
    service: AgenticResearcherService = app.state.agentic_researcher_service
    workspace = app.state.workspace_service.create_workspace(
        project_id="proj-001",
        label="Task workspace",
        description=None,
        default_workdir=str(tmp_path / "workspace"),
        workspace_prompt="Use the task workspace.",
        owner_user_id=None,
    )
    task = service.create_task(
        project_id="proj-001",
        workspace_id=workspace.workspace_id,
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CODEX_APP_SERVER),
        prompt="hello codex",
        owner_user_id="user-001",
        title="hello codex",
    )
    await service.append_output(task.task_id, "message", "hello codex")
    await service.append_output(
        task.task_id,
        "message",
        '{"role": "user", "content": "tell me the time"}',
    )
    await service.append_output(task.task_id, "message", "tell me the time")
    await service.append_output(
        task.task_id,
        "tool_call",
        '{"event_type": "tool_call", "payload": {"id": "call-1", "name": "commandExecution", "arguments": {"command": "date"}}, "token_usage": null}',
    )
    await service.append_output(
        task.task_id,
        "tool_result",
        '{"event_type": "tool_result", "payload": {"tool_use_id": "call-1", "content": {"status": "failed"}, "is_error": true}, "token_usage": null}',
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        response = await client.get(f"/tasks/{task.task_id}/messages?after_seq=0&limit=200")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [(message["type"], message["content"]) for message in messages[:2]] == [
        ("user", "hello codex"),
        ("user", "tell me the time"),
    ]
    assert [message["type"] for message in messages] == [
        "user",
        "user",
        "tool_call",
        "tool_result",
    ]
    assert messages[2]["content"] == {
        "name": "commandExecution",
        "arguments": {"command": "date"},
    }
    assert messages[3]["content"] == {
        "tool_use_id": "call-1",
        "content": {"status": "failed"},
    }

@pytest.mark.anyio
async def test_task_stream_allows_query_api_key_for_eventsource(tmp_path: Path) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as authed_client:
        workspace = app.state.workspace_service.create_workspace(
            project_id="proj-001",
            label="Task workspace",
            description=None,
            default_workdir=str(tmp_path / "workspace"),
            workspace_prompt="Use the task workspace.",
            owner_user_id=None,
        )
        create_response = await authed_client.post(
            "/tasks",
            json={
                "project_id": "proj-001",
                "workspace_id": workspace.workspace_id,
                "environment_id": "env-001",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "title": "Stream task",
                "prompt": "Initial prompt",
                "skills": [],
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]
        await wait_for_status(authed_client, task_id, "succeeded")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as eventsource_client:
        async with eventsource_client.stream(
            "GET",
            f"/tasks/{task_id}/stream?after_seq=1&api_key=secret-key",
        ) as stream:
            assert stream.status_code == 200
            stream_text = await stream.aread()

    decoded_stream = stream_text.decode("utf-8")
    assert "event: output" in decoded_stream
    assert "event: done" in decoded_stream


def test_agentic_researcher_initialization_migrates_legacy_pending_status(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, FakeEngine())
    service: AgenticResearcherService = app.state.agentic_researcher_service
    workspace = app.state.workspace_service.create_workspace(
        project_id="proj-001",
        label="Task workspace",
        description=None,
        default_workdir=str(tmp_path / "workspace"),
        workspace_prompt="Use the task workspace.",
        owner_user_id=None,
    )
    task = service.create_task(
        project_id="proj-001",
        workspace_id=workspace.workspace_id,
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
        prompt="Legacy prompt",
        owner_user_id="user-001",
        title="Legacy task",
    )
    with closing(sqlite3.connect(service._db_path)) as conn:
        conn.execute("UPDATE tasks SET status = 'pending' WHERE task_id = ?", (task.task_id,))
        conn.commit()

    restarted = AgenticResearcherService(
        state_root=tmp_path,
        workspace_service=app.state.workspace_service,
        engine_factory=lambda _name: FakeEngine(),
    )
    restarted.initialize()

    migrated = restarted.get_task(task.task_id)
    assert migrated.status == TaskStatus.QUEUED


@pytest.mark.anyio
async def test_task_list_uses_fallback_workdir_for_missing_legacy_workspace(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app, user_id="user-001")
    service: AgenticResearcherService = app.state.agentic_researcher_service
    task = service.create_task(
        project_id="proj-001",
        workspace_id="default-workspace",
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
        prompt="Legacy prompt",
        owner_user_id="user-001",
        title="Legacy workspace task",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        response = await client.get("/tasks?include_archived=false&limit=200&sort=updated")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["task_id"] == task.task_id
    assert payload["items"][0]["working_directory"] == str(
        tmp_path / "workspace" / "default-workspace"
    )
    assert payload["items"][0]["command"] == [
        "claude",
        "-p",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
    ]


@pytest.mark.anyio
async def test_admin_task_lists_include_tasks_from_other_owners(tmp_path: Path) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app, username="admin-viewer", password="admin-pass")
    service: AgenticResearcherService = app.state.agentic_researcher_service
    workspace = app.state.workspace_service.create_workspace(
        project_id="proj-001",
        label="Task workspace",
        description=None,
        default_workdir=str(tmp_path / "workspace"),
        workspace_prompt="Use the task workspace.",
        owner_user_id=None,
    )
    task = service.create_task(
        project_id="proj-001",
        workspace_id=workspace.workspace_id,
        environment_id="env-001",
        researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
        prompt="Owned by another user",
        owner_user_id="other-user",
        title="Cross-owner task",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        all_tasks = await client.get("/tasks?include_archived=false&limit=200&sort=updated")
        project_tasks = await client.get(
            "/projects/proj-001/tasks?include_archived=false&limit=200&sort=updated"
        )

    assert all_tasks.status_code == 200
    assert [item["task_id"] for item in all_tasks.json()["items"]] == [task.task_id]
    assert project_tasks.status_code == 200
    assert [item["task_id"] for item in project_tasks.json()["items"]] == [task.task_id]


@pytest.mark.anyio
async def test_project_tasks_endpoint_uses_task_filters(tmp_path: Path) -> None:
    app = make_app(tmp_path, FakeEngine())
    headers = get_jwt_headers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    ) as client:
        workspace = app.state.workspace_service.create_workspace(
            project_id="proj-001",
            label="Project task workspace",
            description=None,
            default_workdir=str(tmp_path / "workspace"),
            workspace_prompt="Use the task workspace.",
            owner_user_id=None,
        )
        create_response = await client.post(
            "/tasks",
            json={
                "project_id": "proj-001",
                "workspace_id": workspace.workspace_id,
                "environment_id": "env-001",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "title": "Visible task",
                "prompt": "Visible prompt",
                "skills": [],
            },
        )
        assert create_response.status_code == 201
        owner_user_id = create_response.json()["owner_user_id"]

        service: AgenticResearcherService = app.state.agentic_researcher_service
        archived = service.create_task(
            project_id="proj-001",
            workspace_id=workspace.workspace_id,
            environment_id="env-001",
            researcher=vanilla(engine=HarnessEngineType.CLAUDE_CODE),
            prompt="Archived prompt",
            owner_user_id=owner_user_id,
            title="Archived task",
        )
        service.cancel_task(archived.task_id)

        default_response = await client.get("/projects/proj-001/tasks")
        assert default_response.status_code == 200
        assert [item["title"] for item in default_response.json()["items"]] == ["Visible task"]

        archived_response = await client.get(
            "/projects/proj-001/tasks",
            params={"include_archived": "true", "limit": "1", "sort": "created"},
        )
        assert archived_response.status_code == 200
        archived_payload = archived_response.json()
        assert archived_payload["total"] == 1
        assert archived_payload["items"][0]["project_id"] == "proj-001"
        assert archived_payload["items"][0]["workspace_id"] == workspace.workspace_id

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
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
        assert detail["latest_output_seq"] == 2

        output = await client.get(f"/tasks/{task_id}/output")
        assert output.status_code == 200
        assert [item["content"] for item in output.json()["items"]] == [
            "ran: Initial prompt",
            '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        ]

        async with client.stream("GET", f"/tasks/{task_id}/stream?after_seq=1") as stream:
            stream_text = await stream.aread()
        decoded_stream = stream_text.decode("utf-8")
        assert "event: output" in decoded_stream
        assert "ran: Initial prompt" not in decoded_stream
        assert "event: done" in decoded_stream

        prompt_response = await client.post(
            f"/tasks/{task_id}/prompt",
            json={"prompt": "Follow up"},
        )
        assert prompt_response.status_code == 200
        assert prompt_response.json()["sequence"] == 3

        detail = await wait_for_status(client, task_id, "succeeded")
        assert detail["latest_output_seq"] == 5
        output = await client.get(f"/tasks/{task_id}/output?after_seq=3")
        assert [item["content"] for item in output.json()["items"]] == [
            "ran: Follow up",
            '{"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}, "token_usage": null}',
        ]


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

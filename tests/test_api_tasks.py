from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.task_harness.launcher import LaunchPayload
from ainrf.task_harness.models import TaskHarnessStatus

API_HEADERS = {"X-API-Key": "secret-key", "X-AINRF-User-Id": "browser-user"}
_LIVE_CLAUDE_TASK_ENV = "AINRF_RUN_LIVE_CLAUDE_TASK"


class FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def read(self, _size: int) -> str:
        await asyncio.sleep(0)
        if not self._chunks:
            return ""
        return self._chunks.pop(0)


class FakeRunningProcess:
    def __init__(
        self,
        *,
        stdout_chunks: list[str] | None = None,
        stderr_chunks: list[str] | None = None,
        exit_code: int = 0,
    ) -> None:
        self.stdout = FakeStream(stdout_chunks or [])
        self.stderr = FakeStream(stderr_chunks or [])
        self._exit_code = exit_code
        self.terminated = False

    async def wait(self) -> int:
        await asyncio.sleep(0.01)
        return self._exit_code

    async def terminate(self) -> None:
        self.terminated = True

    async def kill(self) -> None:
        self.terminated = True

    async def cleanup(self) -> None:
        return None


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            terminal_command=("/bin/bash", "-l"),
        )
    )


async def wait_for_status(
    client: httpx.AsyncClient,
    task_id: str,
    expected: TaskHarnessStatus,
    *,
    attempts: int = 40,
    delay_seconds: float = 0.05,
) -> dict[str, Any]:
    for _ in range(attempts):
        response = await client.get(f"/tasks/{task_id}", headers=API_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == expected.value:
            return payload
        await asyncio.sleep(delay_seconds)
    raise AssertionError(f"Task {task_id} did not reach {expected.value}")


async def wait_for_final_status(
    client: httpx.AsyncClient,
    task_id: str,
    *,
    attempts: int = 240,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    final_statuses = {TaskHarnessStatus.SUCCEEDED.value, TaskHarnessStatus.FAILED.value}
    for _ in range(attempts):
        response = await client.get(f"/tasks/{task_id}", headers=API_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in final_statuses:
            return payload
        await asyncio.sleep(delay_seconds)
    raise AssertionError(f"Task {task_id} did not reach a final status")


@pytest.mark.anyio
async def test_task_harness_routes_create_list_detail_output_and_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="127.0.0.1",
        default_workdir="/workspace/project",
        task_harness_profile="Use the configured GPU environment.",
    )

    def fake_build_local_launcher(
        *,
        working_directory: str,
        prompt_file: Path,
        rendered_prompt: str,
        settings_path: str | None = None,
    ) -> tuple[LaunchPayload, object]:
        _ = prompt_file, rendered_prompt, settings_path
        payload = LaunchPayload(
            runner_kind="local-process",
            working_directory=working_directory,
            command=["claude", "-p"],
            prompt_file=str(prompt_file),
        )

        async def launch() -> FakeRunningProcess:
            return FakeRunningProcess(stdout_chunks=["hello\n"], stderr_chunks=["warn\n"])

        return payload, launch

    monkeypatch.setattr(
        "ainrf.task_harness.service.build_local_launcher",
        fake_build_local_launcher,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        workspaces = await client.get("/workspaces", headers=API_HEADERS)
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": "Train model\nUse three epochs.",
            },
        )

        assert workspaces.status_code == 200
        assert workspaces.json()["items"][0]["workspace_id"] == "workspace-default"
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["status"] == "queued"
        assert created["title"] == "Train model"

        detail = await wait_for_status(client, created["task_id"], TaskHarnessStatus.SUCCEEDED)
        listed = await client.get("/tasks", headers=API_HEADERS)
        output = await client.get(f"/tasks/{created['task_id']}/output", headers=API_HEADERS)
        workspace_detail = await client.get("/workspaces/workspace-default", headers=API_HEADERS)

    assert listed.status_code == 200
    assert listed.json()["items"][0]["workspace_summary"]["workspace_id"] == "workspace-default"
    assert detail["binding"]["resolved_workdir"] == str(Path.cwd())
    assert detail["prompt"]["layer_order"] == [
        "global_harness_system",
        "workspace",
        "environment",
        "task_profile",
        "task_input",
    ]
    assert detail["runtime"]["runner_kind"] == "local-process"
    assert detail["result"]["exit_code"] == 0
    assert output.status_code == 200
    assert [item["kind"] for item in output.json()["items"]] == [
        "lifecycle",
        "lifecycle",
        "lifecycle",
        "stdout",
        "stderr",
        "lifecycle",
    ]
    assert output.json()["next_seq"] == 6
    assert workspace_detail.status_code == 200
    assert workspace_detail.json()["label"] == "Repository Default"


@pytest.mark.anyio
async def test_task_harness_route_accepts_three_layer_task_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="profile-lab",
        display_name="Profile Lab",
        host="127.0.0.1",
        default_workdir="/workspace/project",
        task_harness_profile="Use the configured profile lab environment.",
    )
    recorded: dict[str, str] = {}

    def fake_build_local_launcher(
        *,
        working_directory: str,
        prompt_file: Path,
        rendered_prompt: str,
        settings_path: str,
    ) -> tuple[LaunchPayload, object]:
        _ = prompt_file, rendered_prompt
        recorded["settings_path"] = settings_path
        payload = LaunchPayload(
            runner_kind="local-process",
            working_directory=working_directory,
            command=["claude", "--settings", settings_path],
            prompt_file=str(prompt_file),
        )

        async def launch() -> FakeRunningProcess:
            return FakeRunningProcess(stdout_chunks=["structured hello\n"])

        return payload, launch

    monkeypatch.setattr(
        "ainrf.task_harness.service.build_local_launcher",
        fake_build_local_launcher,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": "ignored legacy input",
                "title": "Structured API task",
                "execution_engine": "claude-code",
                "research_agent_profile": {
                    "profile_id": "agent-literature",
                    "label": "Literature Agent",
                    "system_prompt": "Prefer careful literature synthesis.",
                    "skills_prompt": "Use citation and repo-inspection skills.",
                    "settings_json": {"permissions": {"allow": ["Read", "Grep"]}},
                },
                "task_configuration": {
                    "mode": "structured_research",
                    "template_id": "structured-research-default",
                    "template_vars": {
                        "research_goal": "Compare task harness designs",
                        "context": "AINRF runtime refactor",
                        "constraints": "Keep Claude Code as the only enabled engine",
                        "deliverables": "Architecture notes and implementation steps",
                        "validation_plan": "Run unit tests and build",
                    },
                },
            },
        )

        assert create_response.status_code == 201
        detail = await wait_for_status(
            client, create_response.json()["task_id"], TaskHarnessStatus.SUCCEEDED
        )

    assert recorded["settings_path"] == detail["research_agent_profile"]["settings_artifact_path"]
    assert detail["execution_engine"] == "claude-code"
    assert detail["research_agent_profile"]["profile_id"] == "agent-literature"
    assert detail["task_configuration"]["mode"] == "structured_research"
    assert "Compare task harness designs" in detail["task_configuration"]["rendered_task_input"]
    assert detail["binding"]["task_input"] == detail["task_configuration"]["rendered_task_input"]
    assert "research_agent_system" in detail["prompt"]["layer_order"]
    assert "research_agent_skills" in detail["prompt"]["layer_order"]
    assert detail["runtime"]["command"] == ["claude", "--settings", recorded["settings_path"]]
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="cpu-lab",
        display_name="CPU Lab",
        host="127.0.0.1",
        default_workdir="/workspace/project",
        task_harness_profile="",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": "Inspect CPU environment",
            },
        )

        assert create_response.status_code == 201
        detail = await wait_for_status(
            client, create_response.json()["task_id"], TaskHarnessStatus.FAILED
        )

    assert detail["result"]["failure_category"] == "startup failure"
    assert "profile is empty" in detail["error_summary"]


@pytest.mark.anyio
async def test_task_harness_stream_endpoint_emits_new_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="127.0.0.1",
        default_workdir="/workspace/project",
        task_harness_profile="Use the configured GPU environment.",
    )

    def fake_build_local_launcher(
        *,
        working_directory: str,
        prompt_file: Path,
        rendered_prompt: str,
        settings_path: str | None = None,
    ) -> tuple[LaunchPayload, object]:
        _ = prompt_file, rendered_prompt, settings_path
        payload = LaunchPayload(
            runner_kind="local-process",
            working_directory=working_directory,
            command=["claude", "-p"],
            prompt_file=str(prompt_file),
        )

        async def launch() -> FakeRunningProcess:
            return FakeRunningProcess(stdout_chunks=["hello\n"], stderr_chunks=[])

        return payload, launch

    monkeypatch.setattr(
        "ainrf.task_harness.service.build_local_launcher",
        fake_build_local_launcher,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": "Stream this task",
            },
        )
        task_id = create_response.json()["task_id"]
        async with client.stream(
            "GET",
            f"/tasks/{task_id}/stream?after_seq=1",
            headers=API_HEADERS,
        ) as response:
            assert response.status_code == 200
            body = ""
            async for line in response.aiter_lines():
                body += line + "\n"
                if '"kind":"stdout"' in body:
                    break

    assert '"kind":"stdout"' in body
    assert "hello\\n" in body


@pytest.mark.anyio
async def test_task_harness_remote_path_runs_without_readiness_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="ssh-lab",
        display_name="SSH Lab",
        host="gpu-server-01",
        default_workdir="/workspace/project",
        task_harness_profile="Use the configured SSH environment.",
    )
    recorded: dict[str, str] = {}
    fake_executor = object()

    def fake_build_ssh_executor(*_args: object, project_dir: str) -> object:
        recorded["project_dir"] = project_dir
        return fake_executor

    async def fake_build_remote_launcher(
        *,
        executor: object,
        task_id: str,
        local_task_dir: Path,
        working_directory: str,
        prompt_file: Path,
        settings_path: Path | None = None,
    ) -> tuple[LaunchPayload, object]:
        _ = settings_path
        assert executor is fake_executor
        assert task_id
        assert local_task_dir.exists()
        assert prompt_file.exists()
        payload = LaunchPayload(
            runner_kind="ssh-process",
            working_directory=working_directory,
            command=["/remote/launch.sh", "/remote/prompt.txt", working_directory],
            prompt_file="/remote/prompt.txt",
            helper_path="/remote/launch.sh",
        )

        async def launch() -> FakeRunningProcess:
            return FakeRunningProcess(stdout_chunks=["remote hello\n"])

        return payload, launch

    monkeypatch.setattr("ainrf.task_harness.service.build_ssh_executor", fake_build_ssh_executor)
    monkeypatch.setattr(
        "ainrf.task_harness.service.build_remote_launcher",
        fake_build_remote_launcher,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": "Run through the remote launcher path.",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        detail = await wait_for_status(client, created["task_id"], TaskHarnessStatus.SUCCEEDED)
        output = await client.get(f"/tasks/{created['task_id']}/output", headers=API_HEADERS)

    assert recorded["project_dir"] == str(Path.cwd())
    assert detail["runtime"]["runner_kind"] == "ssh-process"
    assert detail["runtime"]["helper_path"] == "/remote/launch.sh"
    assert any(item["content"] == "remote hello\n" for item in output.json()["items"])


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get(_LIVE_CLAUDE_TASK_ENV) != "1",
    reason="Set AINRF_RUN_LIVE_CLAUDE_TASK=1 to run the real Claude task smoke test",
)
async def test_task_harness_live_claude_task_output(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="live-local",
        display_name="Live Local",
        host="127.0.0.1",
        default_workdir=str(Path.cwd()),
        task_harness_profile="Use the configured localhost environment.",
    )
    marker = "HELLO_FROM_CLAUDE_TASK_20260423"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        timeout=60.0,
    ) as client:
        create_response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "task_input": (
                    f"Reply with exactly {marker} on a single line. "
                    "Do not add punctuation, explanation, or code fences."
                ),
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]
        detail = await wait_for_final_status(client, task_id)
        output = await client.get(f"/tasks/{task_id}/output", headers=API_HEADERS)

    output_items = output.json()["items"]
    combined_output = "".join(item["content"] for item in output_items)
    print(f"Live Claude task {task_id} output:\n{combined_output}")
    assert detail["status"] == TaskHarnessStatus.SUCCEEDED.value, combined_output
    assert marker in combined_output, combined_output

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.terminal.tmux import TmuxWindowInfo


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            terminal_command=("/bin/bash", "-l"),
        )
    )


def _configure_task_runtime(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    inspect_window: TmuxWindowInfo | None = None,
) -> list[str]:
    adapter = app.state.terminal_session_manager.tmux_adapter
    ensured_sessions: list[str] = []

    monkeypatch.setattr(
        adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "build_attach_command",
        lambda *args, **kwargs: ("tmux", "attach-session"),
    )
    monkeypatch.setattr(
        adapter,
        "ensure_agent_session",
        lambda binding, environment, session_name: ensured_sessions.append(session_name),
    )
    monkeypatch.setattr(
        adapter,
        "build_window_attach_command",
        lambda *args, **kwargs: (
            "tmux",
            "attach-session",
            "-t",
            "agent-session",
            ";",
            "select-window",
            "-t",
            "@1",
        ),
    )
    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: True)
    if inspect_window is not None:
        monkeypatch.setattr(
            adapter,
            "inspect_window",
            lambda *args, **kwargs: inspect_window,
        )
    return ensured_sessions


@pytest.mark.anyio
async def test_terminal_session_pairs_returns_personal_and_agent_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="127.0.0.1",
    )
    _configure_task_runtime(
        app,
        monkeypatch,
        inspect_window=TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "create_window",
        lambda *args, **kwargs: TmuxWindowInfo(window_id="@1", window_name="train-task"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        personal = await client.post(
            "/terminal/session",
            headers={"X-API-Key": "secret-key"},
            json={"environment_id": environment.id},
        )
        created = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Train Task",
                "command": "python train.py",
            },
        )
        opened = await client.post(
            f"/tasks/{created.json()['task_id']}/terminal/open",
            headers={"X-API-Key": "secret-key"},
        )
        session_pairs = await client.get(
            f"/terminal/session-pairs?environment_id={environment.id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert personal.status_code == 200
    assert created.status_code == 200
    assert opened.status_code == 200
    assert session_pairs.status_code == 200
    payload = session_pairs.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["environment_id"] == environment.id
    assert item["personal_status"] == "running"
    assert item["agent_status"] == "running"
    assert item["personal_session_name"].endswith(":personal")
    assert item["agent_session_name"].endswith(":agent")
    assert item["last_personal_attach_at"] is not None
    assert item["last_agent_attach_at"] is not None


@pytest.mark.anyio
async def test_post_tasks_ensures_agent_session_and_reuses_same_session_for_multiple_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    ensured_sessions = _configure_task_runtime(
        app,
        monkeypatch,
        inspect_window=TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
    )
    created_windows = iter(
        [
            TmuxWindowInfo(window_id="@1", window_name="train-task"),
            TmuxWindowInfo(window_id="@2", window_name="eval-task"),
        ]
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "create_window",
        lambda *args, **kwargs: next(created_windows),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Train Task",
                "command": "python train.py",
            },
        )
        second = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Eval Task",
                "command": "python eval.py",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert ensured_sessions[0].endswith(":agent")
    assert first_payload["terminal"]["agent_session_name"] == second_payload["terminal"]["agent_session_name"]
    assert first_payload["terminal"]["window_id"] != second_payload["terminal"]["window_id"]


@pytest.mark.anyio
async def test_get_tasks_and_get_task_refresh_completed_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    _configure_task_runtime(
        app,
        monkeypatch,
        inspect_window=TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "create_window",
        lambda *args, **kwargs: TmuxWindowInfo(window_id="@1", window_name="train-task"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Train Task",
                "command": "python train.py",
            },
        )

        monkeypatch.setattr(
            app.state.terminal_session_manager.tmux_adapter,
            "inspect_window",
            lambda *args, **kwargs: TmuxWindowInfo(
                window_id="@1",
                window_name="train-task",
                is_dead=True,
                exit_status=0,
            ),
        )

        listed = await client.get(
            f"/tasks?environment_id={environment.id}",
            headers={"X-API-Key": "secret-key"},
        )
        fetched = await client.get(
            f"/tasks/{created.json()['task_id']}",
            headers={"X-API-Key": "secret-key"},
        )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert listed.json()["items"][0]["status"] == "completed"
    assert listed.json()["items"][0]["terminal"]["status"] == "completed"
    assert fetched.json()["status"] == "completed"
    assert fetched.json()["exit_code"] == 0


@pytest.mark.anyio
async def test_task_terminal_open_returns_readonly_attachment_and_terminal_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="127.0.0.1",
    )
    _configure_task_runtime(
        app,
        monkeypatch,
        inspect_window=TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "create_window",
        lambda *args, **kwargs: TmuxWindowInfo(window_id="@1", window_name="train-task"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://lab.internal:5173",
    ) as client:
        created = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Train Task",
                "command": "python train.py",
            },
        )
        terminal = await client.get(
            f"/tasks/{created.json()['task_id']}/terminal",
            headers={"X-API-Key": "secret-key"},
        )
        opened = await client.post(
            f"/tasks/{created.json()['task_id']}/terminal/open",
            headers={"X-API-Key": "secret-key"},
        )

    assert terminal.status_code == 200
    assert terminal.json()["window_id"] == "@1"
    assert opened.status_code == 200
    assert opened.json()["readonly"] is True
    assert opened.json()["mode"] == "observe"
    assert opened.json()["window_id"] == "@1"
    assert opened.json()["terminal_ws_url"].startswith(
        "ws://lab.internal:5173/terminal/attachments/"
    )


@pytest.mark.anyio
async def test_task_cancel_transitions_to_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    _configure_task_runtime(
        app,
        monkeypatch,
        inspect_window=TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "create_window",
        lambda *args, **kwargs: TmuxWindowInfo(window_id="@1", window_name="train-task"),
    )
    interrupt_calls: list[str] = []
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "send_window_interrupt",
        lambda binding, env, window_id: interrupt_calls.append(window_id),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/tasks",
            headers={"X-API-Key": "secret-key"},
            json={
                "environment_id": environment.id,
                "title": "Train Task",
                "command": "python train.py",
            },
        )

        inspect_windows = iter(
            [
                TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False),
                TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=True, exit_status=130),
            ]
        )
        monkeypatch.setattr(
            app.state.terminal_session_manager.tmux_adapter,
            "inspect_window",
            lambda *args, **kwargs: next(inspect_windows),
        )

        cancelled = await client.post(
            f"/tasks/{created.json()['task_id']}/cancel",
            headers={"X-API-Key": "secret-key"},
        )

    assert cancelled.status_code == 200
    assert interrupt_calls == ["@1"]
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["terminal"]["status"] == "cancelled"

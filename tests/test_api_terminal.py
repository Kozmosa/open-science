from __future__ import annotations

from pathlib import Path
import threading
import time

import anyio
import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.terminal.tmux import TmuxCommandError

APP_USER_ID = "browser-user"
API_HEADERS = {"X-API-Key": "secret-key", "X-AINRF-User-Id": APP_USER_ID}


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            terminal_command=("/bin/bash", "-l"),
        )
    )


@pytest.mark.anyio
async def test_terminal_session_get_returns_idle_summary_for_selected_environment(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/terminal/session?environment_id={environment.id}",
            headers=API_HEADERS,
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": None,
        "provider": "tmux",
        "target_kind": "environment-ssh",
        "environment_id": environment.id,
        "environment_alias": "gpu-lab",
        "working_directory": str(tmp_path),
        "status": "idle",
        "created_at": None,
        "started_at": None,
        "closed_at": None,
        "terminal_ws_url": None,
        "detail": None,
        "binding_id": None,
        "session_name": f"ainrf:u:{APP_USER_ID}:e:{environment.id}:personal",
        "attachment_id": None,
        "attachment_expires_at": None,
    }


@pytest.mark.anyio
async def test_terminal_session_post_creates_personal_session_and_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
        default_workdir="/workspace/default",
    )
    app.state.environment_service.create_project_reference(
        project_id="default",
        environment_id=environment.id,
        override_workdir="/workspace/override",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["provider"] == "tmux"
    assert payload["target_kind"] == "environment-local"
    assert payload["environment_id"] == environment.id
    assert payload["working_directory"] == "/workspace/override"
    assert payload["status"] == "running"
    assert payload["binding_id"] is not None
    assert payload["session_name"] == (f"ainrf:u:{APP_USER_ID}:e:{environment.id}:personal")
    assert payload["attachment_id"] is not None
    assert payload["attachment_expires_at"] is not None
    assert (
        payload["terminal_ws_url"]
        == f"ws://testserver/terminal/attachments/{payload['attachment_id']}/ws?token="
        f"{app.state.terminal_attachment_broker._attachments[payload['attachment_id']].token}"
    )


@pytest.mark.anyio
async def test_terminal_session_post_returns_webui_origin_attachment_ws_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
        default_workdir="/workspace/override",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://lab.internal:5173",
    ) as client:
        response = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )

    assert response.status_code == 200
    assert response.json()["terminal_ws_url"] is not None
    ws_url = response.json()["terminal_ws_url"]
    assert ws_url.startswith("ws://lab.internal:5173/terminal/attachments/")
    assert "/ws?token=" in ws_url


@pytest.mark.anyio
async def test_terminal_session_post_reuses_same_personal_session_for_same_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: True,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )
        second = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )

    first_payload = first.json()
    second_payload = second.json()
    assert first.status_code == 200
    assert second.status_code == 200
    assert first_payload["binding_id"] == second_payload["binding_id"]
    assert first_payload["session_name"] == second_payload["session_name"]
    assert first_payload["attachment_id"] != second_payload["attachment_id"]


@pytest.mark.anyio
async def test_terminal_session_post_serializes_concurrent_attach_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        seeded = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )
        assert seeded.status_code == 200

        active_calls = 0
        max_active_calls = 0
        state_lock = threading.Lock()

        def duplicate_on_overlap(*args: object, **kwargs: object) -> None:
            nonlocal active_calls, max_active_calls
            with state_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
                overlap = active_calls > 1
            try:
                if overlap:
                    raise TmuxCommandError("duplicate session: concurrent attach")
                time.sleep(0.05)
            finally:
                with state_lock:
                    active_calls -= 1

        monkeypatch.setattr(
            app.state.terminal_session_manager._tmux_adapter,
            "ensure_personal_session",
            duplicate_on_overlap,
        )

        responses: list[httpx.Response | None] = [None, None]
        start_event = anyio.Event()

        async def attach(index: int) -> None:
            await start_event.wait()
            responses[index] = await client.post(
                "/terminal/session",
                headers=API_HEADERS,
                json={"environment_id": environment.id},
            )

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(attach, 0)
            task_group.start_soon(attach, 1)
            await anyio.sleep(0)
            start_event.set()

    first, second = responses
    assert first is not None
    assert second is not None
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["binding_id"] == second.json()["binding_id"]
    assert first.json()["session_name"] == second.json()["session_name"]
    assert first.json()["attachment_id"] != second.json()["attachment_id"]
    assert max_active_calls == 1


@pytest.mark.anyio
async def test_terminal_session_switching_environment_keeps_distinct_personal_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    first_environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    second_environment = app.state.environment_service.create_environment(
        alias="cpu-lab",
        display_name="CPU Lab",
        host="cpu.example.com",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: True,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": first_environment.id},
        )
        second = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": second_environment.id},
        )
        first_summary = await client.get(
            f"/terminal/session?environment_id={first_environment.id}",
            headers=API_HEADERS,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["binding_id"] != second.json()["binding_id"]
    assert first_summary.status_code == 200
    assert first_summary.json()["status"] == "running"
    assert first_summary.json()["environment_id"] == first_environment.id


@pytest.mark.anyio
async def test_terminal_session_delete_detaches_without_destroying_tmux_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: True,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )
        detached = await client.delete(
            f"/terminal/session?environment_id={environment.id}&attachment_id={created.json()['attachment_id']}",
            headers=API_HEADERS,
        )

    assert created.status_code == 200
    assert detached.status_code == 200
    assert detached.json()["status"] == "running"
    assert detached.json()["attachment_id"] is None
    assert detached.json()["terminal_ws_url"] is None


@pytest.mark.anyio
async def test_terminal_session_reset_returns_new_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    reset_calls: list[str] = []
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "reset_personal_session",
        lambda *args, **kwargs: reset_calls.append("reset"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": environment.id},
        )
        reset = await client.post(
            "/terminal/session/reset",
            headers=API_HEADERS,
            json={
                "environment_id": environment.id,
                "attachment_id": created.json()["attachment_id"],
            },
        )

    assert created.status_code == 200
    assert reset.status_code == 200
    assert reset_calls == ["reset"]
    assert reset.json()["attachment_id"] != created.json()["attachment_id"]
    assert reset.json()["session_name"] == created.json()["session_name"]


@pytest.mark.anyio
async def test_terminal_session_post_returns_404_for_missing_environment(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/terminal/session",
            headers=API_HEADERS,
            json={"environment_id": "missing"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Environment not found"}


@pytest.mark.anyio
async def test_terminal_session_routes_require_app_user_header(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/terminal/session?environment_id={environment.id}",
            headers={"X-API-Key": "secret-key"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required header: X-AINRF-User-Id"}

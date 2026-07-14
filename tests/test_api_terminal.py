from __future__ import annotations

from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import cast

import anyio
import httpx
import pytest
from fastapi import Request

from ainrf.api.routes.terminal import (
    create_terminal_session,
    delete_terminal_session,
    reset_terminal_session,
    terminal_session_exec,
)
from ainrf.api.schemas import (
    TerminalExecRequest,
    TerminalSessionCreateRequest,
    TerminalSessionResetRequest,
)
from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainModelMode,
    MaintenanceModeError,
)
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.tmux import TmuxCommandError
from tests.testutil import get_jwt_headers, make_terminal_app, make_terminal_manager

pytestmark = [pytest.mark.api, pytest.mark.concurrent]

APP_USER_ID = "browser-user"
# API_HEADERS constant replaced - use jwt_headers from get_jwt_headers(app)


def _maintenance_terminal_request(
    *,
    state_root: Path,
    maintenance: DomainMaintenanceService,
    manager: object,
    environment_service: object,
    broker: TerminalAttachmentBroker,
) -> Request:
    """Build the smallest request surface needed by terminal route fences.

    These regression tests call a route directly so the maintenance epoch can
    cross inside the terminal operation without the HTTP middleware's outer
    lease being part of the test fixture.  Production requests still receive
    the same 503 mapping from that middleware.
    """

    return cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    api_config=SimpleNamespace(
                        state_root=state_root,
                        domain_model_mode=DomainModelMode.LEGACY,
                    ),
                    domain_api_participant_id=None,
                    domain_maintenance_service=maintenance,
                    environment_service=environment_service,
                    terminal_attachment_broker=broker,
                    terminal_session_manager=manager,
                )
            ),
            base_url="http://testserver/",
            state=SimpleNamespace(current_user={"id": APP_USER_ID, "role": "admin"}),
        ),
    )


@pytest.mark.anyio
async def test_terminal_session_get_returns_idle_summary_for_selected_environment(
    tmp_path: Path,
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
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
        "session_name": app.state.terminal_session_manager.session_name_for(
            APP_USER_ID, environment.id
        ),
        "attachment_id": None,
        "attachment_expires_at": None,
    }


@pytest.mark.anyio
async def test_terminal_session_post_creates_personal_session_and_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
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
    assert payload["session_name"] == app.state.terminal_session_manager.session_name_for(
        APP_USER_ID, environment.id
    )
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        second = await client.post(
            "/terminal/session",
            headers=jwt_headers,
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
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
                headers=jwt_headers,
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
            json={"environment_id": first_environment.id},
        )
        second = await client.post(
            "/terminal/session",
            headers=jwt_headers,
            json={"environment_id": second_environment.id},
        )
        first_summary = await client.get(
            f"/terminal/session?environment_id={first_environment.id}",
            headers=jwt_headers,
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        detached = await client.delete(
            f"/terminal/session?environment_id={environment.id}&attachment_id={created.json()['attachment_id']}",
            headers=jwt_headers,
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
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
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
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        reset = await client.post(
            "/terminal/session/reset",
            headers=jwt_headers,
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
async def test_terminal_session_create_cleans_new_tmux_session_when_epoch_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_terminal_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    maintenance = DomainMaintenanceService(tmp_path)
    broker = TerminalAttachmentBroker()
    request = _maintenance_terminal_request(
        state_root=tmp_path,
        maintenance=maintenance,
        manager=manager,
        environment_service=environment_service,
        broker=broker,
    )
    created_sessions: list[str] = []
    killed_sessions: list[str] = []

    def create_then_enter_maintenance(*args: object, **kwargs: object) -> bool:
        _ = kwargs
        created_sessions.append(str(args[-1]))
        maintenance.enter(actor_id="operator", reason="race terminal session create")
        return True

    def record_cleanup(*args: object, **kwargs: object) -> None:
        _ = kwargs
        killed_sessions.append(str(args[-1]))

    monkeypatch.setattr(
        manager.tmux_adapter,
        "ensure_personal_session",
        create_then_enter_maintenance,
    )
    monkeypatch.setattr(manager.tmux_adapter, "kill_session", record_cleanup)
    try:
        with pytest.raises(MaintenanceModeError):
            await create_terminal_session(
                TerminalSessionCreateRequest(environment_id=environment.id),
                request,
            )
    finally:
        if maintenance.status().is_active:
            maintenance.exit(actor_id="operator")

    binding = manager._load_binding(APP_USER_ID, environment.id)
    pair = manager._load_pair(binding.binding_id) if binding is not None else None
    assert created_sessions == killed_sessions
    assert pair is not None
    assert pair.personal_status.value == "idle"
    assert broker._attachments == {}


@pytest.mark.anyio
async def test_terminal_session_create_returns_503_when_epoch_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real HTTP stack must translate a crossed terminal lease to 503."""

    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    maintenance = DomainMaintenanceService(tmp_path)
    manager = app.state.terminal_session_manager
    killed_sessions: list[str] = []

    def create_then_enter_maintenance(*args: object, **kwargs: object) -> bool:
        _ = kwargs
        maintenance.enter(actor_id="operator", reason="race terminal session create")
        return True

    def record_cleanup(*args: object, **kwargs: object) -> None:
        _ = kwargs
        killed_sessions.append(str(args[-1]))

    monkeypatch.setattr(
        manager.tmux_adapter,
        "ensure_personal_session",
        create_then_enter_maintenance,
    )
    monkeypatch.setattr(manager.tmux_adapter, "kill_session", record_cleanup)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/terminal/session",
                headers=jwt_headers,
                json={"environment_id": environment.id},
            )
    finally:
        if maintenance.status().is_active:
            maintenance.exit(actor_id="operator")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"
    assert len(killed_sessions) == 1
    assert app.state.terminal_attachment_broker._attachments == {}


@pytest.mark.anyio
async def test_terminal_session_reset_cleans_new_tmux_session_when_epoch_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_terminal_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    maintenance = DomainMaintenanceService(tmp_path)
    broker = TerminalAttachmentBroker()
    request = _maintenance_terminal_request(
        state_root=tmp_path,
        maintenance=maintenance,
        manager=manager,
        environment_service=environment_service,
        broker=broker,
    )
    created_sessions: list[str] = []
    killed_sessions: list[str] = []

    def reset_then_enter_maintenance(*args: object, **kwargs: object) -> bool:
        _ = kwargs
        created_sessions.append(str(args[-1]))
        maintenance.enter(actor_id="operator", reason="race terminal session reset")
        return True

    def record_cleanup(*args: object, **kwargs: object) -> None:
        _ = kwargs
        killed_sessions.append(str(args[-1]))

    monkeypatch.setattr(
        manager.tmux_adapter,
        "reset_personal_session",
        reset_then_enter_maintenance,
    )
    monkeypatch.setattr(manager.tmux_adapter, "kill_session", record_cleanup)
    try:
        with pytest.raises(MaintenanceModeError):
            await reset_terminal_session(
                TerminalSessionResetRequest(environment_id=environment.id),
                request,
            )
    finally:
        if maintenance.status().is_active:
            maintenance.exit(actor_id="operator")

    binding = manager._load_binding(APP_USER_ID, environment.id)
    pair = manager._load_pair(binding.binding_id) if binding is not None else None
    assert created_sessions == killed_sessions
    assert pair is not None
    assert pair.personal_status.value == "idle"
    assert broker._attachments == {}


@pytest.mark.anyio
async def test_terminal_session_delete_stops_after_epoch_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_terminal_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    maintenance = DomainMaintenanceService(tmp_path)
    broker = TerminalAttachmentBroker()
    request = _maintenance_terminal_request(
        state_root=tmp_path,
        maintenance=maintenance,
        manager=manager,
        environment_service=environment_service,
        broker=broker,
    )
    session_record_calls: list[object] = []

    def detach_then_enter_maintenance(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        maintenance.enter(actor_id="operator", reason="race terminal attachment detach")

    def unexpected_session_read(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        session_record_calls.append(object())

    monkeypatch.setattr(broker, "detach_attachment", detach_then_enter_maintenance)
    monkeypatch.setattr(manager, "get_session_record", unexpected_session_read)
    try:
        with pytest.raises(MaintenanceModeError):
            await delete_terminal_session(
                request,
                environment_id=environment.id,
                attachment_id="attachment-race",
            )
    finally:
        if maintenance.status().is_active:
            maintenance.exit(actor_id="operator")

    assert session_record_calls == []


@pytest.mark.anyio
async def test_terminal_session_exec_rejects_result_when_epoch_changes_mid_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_terminal_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    maintenance = DomainMaintenanceService(tmp_path)
    broker = TerminalAttachmentBroker()
    request = _maintenance_terminal_request(
        state_root=tmp_path,
        maintenance=maintenance,
        manager=manager,
        environment_service=environment_service,
        broker=broker,
    )
    commands: list[tuple[str, ...]] = []

    async def run_then_enter_maintenance(
        _environment: object,
        command: list[str],
        *,
        cwd: str,
        timeout: float,
    ) -> SimpleNamespace:
        _ = cwd, timeout
        commands.append(tuple(command))
        maintenance.enter(actor_id="operator", reason="race tenant command")
        return SimpleNamespace(stdout="done", stderr="", exit_code=0, command=command)

    monkeypatch.setattr("ainrf.api.routes.terminal.exec_command", run_then_enter_maintenance)
    try:
        with pytest.raises(MaintenanceModeError):
            await terminal_session_exec(
                TerminalExecRequest(environment_id=environment.id, command=["pwd"]),
                request,
            )
    finally:
        if maintenance.status().is_active:
            maintenance.exit(actor_id="operator")

    assert commands == [("pwd",)]


@pytest.mark.anyio
async def test_terminal_session_post_returns_404_for_missing_environment(tmp_path: Path) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/terminal/session",
            headers=jwt_headers,
            json={"environment_id": "missing"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Environment not found"}


@pytest.mark.anyio
async def test_terminal_session_routes_require_auth(tmp_path: Path) -> None:
    app = make_terminal_app(tmp_path)
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
            # No JWT headers — should be rejected by middleware
        )

    assert response.status_code == 401

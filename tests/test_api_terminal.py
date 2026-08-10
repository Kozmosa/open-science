from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any, cast

import anyio
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

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
    MaintenanceModeError,
)
from ainrf.auth.service import AuthService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.tmux import TmuxCommandError
from tests.testutil import get_jwt_headers, make_terminal_app, make_terminal_manager, seed_user

pytestmark = [pytest.mark.api, pytest.mark.concurrent]

APP_USER_ID = "browser-user"
# API_HEADERS constant replaced - use jwt_headers from get_jwt_headers(app)


def _create_environment(
    app: FastAPI,
    *,
    alias: str,
    display_name: str,
    host: str,
    default_workdir: str | None = None,
) -> EnvironmentRegistryEntry:
    state = app.state
    created = state.environment_module.create_environment(
        {"id": APP_USER_ID, "role": "admin"},
        alias=alias,
        display_name=display_name,
        connection={"host": host, "user": "root", "default_workdir": default_workdir},
    )
    environment_id = str(created["environment_id"])
    state.auth_service.grant_environment(
        env_id=environment_id,
        user_id=APP_USER_ID,
        max_tasks=None,
        granted_by=APP_USER_ID,
        reason="terminal route fixture execution grant",
    )
    return state.environment_service.get_environment(environment_id)


def _maintenance_terminal_request(
    *,
    state_root: Path,
    maintenance: DomainMaintenanceService,
    manager: object,
    environment_service: Any,
    broker: TerminalAttachmentBroker,
) -> Request:
    """Build the smallest request surface needed by terminal route fences.

    These regression tests call a route directly so the maintenance epoch can
    cross inside the terminal operation without the HTTP middleware's outer
    lease being part of the test fixture.  Production requests still receive
    the same 503 mapping from that middleware.
    """

    auth_service = AuthService(state_root=state_root)
    seed_user(
        auth_service,
        "browser-user",
        "terminal-password",
        role="admin",
        user_id=APP_USER_ID,
    )
    for environment in environment_service.list_environments():
        auth_service.grant_environment(
            env_id=environment.id,
            user_id=APP_USER_ID,
            max_tasks=None,
            granted_by=APP_USER_ID,
            reason="terminal maintenance fixture execution grant",
        )

    domain_reader = SimpleNamespace(
        ready=lambda: True,
        environment=lambda environment_id, _user, include_disabled=False: {
            "environment_id": environment_service.get_environment(environment_id).id,
            "status": "active",
        },
        workspace=lambda _workspace_id, _user: {},
    )
    return cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    api_config=SimpleNamespace(
                        state_root=state_root,
                    ),
                    auth_service=auth_service,
                    domain_api_participant_id=None,
                    environment_module=domain_reader,
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
    environment = _create_environment(
        app,
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/terminal/session?environment_id={environment.id}",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": None,
        "provider": "tmux",
        "target_kind": "environment-ssh",
        "environment_id": environment.id,
        "environment_alias": "gpu-lab",
        "working_directory": None,
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
async def test_terminal_runtime_surfaces_require_execution_grant_before_control_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    created = app.state.environment_module.create_environment(
        {"id": APP_USER_ID, "role": "admin"},
        alias="terminal-no-grant",
        display_name="Terminal no-grant",
        connection={"host": "127.0.0.1"},
    )
    environment_id = str(created["environment_id"])
    calls: list[str] = []

    def fail_get_session(*args: object, **kwargs: object) -> object:
        calls.append("lookup")
        raise AssertionError("terminal lookup must not reach SessionManager without a grant")

    def fail_ensure_session(*args: object, **kwargs: object) -> object:
        calls.append("create")
        raise AssertionError("terminal create must not reach tmux without a grant")

    def fail_reset_session(*args: object, **kwargs: object) -> object:
        calls.append("reset")
        raise AssertionError("terminal reset must not reach tmux without a grant")

    async def fail_exec(*args: object, **kwargs: object) -> object:
        calls.append("exec")
        raise AssertionError("terminal exec must not reach the executor without a grant")

    monkeypatch.setattr(app.state.terminal_session_manager, "get_session_record", fail_get_session)
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        fail_ensure_session,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager,
        "reset_personal_session",
        fail_reset_session,
    )
    monkeypatch.setattr("ainrf.api.routes.terminal.exec_command", fail_exec)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        lookup = await client.get(
            f"/api/terminal/session?environment_id={environment_id}", headers=jwt_headers
        )
        create = await client.post(
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": environment_id},
        )
        execute = await client.post(
            "/api/terminal/session/exec",
            headers=jwt_headers,
            json={"environment_id": environment_id, "command": ["pwd"]},
        )
        delete = await client.delete(
            f"/api/terminal/session?environment_id={environment_id}",
            headers=jwt_headers,
        )
        reset = await client.post(
            "/api/terminal/session/reset",
            headers=jwt_headers,
            json={"environment_id": environment_id},
        )

    assert lookup.status_code == 403
    assert create.status_code == 403
    assert execute.status_code == 403
    assert delete.status_code == 403
    assert reset.status_code == 403
    assert calls == []

    app.state.auth_service.grant_environment(
        env_id=environment_id,
        user_id=APP_USER_ID,
        max_tasks=None,
        granted_by=APP_USER_ID,
        reason="terminal grant transition test",
    )
    app.state.auth_service.revoke_environment(
        environment_id,
        APP_USER_ID,
        revoked_by=APP_USER_ID,
        reason="terminal grant transition test",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        revoked_lookup = await client.get(
            f"/api/terminal/session?environment_id={environment_id}", headers=jwt_headers
        )
    assert revoked_lookup.status_code == 403


@pytest.mark.anyio
async def test_terminal_session_pairs_filter_ungranted_visible_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    granted = _create_environment(
        app,
        alias="terminal-granted-pair",
        display_name="Granted pair",
        host="gpu.example.com",
    )
    hidden_record = app.state.environment_module.create_environment(
        {"id": APP_USER_ID, "role": "admin"},
        alias="terminal-hidden-pair",
        display_name="Hidden pair",
        connection={"host": "gpu-hidden.example.com"},
    )
    hidden = app.state.environment_service.get_environment(str(hidden_record["environment_id"]))
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: False,
    )
    app.state.terminal_session_manager.ensure_personal_session(APP_USER_ID, granted, None)
    app.state.terminal_session_manager.ensure_personal_session(APP_USER_ID, hidden, None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        specific_hidden = await client.get(
            f"/api/terminal/session-pairs?environment_id={hidden.id}", headers=jwt_headers
        )
        all_pairs = await client.get("/api/terminal/session-pairs", headers=jwt_headers)

    assert specific_hidden.status_code == 403
    assert all_pairs.status_code == 200
    pair_environment_ids = {item["environment_id"] for item in all_pairs.json()["items"]}
    assert granted.id in pair_environment_ids
    assert hidden.id not in pair_environment_ids


@pytest.mark.anyio
async def test_terminal_session_pairs_filter_runtime_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    environment = _create_environment(
        app,
        alias="terminal-drifting-pair",
        display_name="Drifting pair",
        host="gpu-drift.example.com",
    )
    manager = app.state.terminal_session_manager
    monkeypatch.setattr(
        manager._tmux_adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        manager._tmux_adapter,
        "has_session",
        lambda *args, **kwargs: False,
    )
    manager.ensure_personal_session(APP_USER_ID, environment, None)

    service = app.state.environment_service
    original_get_environment = service.get_environment
    target_calls = 0

    def drifting_get_environment(environment_id: str) -> EnvironmentRegistryEntry:
        nonlocal target_calls
        resolved = original_get_environment(environment_id)
        if environment_id != environment.id:
            return resolved
        target_calls += 1
        if target_calls >= 2:
            return replace(resolved, id="runtime-identity-drift")
        return resolved

    monkeypatch.setattr(service, "get_environment", drifting_get_environment)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/terminal/session-pairs", headers=jwt_headers)

    assert response.status_code == 200
    assert target_calls >= 2
    assert environment.id not in {item["environment_id"] for item in response.json()["items"]}


@pytest.mark.anyio
async def test_terminal_mutations_recheck_grant_at_external_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_terminal_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-grant-race",
        display_name="Grant race",
        host="gpu-grant-race.example.com",
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
    auth_service = request.app.state.auth_service
    external_calls: list[str] = []

    def unexpected_create(*args: object, **kwargs: object) -> object:
        external_calls.append("create")
        raise AssertionError("revoked grant must stop terminal creation")

    def unexpected_reset(*args: object, **kwargs: object) -> object:
        external_calls.append("reset")
        raise AssertionError("revoked grant must stop terminal reset")

    def unexpected_detach(*args: object, **kwargs: object) -> object:
        external_calls.append("delete")
        raise AssertionError("revoked grant must stop attachment detach")

    async def unexpected_exec(*args: object, **kwargs: object) -> object:
        external_calls.append("exec")
        raise AssertionError("revoked grant must stop tenant command")

    monkeypatch.setattr(manager, "ensure_personal_session", unexpected_create)
    monkeypatch.setattr(manager, "reset_personal_session", unexpected_reset)
    monkeypatch.setattr(broker, "detach_attachment", unexpected_detach)
    monkeypatch.setattr("ainrf.api.routes.terminal.exec_command", unexpected_exec)

    original_resolve_workdir = environment_service.resolve_effective_workdir

    def resolve_then_revoke(
        project_id: str,
        environment_id: str,
        fallback_root: Path,
    ) -> str:
        resolved = original_resolve_workdir(project_id, environment_id, fallback_root)
        auth_service.revoke_environment(
            environment.id,
            APP_USER_ID,
            revoked_by=APP_USER_ID,
            reason="terminal mutation boundary regression",
        )
        return resolved

    monkeypatch.setattr(
        environment_service,
        "resolve_effective_workdir",
        resolve_then_revoke,
    )

    async def expect_denied(operation: object) -> None:
        auth_service.grant_environment(
            env_id=environment.id,
            user_id=APP_USER_ID,
            max_tasks=None,
            granted_by=APP_USER_ID,
            reason="terminal mutation boundary regression",
        )
        with pytest.raises(HTTPException) as caught:
            await operation  # type: ignore[misc]
        assert caught.value.status_code == 403

    await expect_denied(
        create_terminal_session(
            TerminalSessionCreateRequest(environment_id=environment.id),
            request,
        )
    )
    await expect_denied(
        delete_terminal_session(
            request,
            environment_id=environment.id,
            attachment_id="attachment-grant-race",
        )
    )
    await expect_denied(
        reset_terminal_session(
            TerminalSessionResetRequest(environment_id=environment.id),
            request,
        )
    )
    await expect_denied(
        terminal_session_exec(
            TerminalExecRequest(environment_id=environment.id, command=["pwd"]),
            request,
        )
    )

    assert external_calls == []


@pytest.mark.anyio
async def test_terminal_session_post_creates_personal_session_and_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    environment = _create_environment(
        app,
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
        default_workdir="/workspace/default",
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["provider"] == "tmux"
    assert payload["target_kind"] == "environment-local"
    assert payload["environment_id"] == environment.id
    assert payload["working_directory"] == "/workspace/default"
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
    environment = _create_environment(
        app,
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
            "/api/terminal/session",
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
    environment = _create_environment(
        app,
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        second = await client.post(
            "/api/terminal/session",
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
    environment = _create_environment(
        app,
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
            "/api/terminal/session",
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
                "/api/terminal/session",
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
    first_environment = _create_environment(
        app,
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    second_environment = _create_environment(
        app,
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": first_environment.id},
        )
        second = await client.post(
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": second_environment.id},
        )
        first_summary = await client.get(
            f"/api/terminal/session?environment_id={first_environment.id}",
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
    environment = _create_environment(
        app,
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        detached = await client.delete(
            f"/api/terminal/session?environment_id={environment.id}&attachment_id={created.json()['attachment_id']}",
            headers=jwt_headers,
        )

    assert created.status_code == 200
    assert detached.status_code == 200
    assert detached.json()["status"] == "running"
    assert detached.json()["attachment_id"] is None
    assert detached.json()["terminal_ws_url"] is None


@pytest.mark.anyio
async def test_terminal_attachment_environment_identity_is_required_for_delete_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    attached_environment = _create_environment(
        app,
        alias="gpu-attached",
        display_name="Attached environment",
        host="gpu-attached.example.com",
    )
    other_environment = _create_environment(
        app,
        alias="gpu-other",
        display_name="Other environment",
        host="gpu-other.example.com",
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": attached_environment.id},
        )
        attachment_id = created.json()["attachment_id"]
        wrong_delete = await client.delete(
            "/api/terminal/session",
            params={
                "environment_id": other_environment.id,
                "attachment_id": attachment_id,
            },
            headers=jwt_headers,
        )
        wrong_reset = await client.post(
            "/api/terminal/session/reset",
            headers=jwt_headers,
            json={
                "environment_id": other_environment.id,
                "attachment_id": attachment_id,
            },
        )

    assert created.status_code == 200
    assert wrong_delete.status_code == 404
    assert wrong_reset.status_code == 404
    assert app.state.terminal_attachment_broker.get_attachment(attachment_id) is not None


@pytest.mark.anyio
async def test_terminal_session_reset_returns_new_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_terminal_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id=APP_USER_ID)
    environment = _create_environment(
        app,
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": environment.id},
        )
        reset = await client.post(
            "/api/terminal/session/reset",
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
    environment = _create_environment(
        app,
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
                "/api/terminal/session",
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
            "/api/terminal/session",
            headers=jwt_headers,
            json={"environment_id": "missing"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Environment not found"}


@pytest.mark.anyio
async def test_terminal_session_routes_require_auth(tmp_path: Path) -> None:
    app = make_terminal_app(tmp_path)
    environment = _create_environment(
        app,
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/terminal/session?environment_id={environment.id}",
            # No JWT headers — should be rejected by middleware
        )

    assert response.status_code == 401

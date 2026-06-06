from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from tests.testutil import get_jwt_headers
from ainrf.execution.errors import SSHConnectionError
from ainrf.execution.models import CommandResult
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.terminal.models import (
    TerminalAttachmentTarget,
    TerminalSessionRecord,
    TerminalSessionStatus,
    UserEnvironmentBinding,
)
from ainrf.terminal.pty import TERMINAL_LOCAL_TARGET_KIND

pytestmark = [pytest.mark.api]
# API_HEADERS constant replaced - use jwt_headers from get_jwt_headers(app)


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.anyio
async def test_environment_list_starts_empty(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    async with make_client(app) as client:
        response = await client.get("/environments", headers=jwt_headers)
        v1_response = await client.get("/v1/environments", headers=jwt_headers)

    assert response.status_code == 200
    assert [item["alias"] for item in response.json()["items"]] == ["localhost"]
    assert response.json()["items"][0]["is_seed"] is True
    assert v1_response.status_code == 200
    assert [item["alias"] for item in v1_response.json()["items"]] == ["localhost"]


@pytest.mark.anyio
async def test_environment_create_returns_saved_fields_and_null_latest_detection(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "description": "Primary CUDA environment",
        "tags": ["gpu", "research"],
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
        "auth_kind": "ssh_key",
        "identity_file": "/keys/gpu-lab",
        "proxy_jump": "bastion",
        "proxy_command": "ssh -W %h:%p bastion",
        "ssh_options": {"StrictHostKeyChecking": "no"},
        "default_workdir": "/workspace/project",
        "preferred_python": "python3.13",
        "preferred_env_manager": "uv",
        "preferred_runtime_notes": "Use CUDA 12 image",
        "task_harness_profile": "Use the configured GPU environment.",
    }

    async with make_client(app) as client:
        response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=payload,
        )

    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["id"], str)
    assert data["id"].startswith("env-")
    assert data["alias"] == payload["alias"]
    assert data["display_name"] == payload["display_name"]
    assert data["description"] == payload["description"]
    assert data["tags"] == payload["tags"]
    assert data["host"] == payload["host"]
    assert data["port"] == payload["port"]
    assert data["user"] == payload["user"]
    assert data["auth_kind"] == payload["auth_kind"]
    assert data["identity_file"] == payload["identity_file"]
    assert data["proxy_jump"] == payload["proxy_jump"]
    assert data["proxy_command"] == payload["proxy_command"]
    assert data["ssh_options"] == payload["ssh_options"]
    assert data["default_workdir"] == payload["default_workdir"]
    assert data["preferred_python"] == payload["preferred_python"]
    assert data["preferred_env_manager"] == payload["preferred_env_manager"]
    assert data["preferred_runtime_notes"] == payload["preferred_runtime_notes"]
    assert data["task_harness_profile"] == payload["task_harness_profile"]
    assert data["latest_detection"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


@pytest.mark.anyio
async def test_environment_detect_uses_ssh_probe_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[str] = []
    ensured_sessions: list[object] = []

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, timeout, cwd, env
        commands.append(command)
        return _probe_result(command)

    def fake_ensure_personal_session(*args: object, **kwargs: object) -> tuple[object, object]:
        ensured_sessions.append((args, kwargs))
        return object(), object()

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    monkeypatch.setattr(
        app.state.terminal_session_manager,
        "ensure_personal_session",
        fake_ensure_personal_session,
    )
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
        default_workdir="/workspace/project",
    )

    async with make_client(app) as client:
        response = await client.post(
            f"/environments/{environment.id}/detect",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    detection = response.json()["latest_detection"]
    assert detection["status"] == "success"
    assert detection["summary"] == "Detection completed for gpu-lab via SSH."
    assert detection["ssh_ok"] is True
    assert detection["hostname"] == "gpu-lab"
    assert detection["python"] == {
        "available": True,
        "version": "Python 3.13.0",
        "path": "/usr/bin/python3",
    }
    assert detection["claude_cli"] == {
        "available": True,
        "version": "Claude Code 1.2.3",
        "path": "/usr/local/bin/claude",
    }
    assert detection["gpu_models"] == ["NVIDIA A100"]
    assert detection["gpu_count"] == 1
    assert commands
    assert ensured_sessions == []


@pytest.mark.anyio
async def test_environment_detect_writes_back_runtime_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, timeout, cwd, env
        return _probe_result(command)

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
        default_workdir="/workspace/project",
    )

    async with make_client(app) as client:
        response = await client.post(
            f"/environments/{environment.id}/detect",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["preferred_python"] == "/usr/bin/python3"
    assert data["preferred_env_manager"] == "uv"
    assert data["latest_detection"]["codex"] == {
        "available": True,
        "version": "Codex 0.130.0",
        "path": "/usr/local/bin/codex",
    }


@pytest.mark.anyio
async def test_environment_detect_falls_back_to_personal_tmux_when_ssh_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensured: list[tuple[str, str, str | None]] = []
    tmux_commands: list[str] = []

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        raise SSHConnectionError("ssh unavailable")

    def fake_ensure_personal_session(
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        ensured.append((app_user_id, environment.id, working_directory))
        binding = UserEnvironmentBinding(
            binding_id="binding-1",
            user_id=app_user_id,
            environment_id=environment.id,
            remote_login_user=environment.user,
            default_shell="/bin/bash",
            default_workdir=working_directory,
        )
        monkeypatch.setattr(
            app.state.terminal_session_manager,
            "get_binding_by_id",
            lambda binding_id: binding if binding_id == "binding-1" else None,
        )
        record = TerminalSessionRecord(
            session_id="p-fallback",
            provider="tmux",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            status=TerminalSessionStatus.RUNNING,
            environment_id=environment.id,
            environment_alias=environment.alias,
            working_directory=working_directory,
            binding_id="binding-1",
            session_name="p-fallback",
        )
        target = TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="p-fallback",
            session_name="p-fallback",
            user_id=app_user_id,
            environment_id=environment.id,
            environment_alias=environment.alias,
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory=working_directory,
            attach_command=("tmux", "attach-session", "-t", "p-fallback"),
            spawn_working_directory=tmp_path,
        )
        return record, target

    def fake_run_bounded_session_command(
        binding: object,
        environment: object,
        session_name: str,
        *,
        command: str,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> object:
        _ = binding, environment, session_name, timeout_seconds, poll_interval_seconds
        tmux_commands.append(command)
        result = _probe_result(command)
        return SimpleNamespace(
            returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    monkeypatch.setattr(
        app.state.terminal_session_manager,
        "ensure_personal_session",
        fake_ensure_personal_session,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "run_bounded_session_command",
        fake_run_bounded_session_command,
    )
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
        default_workdir="/workspace/project",
    )

    async with make_client(app) as client:
        response = await client.post(
            f"/v1/environments/{environment.id}/detect",
            headers=jwt_headers,
        )
        detail_response = await client.get(
            f"/v1/environments/{environment.id}", headers=jwt_headers
        )

    assert response.status_code == 200
    detection = response.json()["latest_detection"]
    assert detection == detail_response.json()["latest_detection"]
    assert detection["status"] == "success"
    assert detection["summary"] == "Detection completed for gpu-lab via personal tmux fallback."
    assert detection["ssh_ok"] is False
    assert detection["warnings"] == ["ssh_unavailable", "used_personal_tmux_fallback"]
    assert detection["hostname"] == "gpu-lab"
    assert detection["uv"] == {"available": True, "version": "uv 0.5.0", "path": "/usr/bin/uv"}
    assert ensured == [("browser-user", environment.id, "/workspace/project")]
    assert tmux_commands


@pytest.mark.anyio
async def test_localhost_environment_detect_uses_personal_tmux_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensured: list[tuple[str, str, str | None]] = []
    tmux_commands: list[str] = []

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        raise AssertionError("Localhost detection should use personal tmux directly")

    def fake_ensure_personal_session(
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        ensured.append((app_user_id, environment.id, working_directory))
        binding = UserEnvironmentBinding(
            binding_id="binding-localhost",
            user_id=app_user_id,
            environment_id=environment.id,
            remote_login_user=environment.user,
            default_shell="/bin/bash",
            default_workdir=working_directory,
        )
        monkeypatch.setattr(
            app.state.terminal_session_manager,
            "get_binding_by_id",
            lambda binding_id: binding if binding_id == "binding-localhost" else None,
        )
        record = TerminalSessionRecord(
            session_id="p-localhost",
            provider="tmux",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            status=TerminalSessionStatus.RUNNING,
            environment_id=environment.id,
            environment_alias=environment.alias,
            working_directory=working_directory,
            binding_id="binding-localhost",
            session_name="p-localhost",
        )
        target = TerminalAttachmentTarget(
            binding_id="binding-localhost",
            session_id="p-localhost",
            session_name="p-localhost",
            user_id=app_user_id,
            environment_id=environment.id,
            environment_alias=environment.alias,
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory=working_directory,
            attach_command=("tmux", "attach-session", "-t", "p-localhost"),
            spawn_working_directory=tmp_path,
        )
        return record, target

    def fake_run_bounded_session_command(
        binding: object,
        environment: object,
        session_name: str,
        *,
        command: str,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> object:
        _ = binding, environment, session_name, timeout_seconds, poll_interval_seconds
        tmux_commands.append(command)
        result = _probe_result(command.replace("/workspace/projects", "/workspace/project"))
        return SimpleNamespace(
            returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    monkeypatch.setattr(
        app.state.terminal_session_manager,
        "ensure_personal_session",
        fake_ensure_personal_session,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "run_bounded_session_command",
        fake_run_bounded_session_command,
    )

    async with make_client(app) as client:
        response = await client.post(
            "/v1/environments/env-localhost/detect",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    detection = response.json()["latest_detection"]
    assert detection["status"] == "success"
    assert detection["summary"] == "Detection completed for localhost via personal tmux fallback."
    assert detection["ssh_ok"] is False
    assert detection["warnings"] == ["ssh_unavailable", "used_personal_tmux_fallback"]
    assert "localhost_seed_unreachable" not in detection["errors"]
    expected_workdir = str(Path.home() / ".ainrf_workspaces" / "default")
    assert ensured == [("browser-user", "env-localhost", expected_workdir)]
    assert tmux_commands


@pytest.mark.anyio
async def test_environment_detect_reports_missing_user_when_fallback_requires_personal_tmux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With JWT auth a user is always available, so personal tmux fallback is attempted."""
    ensured: list[tuple[str, str, str | None]] = []
    tmux_commands: list[str] = []

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        raise SSHConnectionError("ssh unavailable")

    def fake_ensure_personal_session(
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        ensured.append((app_user_id, environment.id, working_directory))
        binding = UserEnvironmentBinding(
            binding_id="binding-1",
            user_id=app_user_id,
            environment_id=environment.id,
            remote_login_user=environment.user,
            default_shell="/bin/bash",
            default_workdir=working_directory,
        )
        monkeypatch.setattr(
            app.state.terminal_session_manager,
            "get_binding_by_id",
            lambda binding_id: binding if binding_id == "binding-1" else None,
        )
        record = TerminalSessionRecord(
            session_id="p-fallback",
            provider="tmux",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            status=TerminalSessionStatus.RUNNING,
            environment_id=environment.id,
            environment_alias=environment.alias,
            working_directory=working_directory,
            binding_id="binding-1",
            session_name="p-fallback",
        )
        target = TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="p-fallback",
            session_name="p-fallback",
            user_id=app_user_id,
            environment_id=environment.id,
            environment_alias=environment.alias,
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory=working_directory,
            attach_command=("tmux", "attach-session", "-t", "p-fallback"),
            spawn_working_directory=tmp_path,
        )
        return record, target

    def fake_run_bounded_session_command(
        binding: object,
        environment: object,
        session_name: str,
        *,
        command: str,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> object:
        _ = binding, environment, session_name, timeout_seconds, poll_interval_seconds
        tmux_commands.append(command)
        result = _probe_result(command)
        return SimpleNamespace(
            returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    environment = app.state.environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
        default_workdir="/workspace/project",
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager,
        "ensure_personal_session",
        fake_ensure_personal_session,
    )
    monkeypatch.setattr(
        app.state.terminal_session_manager.tmux_adapter,
        "run_bounded_session_command",
        fake_run_bounded_session_command,
    )

    async with make_client(app) as client:
        response = await client.post(
            f"/environments/{environment.id}/detect",
            headers=jwt_headers,
        )

    assert response.status_code == 200
    detection = response.json()["latest_detection"]
    assert detection["status"] == "success"
    assert detection["summary"] == "Detection completed for gpu-lab via personal tmux fallback."
    assert detection["ssh_ok"] is False
    assert detection["warnings"] == ["ssh_unavailable", "used_personal_tmux_fallback"]
    assert detection["hostname"] == "gpu-lab"
    assert ensured == [("browser-user", environment.id, "/workspace/project")]
    assert tmux_commands


@pytest.mark.anyio
async def test_environment_lifecycle_supports_update_detect_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, timeout, cwd, env
        return _probe_result(command)

    monkeypatch.setattr("ainrf.environments.probing.SSHExecutor.run_command", fake_run_command)
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    create_payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=create_payload,
        )
        environment_id = create_response.json()["id"]

        detail_response = await client.get(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )
        update_response = await client.patch(
            f"/environments/{environment_id}",
            headers=jwt_headers,
            json={
                "display_name": "GPU Lab Updated",
                "default_workdir": "/workspace/project-a",
                "task_harness_profile": "Updated task harness profile.",
            },
        )
        detect_response = await client.post(
            f"/environments/{environment_id}/detect",
            headers=jwt_headers,
            json={},
        )
        listed_response = await client.get(
            "/v1/environments",
            headers=jwt_headers,
        )
        delete_response = await client.delete(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )
        missing_response = await client.get(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )

    assert detail_response.status_code == 200
    assert detail_response.json()["alias"] == "gpu-lab"

    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "GPU Lab Updated"
    assert update_response.json()["default_workdir"] == "/workspace/project-a"
    assert update_response.json()["task_harness_profile"] == "Updated task harness profile."

    assert detect_response.status_code == 200
    assert detect_response.json()["latest_detection"]["environment_id"] == environment_id
    assert detect_response.json()["latest_detection"]["status"] == "success"
    assert detect_response.json()["latest_detection"]["summary"] == (
        "Detection completed for gpu-lab via SSH."
    )

    assert listed_response.status_code == 200
    listed_items = listed_response.json()["items"]
    assert any(
        item["latest_detection"] is not None
        and item["latest_detection"]["environment_id"] == environment_id
        for item in listed_items
    )

    assert delete_response.status_code == 204
    assert missing_response.status_code == 404


@pytest.mark.anyio
async def test_environment_alias_conflicts_and_reference_protection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=payload,
        )
        environment_id = create_response.json()["id"]
        conflict_response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=payload,
        )

        project = app.state.project_service.create_project(
            name="Project A",
            description=None,
        )
        app.state.environment_service.upsert_project_reference(
            project_id=project.project_id,
            environment_id=environment_id,
            is_default=True,
        )
        delete_response = await client.delete(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )

    assert conflict_response.status_code == 409
    assert "alias" in conflict_response.json()["detail"].lower()
    assert delete_response.status_code == 409
    assert "referenced" in delete_response.json()["detail"].lower()


@pytest.mark.anyio
async def test_localhost_environment_is_present_and_cannot_be_deleted(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")

    async with make_client(app) as client:
        list_response = await client.get("/environments", headers=jwt_headers)
        localhost_id = list_response.json()["items"][0]["id"]
        delete_response = await client.delete(
            f"/environments/{localhost_id}",
            headers=jwt_headers,
        )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["alias"] == "localhost"
    assert delete_response.status_code == 409
    assert "cannot be deleted" in delete_response.json()["detail"].lower()


@pytest.mark.anyio
async def test_project_environment_reference_crud_and_delete_protection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    payload = {
        "alias": "gpu-lab",
        "display_name": "GPU Lab",
        "host": "gpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_environment_response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=payload,
        )
        environment_id = create_environment_response.json()["id"]

        create_reference_response = await client.post(
            "/projects/default/environment-refs",
            headers=jwt_headers,
            json={
                "environment_id": environment_id,
                "is_default": True,
                "override_workdir": "/workspace/project-a",
            },
        )
        update_reference_response = await client.patch(
            f"/projects/default/environment-refs/{environment_id}",
            headers=jwt_headers,
            json={
                "override_env_name": "research-env",
                "override_env_manager": "conda",
                "override_runtime_notes": "Prefer the project runtime image",
            },
        )
        list_reference_response = await client.get(
            "/projects/default/environment-refs",
            headers=jwt_headers,
        )
        delete_environment_response = await client.delete(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )
        delete_reference_response = await client.delete(
            f"/projects/default/environment-refs/{environment_id}",
            headers=jwt_headers,
        )
        delete_environment_after_unbind = await client.delete(
            f"/environments/{environment_id}",
            headers=jwt_headers,
        )

    assert create_reference_response.status_code == 201
    assert create_reference_response.json()["environment_id"] == environment_id
    assert create_reference_response.json()["is_default"] is True
    assert create_reference_response.json()["override_workdir"] == "/workspace/project-a"

    assert update_reference_response.status_code == 200
    assert update_reference_response.json()["override_env_name"] == "research-env"
    assert update_reference_response.json()["override_env_manager"] == "conda"
    assert (
        update_reference_response.json()["override_runtime_notes"]
        == "Prefer the project runtime image"
    )

    assert list_reference_response.status_code == 200
    assert list_reference_response.json()["items"] == [update_reference_response.json()]

    assert delete_environment_response.status_code == 409
    assert "referenced" in delete_environment_response.json()["detail"].lower()
    assert delete_reference_response.status_code == 204
    assert delete_environment_after_unbind.status_code == 204


@pytest.mark.anyio
async def test_project_environment_reference_routes_are_mirrored_under_v1(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    jwt_headers = get_jwt_headers(app, user_id="browser-user")
    payload = {
        "alias": "cpu-lab",
        "display_name": "CPU Lab",
        "host": "cpu.example.com",
        "port": 22,
        "user": "root",
    }

    async with make_client(app) as client:
        create_environment_response = await client.post(
            "/environments",
            headers=jwt_headers,
            json=payload,
        )
        environment_id = create_environment_response.json()["id"]

        create_reference_response = await client.post(
            "/v1/projects/default/environment-refs",
            headers=jwt_headers,
            json={"environment_id": environment_id},
        )
        list_reference_response = await client.get(
            "/v1/projects/default/environment-refs",
            headers=jwt_headers,
        )

    assert create_reference_response.status_code == 201
    assert create_reference_response.json()["environment_id"] == environment_id
    assert list_reference_response.status_code == 200
    assert list_reference_response.json()["items"] == [create_reference_response.json()]


def _probe_result(command: str) -> CommandResult:
    outputs = {
        "hostname": CommandResult(0, "gpu-lab\n", ""),
        "uname -s": CommandResult(0, "Linux\n", ""),
        "uname -m": CommandResult(0, "x86_64\n", ""),
        "test -d /workspace/project-a": CommandResult(0, "", ""),
        "test -d /workspace/project": CommandResult(0, "", ""),
        f"test -d {Path.home() / '.ainrf_workspaces' / 'default'}": CommandResult(0, "", ""),
        "command -v python3": CommandResult(0, "/usr/bin/python3\n", ""),
        "python3 --version": CommandResult(0, "Python 3.13.0\n", ""),
        "command -v conda": CommandResult(1, "", ""),
        "command -v uv": CommandResult(0, "/usr/bin/uv\n", ""),
        "uv --version": CommandResult(0, "uv 0.5.0\n", ""),
        "command -v pixi": CommandResult(1, "", ""),
        "command -v codex": CommandResult(0, "/usr/local/bin/codex\n", ""),
        "codex --version": CommandResult(0, "Codex 0.130.0\n", ""),
        "python3 -c 'import torch; print(torch.__version__)'": CommandResult(
            1, "", "No module named torch"
        ),
        "python3 -c 'import torch; print(torch.cuda.is_available())'": CommandResult(
            1, "", "No module named torch"
        ),
        "nvidia-smi --query-gpu=name --format=csv,noheader": CommandResult(0, "NVIDIA A100\n", ""),
        "command -v nvcc": CommandResult(1, "", ""),
        "command -v claude": CommandResult(0, "/usr/local/bin/claude\n", ""),
        "claude --version": CommandResult(0, "Claude Code 1.2.3\n", ""),
        'test -n "$ANTHROPIC_API_KEY"': CommandResult(1, "", ""),
    }
    try:
        return outputs[command]
    except KeyError as exc:
        raise AssertionError(f"unexpected probe command: {command}") from exc

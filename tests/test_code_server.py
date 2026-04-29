from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ainrf.code_server import (
    CodeServerLifecycleStatus,
    EnvironmentCodeServerManager,
    UnsupportedWorkspaceEnvironmentError,
    build_code_server_command,
    build_remote_code_server_command,
)
from ainrf.environments import EnvironmentAuthKind, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.terminal.models import (
    TerminalAttachmentTarget,
    TerminalSessionRecord,
    TerminalSessionStatus,
)
from ainrf.terminal.pty import TERMINAL_LOCAL_TARGET_KIND


class FakeProcess:
    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.actions: list[str] = []
        self.wait_timeouts: list[float] = []
        self.wait_side_effects: list[BaseException] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.actions.append("terminate")

    def kill(self) -> None:
        self.actions.append("kill")

    def wait(self, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        if self.wait_side_effects:
            raise self.wait_side_effects.pop(0)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeRemoteProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.wait_closed_calls = 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait_closed(self) -> None:
        self.wait_closed_calls += 1


class FakeTunnel:
    def __init__(self, port: int = 19090) -> None:
        self._port = port
        self.closed = False

    def get_port(self) -> int:
        return self._port

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeConnection:
    def __init__(self, process: FakeRemoteProcess, tunnel: FakeTunnel) -> None:
        self._process = process
        self._tunnel = tunnel
        self.commands: list[str] = []
        self.forward_calls: list[tuple[str, int, str, int]] = []
        self.closed = False

    async def create_process(self, command: str, **kwargs: object) -> FakeRemoteProcess:
        self.commands.append(command)
        self.process_kwargs = kwargs
        return self._process

    async def forward_local_port(
        self,
        listen_host: str,
        listen_port: int,
        dest_host: str,
        dest_port: int,
    ) -> FakeTunnel:
        self.forward_calls.append((listen_host, listen_port, dest_host, dest_port))
        return self._tunnel

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeSessionManager:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.ensure_calls: list[tuple[str, str, str | None]] = []
        self.commands: list[str] = []
        self.tmux_adapter = SimpleNamespace(
            run_bounded_session_command=self.run_bounded_session_command
        )

    def ensure_personal_session(
        self,
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        self.ensure_calls.append((app_user_id, environment.id, working_directory))
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
            spawn_working_directory=self.tmp_path,
        )
        return record, target

    def get_binding_by_id(self, binding_id: str) -> object | None:
        return object() if binding_id == "binding-localhost" else None

    def run_bounded_session_command(
        self,
        binding: object,
        environment: EnvironmentRegistryEntry,
        session_name: str,
        *,
        command: str,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> object:
        _ = binding, environment, session_name, timeout_seconds, poll_interval_seconds
        self.commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _make_manager(
    tmp_path: Path,
) -> tuple[EnvironmentCodeServerManager, InMemoryEnvironmentService]:
    service = InMemoryEnvironmentService()
    manager = EnvironmentCodeServerManager(state_root=tmp_path, environment_service=service)
    return manager, service


def test_build_code_server_command_uses_workspace_and_loopback(tmp_path: Path) -> None:
    command = build_code_server_command("127.0.0.1", 18080, tmp_path)

    assert command == [
        "code-server",
        "--bind-addr",
        "127.0.0.1:18080",
        "--auth",
        "none",
        str(tmp_path),
    ]


def test_build_code_server_command_uses_configured_executable(tmp_path: Path) -> None:
    command = build_code_server_command(
        "127.0.0.1",
        18080,
        tmp_path,
        executable_path="/home/researcher/.local/ainrf/code-server/bin/code-server",
    )

    assert command == [
        "/home/researcher/.local/ainrf/code-server/bin/code-server",
        "--bind-addr",
        "127.0.0.1:18080",
        "--auth",
        "none",
        str(tmp_path),
    ]


def test_build_remote_code_server_command_wraps_bash_login_shell() -> None:
    command = build_remote_code_server_command("/workspace/project")

    assert "bash -lc" in command
    assert "code-server" in command
    assert "127.0.0.1:18080" in command
    assert "/workspace/project" in command


def test_build_remote_code_server_command_uses_configured_executable() -> None:
    command = build_remote_code_server_command(
        "/workspace/project",
        executable_path="/home/researcher/.local/ainrf/code-server/bin/code-server",
    )

    assert "bash -lc" in command
    assert "/home/researcher/.local/ainrf/code-server/bin/code-server" in command
    assert "127.0.0.1:18080" in command
    assert "/workspace/project" in command


@pytest.mark.anyio
async def test_manager_ensure_local_environment_uses_personal_tmux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
        default_workdir="workspace/project",
        code_server_path="/home/researcher/.local/ainrf/code-server/bin/code-server",
    )
    session_manager = FakeSessionManager(tmp_path)

    def fail_popen(*args: object, **kwargs: object) -> FakeProcess:
        _ = args, kwargs
        raise AssertionError("Localhost code-server should start through personal tmux")

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = timeout_seconds
        return host == "127.0.0.1" and port == 18080

    monkeypatch.setattr(
        "ainrf.code_server.resolve_local_code_server_binary",
        lambda configured_path=None: SimpleNamespace(
            available=True,
            path=configured_path,
            detail=None,
        ),
    )
    monkeypatch.setattr("ainrf.code_server.subprocess.Popen", fail_popen)
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    first = await manager.ensure(
        environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )
    second = await manager.ensure(
        environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )

    assert session_manager.ensure_calls == [("browser-user", environment.id, "workspace/project")]
    assert len(session_manager.commands) == 1
    assert (
        "/home/researcher/.local/ainrf/code-server/bin/code-server" in session_manager.commands[0]
    )
    assert "--bind-addr 127.0.0.1:18080" in session_manager.commands[0]
    assert first.status is CodeServerLifecycleStatus.READY
    assert first.environment_id == environment.id
    assert first.workspace_dir == "workspace/project"
    assert second.status is CodeServerLifecycleStatus.READY
    assert manager.base_url == "http://127.0.0.1:18080"


@pytest.mark.anyio
async def test_manager_ensure_remote_environment_starts_tunnel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="remote-lab",
        display_name="Remote Lab",
        host="gpu.example.com",
        port=2222,
        user="researcher",
        identity_file="/keys/id_ed25519",
        default_workdir="/workspace/project",
        code_server_path="/home/researcher/.local/ainrf/code-server/bin/code-server",
    )
    remote_process = FakeRemoteProcess()
    tunnel = FakeTunnel(port=19090)
    connection = FakeConnection(remote_process, tunnel)
    captured_connect_kwargs: dict[str, object] = {}

    async def fake_connect(**kwargs: object) -> FakeConnection:
        captured_connect_kwargs.update(kwargs)
        return connection

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = timeout_seconds
        return host == "127.0.0.1" and port == 19090

    monkeypatch.setattr("ainrf.code_server.asyncssh.connect", fake_connect)
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    state = await manager.ensure(environment.id)

    assert state.status is CodeServerLifecycleStatus.READY
    assert state.environment_id == environment.id
    assert state.workspace_dir == "/workspace/project"
    assert captured_connect_kwargs["host"] == "gpu.example.com"
    assert captured_connect_kwargs["port"] == 2222
    assert captured_connect_kwargs["username"] == "researcher"
    assert captured_connect_kwargs["client_keys"] == ["/keys/id_ed25519"]
    assert connection.forward_calls == [("127.0.0.1", 0, "127.0.0.1", 18080)]
    assert connection.commands
    assert "/home/researcher/.local/ainrf/code-server/bin/code-server" in connection.commands[0]
    assert manager.base_url == "http://127.0.0.1:19090"


@pytest.mark.anyio
async def test_manager_switching_environments_tears_down_previous_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    first_environment = service.create_environment(
        alias="local-a",
        display_name="Local A",
        host="127.0.0.1",
        default_workdir="workspace/a",
    )
    second_environment = service.create_environment(
        alias="local-b",
        display_name="Local B",
        host="127.0.0.1",
        default_workdir="workspace/b",
    )
    session_manager = FakeSessionManager(tmp_path)

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = timeout_seconds
        return host == "127.0.0.1" and port == 18080

    monkeypatch.setattr(
        "ainrf.code_server.resolve_local_code_server_binary",
        lambda configured_path=None: SimpleNamespace(
            available=True,
            path="/opt/managed/code-server/bin/code-server",
            detail=None,
        ),
    )
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    first_state = await manager.ensure(
        first_environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )
    second_state = await manager.ensure(
        second_environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )

    assert first_state.environment_id == first_environment.id
    assert second_state.environment_id == second_environment.id
    assert first_state.status is CodeServerLifecycleStatus.READY
    assert second_state.status is CodeServerLifecycleStatus.READY
    assert session_manager.ensure_calls == [
        ("browser-user", first_environment.id, "workspace/a"),
        ("browser-user", second_environment.id, "workspace/b"),
    ]
    assert len(session_manager.commands) >= 3
    assert "/opt/managed/code-server/bin/code-server" in session_manager.commands[0]
    assert "workspace/a" in session_manager.commands[0]
    assert "kill" in session_manager.commands[1]
    assert "workspace/b" in session_manager.commands[-1]


@pytest.mark.anyio
async def test_tmux_code_server_stop_escalates_to_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="local-a",
        display_name="Local A",
        host="127.0.0.1",
        default_workdir="workspace/a",
    )
    session_manager = FakeSessionManager(tmp_path)

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = timeout_seconds
        return host == "127.0.0.1" and port == 18080

    monkeypatch.setattr(
        "ainrf.code_server.resolve_local_code_server_binary",
        lambda configured_path=None: SimpleNamespace(
            available=True,
            path="/opt/managed/code-server/bin/code-server",
            detail=None,
        ),
    )
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    await manager.ensure(
        environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )
    await manager.stop()

    assert any("kill -9" in command for command in session_manager.commands)


@pytest.mark.anyio
async def test_manager_reports_missing_local_code_server_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="local-a",
        display_name="Local A",
        host="127.0.0.1",
        default_workdir="workspace/a",
    )
    session_manager = FakeSessionManager(tmp_path)
    monkeypatch.setattr(
        "ainrf.code_server.resolve_local_code_server_binary",
        lambda configured_path=None: SimpleNamespace(
            available=False,
            path=None,
            detail="Install code-server.",
        ),
    )

    state = await manager.ensure(
        environment.id,
        app_user_id="browser-user",
        terminal_session_manager=session_manager,
    )

    assert state.status is CodeServerLifecycleStatus.UNAVAILABLE
    assert state.detail == "Install code-server."
    assert session_manager.ensure_calls == []
    assert session_manager.commands == []


@pytest.mark.anyio
async def test_manager_reports_missing_remote_code_server_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="remote-lab",
        display_name="Remote Lab",
        host="gpu.example.com",
        default_workdir="/workspace/project",
    )

    async def fail_connect(**kwargs: object) -> None:
        _ = kwargs
        raise AssertionError("remote code-server should not start without a resolved path")

    monkeypatch.setattr("ainrf.code_server.asyncssh.connect", fail_connect)

    state = await manager.ensure(environment.id)

    assert state.status is CodeServerLifecycleStatus.UNAVAILABLE
    assert state.detail == "Remote workspace does not have a configured code-server path"


@pytest.mark.anyio
async def test_manager_rejects_password_authenticated_workspace(
    tmp_path: Path,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="password-lab",
        display_name="Password Lab",
        host="gpu.example.com",
        auth_kind=EnvironmentAuthKind.PASSWORD,
    )

    with pytest.raises(UnsupportedWorkspaceEnvironmentError):
        await manager.ensure(environment.id)

    state = await manager.status(environment.id)
    assert state.status is CodeServerLifecycleStatus.UNAVAILABLE
    assert state.detail == "Workspace does not support password-auth environments"


@pytest.mark.anyio
async def test_manager_reports_missing_personal_tmux_context_for_localhost(
    tmp_path: Path,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="local-a",
        display_name="Local A",
        host="127.0.0.1",
        default_workdir="workspace/a",
    )

    with pytest.raises(UnsupportedWorkspaceEnvironmentError, match="personal tmux"):
        await manager.ensure(environment.id)

    state = await manager.status(environment.id)
    assert state.status is CodeServerLifecycleStatus.UNAVAILABLE
    assert "personal tmux" in (state.detail or "")

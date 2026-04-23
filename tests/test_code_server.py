from __future__ import annotations

import errno
from pathlib import Path

import pytest

from ainrf.code_server import (
    CodeServerLifecycleStatus,
    EnvironmentCodeServerManager,
    UnsupportedWorkspaceEnvironmentError,
    build_code_server_command,
    build_remote_code_server_command,
)
from ainrf.environments import EnvironmentAuthKind, InMemoryEnvironmentService


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


def test_build_remote_code_server_command_wraps_bash_login_shell() -> None:
    command = build_remote_code_server_command("/workspace/project")

    assert "bash -lc" in command
    assert "code-server" in command
    assert "127.0.0.1:18080" in command
    assert "/workspace/project" in command


@pytest.mark.anyio
async def test_manager_ensure_local_environment_reuses_existing_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, service = _make_manager(tmp_path)
    environment = service.create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
        default_workdir="workspace/project",
    )
    popen_calls: list[FakeProcess] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        _ = args, kwargs
        process = FakeProcess(pid=4321)
        popen_calls.append(process)
        return process

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = host, port, timeout_seconds
        return True

    monkeypatch.setattr("ainrf.code_server.subprocess.Popen", fake_popen)
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    first = await manager.ensure(environment.id)
    second = await manager.ensure(environment.id)

    assert len(popen_calls) == 1
    assert first.status is CodeServerLifecycleStatus.READY
    assert first.environment_id == environment.id
    assert first.workspace_dir == str(tmp_path / "workspace" / "project")
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
    assert "code-server" in connection.commands[0]
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
    first_process = FakeProcess(pid=1001)
    second_process = FakeProcess(pid=1002)
    processes = [first_process, second_process]

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        _ = args, kwargs
        return processes.pop(0)

    async def fake_wait_until_ready(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
        _ = host, port, timeout_seconds
        return True

    monkeypatch.setattr("ainrf.code_server.subprocess.Popen", fake_popen)
    monkeypatch.setattr("ainrf.code_server._wait_until_ready", fake_wait_until_ready)

    first_state = await manager.ensure(first_environment.id)
    second_state = await manager.ensure(second_environment.id)

    assert first_state.environment_id == first_environment.id
    assert second_state.environment_id == second_environment.id
    assert processes == []
    assert first_state.status is CodeServerLifecycleStatus.READY
    assert second_state.status is CodeServerLifecycleStatus.READY
    assert first_process.actions == ["terminate"]
    assert second_process.actions == []


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
async def test_manager_reports_start_failure_when_local_spawn_errors(
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

    def raise_spawn_error(*args: object, **kwargs: object) -> FakeProcess:
        _ = args, kwargs
        raise OSError(errno.ENOENT, "code-server not found")

    monkeypatch.setattr("ainrf.code_server.subprocess.Popen", raise_spawn_error)

    state = await manager.ensure(environment.id)

    assert state.status is CodeServerLifecycleStatus.UNAVAILABLE
    assert "failed to start code-server" in (state.detail or "")

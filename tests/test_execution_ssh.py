from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import pytest

from ainrf.execution import (
    CommandResult,
    CommandTimeoutError,
    ContainerConfig,
    SSHExecutor,
    UnsupportedContainerError,
)
from ainrf.execution import ssh as ssh_module


class FakeProcess:
    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        block_until_kill: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode: int | None = returncode
        self._block_until_kill = block_until_kill
        self._killed_event = asyncio.Event()
        self.terminated = False
        self.killed = False

    async def communicate(self) -> tuple[str, str]:
        if self._block_until_kill:
            await self._killed_event.wait()
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._killed_event.set()


class FakeAttrs:
    def __init__(self, size: int) -> None:
        self.size = size


class FakeSFTPClient:
    def __init__(self, remote_size: int = 0) -> None:
        self.remote_size = remote_size
        self.put_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[str, str]] = []

    async def put(self, local_path: str, remote_path: str) -> None:
        self.put_calls.append((local_path, remote_path))

    async def get(self, remote_path: str, local_path: str) -> None:
        self.get_calls.append((remote_path, local_path))

    async def stat(self, remote_path: str) -> FakeAttrs:
        _ = remote_path
        return FakeAttrs(self.remote_size)


class FakeConnection:
    def __init__(
        self,
        process_factory: Callable[[str], FakeProcess | Exception],
        sftp_client: FakeSFTPClient | None = None,
    ) -> None:
        self._process_factory = process_factory
        self._sftp_client = sftp_client or FakeSFTPClient()
        self.commands: list[str] = []
        self.closed = False

    async def create_process(self, command: str) -> FakeProcess:
        self.commands.append(command)
        outcome = self._process_factory(command)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def start_sftp_client(self) -> FakeSFTPClient:
        return self._sftp_client

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self.closed


def _container_config() -> ContainerConfig:
    return ContainerConfig(host="gpu-server-01")


def test_container_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AINRF_CONTAINER_HOST", "gpu-server-01")
    monkeypatch.setenv("AINRF_CONTAINER_PORT", "2200")
    monkeypatch.setenv("AINRF_CONTAINER_USER", "researcher")
    monkeypatch.setenv("AINRF_CONTAINER_SSH_KEY_PATH", "/tmp/id_ed25519")
    monkeypatch.setenv("AINRF_CONTAINER_PASSWORD", "secret-pass")
    monkeypatch.setenv("AINRF_CONTAINER_PROJECT_DIR", "/workspace/project-a")
    monkeypatch.setenv("AINRF_CONTAINER_CONNECT_TIMEOUT", "15")
    monkeypatch.setenv("AINRF_CONTAINER_COMMAND_TIMEOUT", "120")

    config = ContainerConfig.from_env()

    assert config.host == "gpu-server-01"
    assert config.port == 2200
    assert config.user == "researcher"
    assert config.ssh_key_path == "/tmp/id_ed25519"
    assert config.ssh_password == "secret-pass"
    assert config.project_dir == "/workspace/project-a"
    assert config.connect_timeout == 15
    assert config.command_timeout == 120


def test_run_command_wraps_bash_cwd_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(lambda _command: FakeProcess(stdout="hello\n"))

    async def fake_connect(**_: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)

    executor = SSHExecutor(_container_config())
    result = asyncio.run(
        executor.run_command("echo hello", cwd="/tmp/work", env={"A": "1", "B": "two words"})
    )

    assert result == CommandResult(exit_code=0, stdout="hello\n", stderr="")
    assert connection.commands
    remote_command = connection.commands[0]
    assert remote_command.startswith("bash -lc ")
    assert "cd /tmp/work" in remote_command
    assert "export A=1 B=" in remote_command
    assert "two words" in remote_command
    assert "echo hello" in remote_command


def test_open_connection_passes_password_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_connect(**kwargs: object) -> FakeConnection:
        captured.update(kwargs)
        return FakeConnection(lambda _command: FakeProcess())

    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)
    executor = SSHExecutor(ContainerConfig(host="gpu-server-01", ssh_password="secret-pass"))

    connection = asyncio.run(executor._open_connection())

    assert connection is not None
    assert captured["password"] == "secret-pass"


def test_run_command_reconnects_after_connection_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    first_connection = FakeConnection(lambda _command: OSError("connection lost"))
    second_connection = FakeConnection(lambda _command: FakeProcess(stdout="recovered\n"))
    connections = [first_connection, second_connection]

    async def fake_connect(**_: object) -> FakeConnection:
        return connections.pop(0)

    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)

    executor = SSHExecutor(_container_config())
    result = asyncio.run(executor.run_command("echo hello", timeout=5))

    assert result.stdout == "recovered\n"
    assert first_connection.closed is True
    assert second_connection.commands


def test_run_command_timeout_terminates_and_kills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout="partial stdout", stderr="partial stderr", block_until_kill=True)
    connection = FakeConnection(lambda _command: process)

    async def fake_connect(**_: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)
    monkeypatch.setattr(ssh_module, "_REMOTE_KILL_GRACE_SECONDS", 0)

    executor = SSHExecutor(_container_config())

    with pytest.raises(CommandTimeoutError) as excinfo:
        asyncio.run(executor.run_command("sleep 10", timeout=0.01))

    assert process.terminated is True
    assert process.killed is True
    assert excinfo.value.stdout == "partial stdout"
    assert excinfo.value.stderr == "partial stderr"


def test_upload_uses_sftp_and_creates_remote_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "artifact.txt"
    local_file.write_text("artifact", encoding="utf-8")

    executor = SSHExecutor(_container_config())
    mkdir_commands: list[str] = []
    sftp_calls: list[tuple[Path, str]] = []

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        mkdir_commands.append(cmd)
        return CommandResult(exit_code=0, stdout="", stderr="")

    async def fake_should_use_rsync(file_size: int) -> bool:
        _ = file_size
        return False

    async def fake_sftp_put(local_path: Path, remote_path: str) -> None:
        sftp_calls.append((local_path, remote_path))

    monkeypatch.setattr(executor, "run_command", fake_run_command)
    monkeypatch.setattr(executor, "_should_use_rsync", fake_should_use_rsync)
    monkeypatch.setattr(executor, "_sftp_put", fake_sftp_put)

    asyncio.run(executor.upload(local_file, "/workspace/projects/demo/artifact.txt"))

    assert mkdir_commands == ["mkdir -p /workspace/projects/demo"]
    assert sftp_calls == [(local_file, "/workspace/projects/demo/artifact.txt")]


def test_upload_prefers_rsync_for_large_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "large.bin"
    local_file.write_bytes(b"x")

    executor = SSHExecutor(_container_config())
    rsync_calls: list[tuple[Path, str, bool]] = []
    sftp_calls: list[tuple[Path, str]] = []

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        return CommandResult(exit_code=0, stdout="", stderr="")

    async def fake_should_use_rsync(file_size: int) -> bool:
        _ = file_size
        return True

    async def fake_run_local_rsync(local_path: Path, remote_path: str, upload: bool) -> None:
        rsync_calls.append((local_path, remote_path, upload))

    async def fake_sftp_put(local_path: Path, remote_path: str) -> None:
        sftp_calls.append((local_path, remote_path))

    monkeypatch.setattr(executor, "run_command", fake_run_command)
    monkeypatch.setattr(executor, "_should_use_rsync", fake_should_use_rsync)
    monkeypatch.setattr(executor, "_run_local_rsync", fake_run_local_rsync)
    monkeypatch.setattr(executor, "_sftp_put", fake_sftp_put)

    asyncio.run(executor.upload(local_file, "/workspace/projects/demo/large.bin"))

    assert rsync_calls == [(local_file, "/workspace/projects/demo/large.bin", True)]
    assert sftp_calls == []


def test_download_falls_back_to_sftp_without_rsync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = SSHExecutor(_container_config())
    sftp_calls: list[tuple[str, Path]] = []

    async def fake_remote_size(remote_path: str) -> int:
        _ = remote_path
        return ssh_module._RSYNC_TRANSFER_THRESHOLD_BYTES + 1

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        if cmd == "command -v rsync":
            return CommandResult(exit_code=1, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    async def fake_sftp_get(remote_path: str, local_path: Path) -> None:
        sftp_calls.append((remote_path, local_path))

    monkeypatch.setattr(executor, "_remote_size", fake_remote_size)
    monkeypatch.setattr(executor, "_local_rsync_available", lambda: True)
    monkeypatch.setattr(executor, "run_command", fake_run_command)
    monkeypatch.setattr(executor, "_sftp_get", fake_sftp_get)

    local_path = tmp_path / "downloads" / "artifact.txt"
    asyncio.run(executor.download("/remote/artifact.txt", local_path))

    assert sftp_calls == [("/remote/artifact.txt", local_path)]
    assert local_path.parent.exists()


def test_ensure_claude_code_installs_without_api_key_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = SSHExecutor(_container_config())
    seen_commands: list[str] = []
    claude_checks = {"count": 0}

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        seen_commands.append(cmd)
        if cmd == "command -v bash":
            return CommandResult(0, "/usr/bin/bash\n", "")
        if 'printf "%s" "$ID"' in cmd:
            return CommandResult(0, "ubuntu", "")
        if cmd in {"command -v node", "command -v npm"}:
            return CommandResult(0, f"/usr/bin/{cmd.split()[-1]}\n", "")
        if cmd == "claude --version":
            claude_checks["count"] += 1
            if claude_checks["count"] == 1:
                return CommandResult(127, "", "claude: command not found")
            return CommandResult(0, "claude 2.1.0\n", "")
        if cmd == ssh_module._CLAUDE_INSTALL_COMMAND:
            return CommandResult(0, "installed", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(executor, "run_command", fake_run_command)

    version = asyncio.run(executor.ensure_claude_code())

    assert version == "2.1.0"
    assert ssh_module._CLAUDE_INSTALL_COMMAND in seen_commands
    assert "printenv ANTHROPIC_API_KEY" not in seen_commands


def test_ensure_claude_code_rejects_unsupported_os(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = SSHExecutor(_container_config())

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        if cmd == "command -v bash":
            return CommandResult(0, "/usr/bin/bash\n", "")
        if 'printf "%s" "$ID"' in cmd:
            return CommandResult(0, "alpine", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(executor, "run_command", fake_run_command)

    with pytest.raises(UnsupportedContainerError):
        asyncio.run(executor.ensure_claude_code())


def test_ensure_claude_code_ignores_missing_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = SSHExecutor(_container_config())

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        if cmd == "command -v bash":
            return CommandResult(0, "/usr/bin/bash\n", "")
        if 'printf "%s" "$ID"' in cmd:
            return CommandResult(0, "ubuntu", "")
        if cmd in {"command -v node", "command -v npm"}:
            return CommandResult(0, "/usr/bin/bin\n", "")
        if cmd == "claude --version":
            return CommandResult(0, "claude 2.1.0\n", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(executor, "run_command", fake_run_command)

    version = asyncio.run(executor.ensure_claude_code())

    assert version == "2.1.0"


def test_ping_collects_health_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = SSHExecutor(_container_config())

    async def fake_ensure_connection(
        deadline: float,
        backoff_budget: float | None = None,
    ) -> FakeConnection:
        _ = deadline, backoff_budget
        return FakeConnection(lambda _command: FakeProcess())

    async def fake_run_command(
        cmd: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        _ = timeout, cwd, env
        if cmd == "claude --version":
            return CommandResult(0, "claude 2.1.0\n", "")
        if cmd == "nvidia-smi --query-gpu=name --format=csv,noheader":
            return CommandResult(0, "NVIDIA A100-SXM4-80GB\n", "")
        if cmd == "nvcc --version":
            return CommandResult(0, "Cuda compilation tools, release 12.4, V12.4.131", "")
        if cmd.startswith("df -B1 "):
            return CommandResult(0, "1073741824\n", "")
        if cmd.startswith("test -w "):
            return CommandResult(0, "", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(executor, "_ensure_connection", fake_ensure_connection)
    monkeypatch.setattr(executor, "run_command", fake_run_command)

    health = asyncio.run(executor.ping())

    assert health.ssh_ok is True
    assert health.claude_ok is True
    assert health.project_dir_writable is True
    assert health.claude_version == "2.1.0"
    assert health.gpu_models == ["NVIDIA A100-SXM4-80GB"]
    assert health.cuda_version == "12.4"
    assert health.disk_free_bytes == 1073741824
    assert health.warnings == []

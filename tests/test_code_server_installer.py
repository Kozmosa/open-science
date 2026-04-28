from __future__ import annotations

from types import SimpleNamespace

import pytest

from ainrf.code_server_installer import (
    CodeServerInstallError,
    CodeServerReleaseAsset,
    build_code_server_install_command,
    install_code_server,
    select_linux_amd64_asset,
)
from ainrf.execution.errors import SSHConnectionError
from ainrf.execution.models import CommandResult
from ainrf.environments import InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.terminal.models import (
    TerminalAttachmentTarget,
    TerminalSessionRecord,
    TerminalSessionStatus,
)
from ainrf.terminal.pty import TERMINAL_LOCAL_TARGET_KIND


def test_select_linux_amd64_asset_picks_tarball() -> None:
    asset = select_linux_amd64_asset(
        {
            "tag_name": "v4.117.0",
            "assets": [
                {
                    "name": "code-server-4.117.0-linux-arm64.tar.gz",
                    "browser_download_url": "https://example.invalid/arm64.tar.gz",
                },
                {
                    "name": "code-server-4.117.0-linux-amd64.tar.gz",
                    "browser_download_url": "https://example.invalid/amd64.tar.gz",
                },
            ],
        }
    )

    assert asset == CodeServerReleaseAsset(
        version="4.117.0",
        name="code-server-4.117.0-linux-amd64.tar.gz",
        download_url="https://example.invalid/amd64.tar.gz",
    )


def test_install_command_is_idempotent_and_emits_json() -> None:
    command = build_code_server_install_command(
        CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )
    )

    assert "~/.local/ainrf/code-server" in command
    assert "code-server-4.117.0-linux-amd64/bin/code-server" in command
    assert "already_installed" in command
    assert "curl -fL" in command
    assert "wget -O" in command
    assert "tar -xzf" in command


@pytest.mark.anyio
async def test_install_code_server_uses_ssh_and_records_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
    )
    commands: list[str] = []

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, timeout, cwd, env
        commands.append(command)
        return CommandResult(
            0,
            '{"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":false}\n',
            "",
        )

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fake_run_command)

    result = await install_code_server(environment.id, environment_service=service)

    assert commands
    assert result.execution_mode == "ssh"
    assert result.already_installed is False
    assert (
        result.code_server_path
        == "~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server"
    )
    assert service.get_environment(environment.id).code_server_path == result.code_server_path


@pytest.mark.anyio
async def test_install_code_server_falls_back_to_personal_tmux_when_ssh_unavailable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
        default_workdir="/workspace/project",
    )
    tmux_commands: list[str] = []

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        raise SSHConnectionError("ssh unavailable")

    class FakeSessionManager:
        def __init__(self) -> None:
            self.tmux_adapter = SimpleNamespace(
                run_bounded_session_command=self.run_bounded_session_command
            )

        def ensure_personal_session(
            self,
            app_user_id: str,
            environment: EnvironmentRegistryEntry,
            working_directory: str | None = None,
        ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
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

        def get_binding_by_id(self, binding_id: str) -> object | None:
            return object() if binding_id == "binding-1" else None

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
            tmux_commands.append(command)
            return SimpleNamespace(
                returncode=0,
                stdout='{"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":true}\n',
                stderr="",
            )

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fake_run_command)

    result = await install_code_server(
        environment.id,
        environment_service=service,
        app_user_id="browser-user",
        terminal_session_manager=FakeSessionManager(),
    )

    assert tmux_commands
    assert result.execution_mode == "personal_tmux_fallback"
    assert result.already_installed is True
    assert service.get_environment(environment.id).code_server_path == result.code_server_path


@pytest.mark.anyio
async def test_install_code_server_requires_user_for_tmux_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
    )

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        raise SSHConnectionError("ssh unavailable")

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fake_run_command)

    with pytest.raises(CodeServerInstallError, match="personal tmux fallback requires a user id"):
        await install_code_server(environment.id, environment_service=service)


@pytest.mark.anyio
async def test_install_code_server_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    service = InMemoryEnvironmentService()
    environment = service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        user="researcher",
    )

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    async def fake_run_command(
        self: object,
        command: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: object | None = None,
    ) -> CommandResult:
        _ = self, command, timeout, cwd, env
        return CommandResult(0, "not json", "")

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fake_run_command)

    with pytest.raises(CodeServerInstallError, match="invalid install output"):
        await install_code_server(environment.id, environment_service=service)

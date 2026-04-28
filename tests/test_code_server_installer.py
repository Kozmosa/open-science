from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from ainrf.code_server_installer import (
    CodeServerInstallError,
    CodeServerReleaseAsset,
    build_code_server_install_command,
    install_code_server,
    select_linux_amd64_asset,
    resolve_release_asset,
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


@pytest.mark.anyio
async def test_resolve_release_asset_uses_locked_fastgit_release_without_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_async_client(*args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise AssertionError("locked code-server version should not call GitHub API")

    monkeypatch.delenv("AINRF_CODE_SERVER_VERSION", raising=False)
    monkeypatch.setattr("ainrf.code_server_installer.httpx.AsyncClient", fail_async_client)

    asset = await resolve_release_asset()

    assert asset == CodeServerReleaseAsset(
        version="4.117.0",
        name="code-server-4.117.0-linux-amd64.tar.gz",
        download_url=(
            "https://fastgit.cc/github.com/coder/code-server/releases/download/"
            "v4.117.0/code-server-4.117.0-linux-amd64.tar.gz"
        ),
    )


@pytest.mark.anyio
async def test_resolve_release_asset_uses_configured_version_without_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_async_client(*args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise AssertionError("configured code-server version should not call GitHub API")

    monkeypatch.setenv("AINRF_CODE_SERVER_VERSION", "4.117.0")
    monkeypatch.setattr("ainrf.code_server_installer.httpx.AsyncClient", fail_async_client)

    asset = await resolve_release_asset()

    assert asset == CodeServerReleaseAsset(
        version="4.117.0",
        name="code-server-4.117.0-linux-amd64.tar.gz",
        download_url=(
            "https://fastgit.cc/github.com/coder/code-server/releases/download/"
            "v4.117.0/code-server-4.117.0-linux-amd64.tar.gz"
        ),
    )


@pytest.mark.anyio
async def test_fetch_latest_release_asset_wraps_github_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ainrf.code_server_installer import fetch_latest_release_asset

    class FakeAsyncClient:
        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def get(self, url: str, timeout: float) -> httpx.Response:
            request = httpx.Request("GET", url)
            _ = timeout
            return httpx.Response(
                403,
                request=request,
                json={"message": "rate limit exceeded"},
            )

    monkeypatch.setattr("ainrf.code_server_installer.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(CodeServerInstallError, match="GitHub rate limit exceeded"):
        await fetch_latest_release_asset()


def test_install_command_emits_json_with_sentinel() -> None:
    command = build_code_server_install_command(
        CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )
    )

    assert "__AINRF_CODE_SERVER_INSTALL_RESULT__" in command
    assert "already_installed" in command
    assert "~/.local/ainrf/code-server" in command
    assert "code-server-4.117.0-linux-amd64/bin/code-server" in command
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
        default_workdir="/workspace/project",
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
            '__AINRF_CODE_SERVER_INSTALL_RESULT__ {"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":false}\n',
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
                stdout='Downloading code-server...\n__AINRF_CODE_SERVER_INSTALL_RESULT__ {"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":true}\n',
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
async def test_install_code_server_uses_personal_tmux_directly_for_localhost(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.get_environment("env-localhost")
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
        raise AssertionError("Localhost code-server install should use personal tmux directly")

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
            tmux_commands.append(command)
            return SimpleNamespace(
                returncode=0,
                stdout='Downloading code-server...\n__AINRF_CODE_SERVER_INSTALL_RESULT__ {"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":false}\n(base) prompt$ ',
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
    assert result.already_installed is False
    assert service.get_environment("env-localhost").code_server_path == result.code_server_path


@pytest.mark.anyio
async def test_install_code_server_returns_personal_tmux_attachment_for_localhost(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.get_environment("env-localhost")

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    class FakeAttachmentBroker:
        def create_attachment(self, api_base_url: str, target: TerminalAttachmentTarget) -> object:
            _ = api_base_url
            assert target.session_name == "p-localhost"
            return SimpleNamespace(
                attachment_id="attachment-1",
                token="token-1",
                expires_at="2026-04-28T21:00:00Z",
            )

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

        def get_binding_by_id(self, binding_id: str) -> object | None:
            return object() if binding_id == "binding-localhost" else None

        def run_bounded_session_command(self, *args: object, **kwargs: object) -> object:
            _ = args, kwargs
            return SimpleNamespace(
                returncode=0,
                stdout='__AINRF_CODE_SERVER_INSTALL_RESULT__ {"version":"4.117.0","install_dir":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64","code_server_path":"~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server","already_installed":false}\n',
                stderr="",
            )

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )

    result = await install_code_server(
        environment.id,
        environment_service=service,
        app_user_id="browser-user",
        terminal_session_manager=FakeSessionManager(),
        terminal_attachment_broker=FakeAttachmentBroker(),
        api_base_url="http://testserver/",
    )

    assert result.terminal_attachment_id == "attachment-1"
    assert (
        result.terminal_ws_url
        == "ws://testserver/terminal/attachments/attachment-1/ws?token=token-1"
    )


@pytest.mark.anyio
async def test_install_code_server_requires_user_for_localhost_without_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.get_environment("env-localhost")

    async def fake_fetch_latest_release_asset() -> CodeServerReleaseAsset:
        return CodeServerReleaseAsset(
            version="4.117.0",
            name="code-server-4.117.0-linux-amd64.tar.gz",
            download_url="https://example.invalid/code-server-4.117.0-linux-amd64.tar.gz",
        )

    async def fail_ssh(*args: object, **kwargs: object) -> CommandResult:
        _ = args, kwargs
        raise AssertionError("Localhost code-server install should not try SSH")

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fail_ssh)

    with pytest.raises(CodeServerInstallError, match="localhost code-server install requires"):
        await install_code_server(environment.id, environment_service=service)


@pytest.mark.anyio
async def test_install_code_server_wraps_personal_session_setup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = InMemoryEnvironmentService()
    environment = service.get_environment("env-localhost")

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

    class BrokenSessionManager:
        tmux_adapter = SimpleNamespace()

        def ensure_personal_session(
            self,
            app_user_id: str,
            environment: EnvironmentRegistryEntry,
            working_directory: str | None = None,
        ) -> object:
            _ = app_user_id, environment, working_directory
            raise RuntimeError("tmux unavailable")

        def get_binding_by_id(self, binding_id: str) -> object | None:
            _ = binding_id
            return None

    monkeypatch.setattr(
        "ainrf.code_server_installer.fetch_latest_release_asset", fake_fetch_latest_release_asset
    )
    monkeypatch.setattr("ainrf.code_server_installer.SSHExecutor.run_command", fake_run_command)

    with pytest.raises(CodeServerInstallError, match="tmux unavailable"):
        await install_code_server(
            environment.id,
            environment_service=service,
            app_user_id="browser-user",
            terminal_session_manager=BrokenSessionManager(),
        )


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
        default_workdir="/workspace/project",
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
        default_workdir="/workspace/project",
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

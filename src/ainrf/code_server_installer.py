from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict, cast, runtime_checkable

import httpx

from ainrf.environments import InMemoryEnvironmentService
from ainrf.environments.local import is_localhost_environment
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.errors import SSHConnectionError
from ainrf.execution.models import CommandResult, ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.terminal.models import TerminalAttachmentTarget, TerminalSessionRecord
from ainrf.terminal.pty import build_attachment_ws_url
from ainrf.terminal.tmux import TmuxCommandError

_CODE_SERVER_LATEST_RELEASE_URL = "https://api.github.com/repos/coder/code-server/releases/latest"
_CODE_SERVER_RELEASE_DOWNLOAD_BASE_URL = (
    "https://fastgit.cc/github.com/coder/code-server/releases/download"
)
_CODE_SERVER_LOCKED_VERSION = "4.117.0"
_CODE_SERVER_VERSION_ENV = "AINRF_CODE_SERVER_VERSION"
_CODE_SERVER_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_INSTALL_ROOT = "~/.local/ainrf/code-server"
_INSTALL_TIMEOUT_SECONDS = 600.0
_INSTALL_RESULT_PREFIX = "__AINRF_CODE_SERVER_INSTALL_RESULT__ "

ExecutionMode = Literal["ssh", "personal_tmux_fallback"]


class CodeServerInstallError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CodeServerReleaseAsset:
    version: str
    name: str
    download_url: str


@dataclass(frozen=True, slots=True)
class CodeServerInstallResult:
    version: str
    install_dir: str
    code_server_path: str
    execution_mode: ExecutionMode
    already_installed: bool
    detail: str
    terminal_session_id: str | None = None
    terminal_attachment_id: str | None = None
    terminal_ws_url: str | None = None
    terminal_attachment_expires_at: str | None = None


class InstallOutput(TypedDict):
    version: str
    install_dir: str
    code_server_path: str
    already_installed: bool


@dataclass(frozen=True, slots=True)
class PersonalTmuxInstallResult:
    command_result: CommandResult
    record: TerminalSessionRecord
    target: TerminalAttachmentTarget


@runtime_checkable
class TerminalAttachmentBrokerLike(Protocol):
    def create_attachment(self, api_base_url: str, target: TerminalAttachmentTarget) -> Any: ...


@runtime_checkable
class SessionManagerLike(Protocol):
    tmux_adapter: Any

    def ensure_personal_session(
        self,
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None = None,
    ) -> Any: ...

    def get_binding_by_id(self, binding_id: str) -> Any | None: ...


def select_linux_amd64_asset(release: dict[str, object]) -> CodeServerReleaseAsset:
    tag_name = str(release.get("tag_name") or "")
    version = tag_name.removeprefix("v")
    assets = release.get("assets")
    if not isinstance(assets, list) or not version:
        raise CodeServerInstallError("latest code-server release metadata is invalid")

    expected_name = f"code-server-{version}-linux-amd64.tar.gz"
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        asset = cast(dict[str, object], raw_asset)
        name = str(asset.get("name") or "")
        download_url = str(asset.get("browser_download_url") or "")
        if name == expected_name and download_url:
            return CodeServerReleaseAsset(version=version, name=name, download_url=download_url)
    raise CodeServerInstallError("latest code-server release has no linux amd64 tarball")


def build_release_asset_for_version(version: str) -> CodeServerReleaseAsset:
    normalized = version.removeprefix("v")
    if not _CODE_SERVER_VERSION_PATTERN.fullmatch(normalized):
        raise CodeServerInstallError("configured code-server version is invalid")
    name = f"code-server-{normalized}-linux-amd64.tar.gz"
    return CodeServerReleaseAsset(
        version=normalized,
        name=name,
        download_url=f"{_CODE_SERVER_RELEASE_DOWNLOAD_BASE_URL}/v{normalized}/{name}",
    )


async def fetch_latest_release_asset() -> CodeServerReleaseAsset:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(_CODE_SERVER_LATEST_RELEASE_URL, timeout=30.0)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = ""
        with contextlib.suppress(Exception):
            payload = exc.response.json()
            if isinstance(payload, dict):
                message = str(payload.get("message") or "")
        if exc.response.status_code == 403 and "rate limit" in message.lower():
            raise CodeServerInstallError(
                "GitHub rate limit exceeded while fetching latest code-server release metadata"
            ) from exc
        raise CodeServerInstallError(
            f"failed to fetch latest code-server release metadata: HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise CodeServerInstallError(
            f"failed to fetch latest code-server release metadata: {exc}"
        ) from exc
    return select_linux_amd64_asset(response.json())


def build_code_server_install_command(asset: CodeServerReleaseAsset) -> str:
    install_dir = f"{_INSTALL_ROOT}/code-server-{asset.version}-linux-amd64"
    code_server_path = f"{install_dir}/bin/code-server"
    archive_path = f"{_INSTALL_ROOT}/{asset.name}"
    payload_script = "\n".join(
        [
            "set -euo pipefail",
            f"install_root={shlex.quote(_INSTALL_ROOT)}",
            f"install_dir={shlex.quote(install_dir)}",
            f"code_server_path={shlex.quote(code_server_path)}",
            f"archive_path={shlex.quote(archive_path)}",
            f"download_url={shlex.quote(asset.download_url)}",
            f"version={shlex.quote(asset.version)}",
            "already_installed=false",
            'mkdir -p "$install_root"',
            'if [ -x "$code_server_path" ]; then',
            "  already_installed=true",
            "else",
            '  tmp_archive="$archive_path.tmp"',
            "  if command -v curl >/dev/null 2>&1; then",
            '    curl -fL "$download_url" -o "$tmp_archive"',
            "  elif command -v wget >/dev/null 2>&1; then",
            '    wget -O "$tmp_archive" "$download_url"',
            "  else",
            "    echo 'curl_or_wget_required' >&2",
            "    exit 127",
            "  fi",
            '  mv "$tmp_archive" "$archive_path"',
            '  rm -rf "$install_dir"',
            '  tar -xzf "$archive_path" -C "$install_root"',
            '  test -x "$code_server_path"',
            "fi",
            f'printf \'{_INSTALL_RESULT_PREFIX}{{"version":"%s","install_dir":"%s","code_server_path":"%s","already_installed":%s}}\\n\' "$version" "$install_dir" "$code_server_path" "$already_installed"',
        ]
    )
    return f"bash -lc {shlex.quote(payload_script)}"


async def resolve_release_asset() -> CodeServerReleaseAsset:
    configured_version = os.environ.get(_CODE_SERVER_VERSION_ENV)
    return build_release_asset_for_version(configured_version or _CODE_SERVER_LOCKED_VERSION)


async def install_code_server(
    environment_id: str,
    *,
    environment_service: InMemoryEnvironmentService,
    app_user_id: str | None = None,
    terminal_session_manager: SessionManagerLike | None = None,
    terminal_attachment_broker: TerminalAttachmentBrokerLike | None = None,
    api_base_url: str | None = None,
) -> CodeServerInstallResult:
    environment = environment_service.get_environment(environment_id)
    asset = await resolve_release_asset()
    command = build_code_server_install_command(asset)
    tmux_result: PersonalTmuxInstallResult | None = None
    if is_localhost_environment(environment):
        if app_user_id is None or terminal_session_manager is None:
            raise CodeServerInstallError(
                "localhost code-server install requires a user id and terminal session manager"
            )
        tmux_result = await _run_install_over_personal_tmux(
            environment=environment,
            command=command,
            app_user_id=app_user_id,
            session_manager=terminal_session_manager,
        )
        command_result = tmux_result.command_result
        execution_mode: ExecutionMode = "personal_tmux_fallback"
    else:
        try:
            command_result = await _run_install_over_ssh(environment, command)
            execution_mode = "ssh"
        except SSHConnectionError:
            if app_user_id is None or terminal_session_manager is None:
                raise CodeServerInstallError(
                    "personal tmux fallback requires a user id and terminal session manager"
                ) from None
            tmux_result = await _run_install_over_personal_tmux(
                environment=environment,
                command=command,
                app_user_id=app_user_id,
                session_manager=terminal_session_manager,
            )
            command_result = tmux_result.command_result
            execution_mode = "personal_tmux_fallback"

    install_payload = _parse_install_output(command_result)
    environment_service.update_environment(
        environment.id,
        code_server_path=install_payload["code_server_path"],
    )
    terminal_session_id = tmux_result.record.session_id if tmux_result is not None else None
    terminal_attachment_id = None
    terminal_ws_url = None
    terminal_attachment_expires_at = None
    if (
        tmux_result is not None
        and terminal_attachment_broker is not None
        and api_base_url is not None
    ):
        attachment = terminal_attachment_broker.create_attachment(api_base_url, tmux_result.target)
        terminal_attachment_id = str(attachment.attachment_id)
        terminal_ws_url = build_attachment_ws_url(
            api_base_url,
            str(attachment.attachment_id),
            str(attachment.token),
        )
        expires_at = attachment.expires_at
        terminal_attachment_expires_at = (
            expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at)
        )
    return CodeServerInstallResult(
        version=install_payload["version"],
        install_dir=install_payload["install_dir"],
        code_server_path=install_payload["code_server_path"],
        execution_mode=execution_mode,
        already_installed=bool(install_payload["already_installed"]),
        detail="code-server installed"
        if not install_payload["already_installed"]
        else "code-server already installed",
        terminal_session_id=terminal_session_id,
        terminal_attachment_id=terminal_attachment_id,
        terminal_ws_url=terminal_ws_url,
        terminal_attachment_expires_at=terminal_attachment_expires_at,
    )


def _environment_workdir(environment: EnvironmentRegistryEntry) -> str:
    if environment.default_workdir:
        return environment.default_workdir
    raise CodeServerInstallError(
        f"Environment {environment.alias} does not define a working directory"
    )


async def _run_install_over_ssh(
    environment: EnvironmentRegistryEntry,
    command: str,
) -> CommandResult:
    container = ContainerConfig(
        host=environment.host,
        port=environment.port,
        user=environment.user,
        ssh_key_path=environment.identity_file,
        project_dir=_environment_workdir(environment),
        connect_timeout=5,
        command_timeout=int(_INSTALL_TIMEOUT_SECONDS),
    )
    executor = SSHExecutor(container)
    try:
        result = await executor.run_command(command, timeout=_INSTALL_TIMEOUT_SECONDS)
    finally:
        await executor.close()
    if result.exit_code != 0:
        raise CodeServerInstallError(result.stderr.strip() or result.stdout.strip())
    return result


async def _run_install_over_personal_tmux(
    *,
    environment: EnvironmentRegistryEntry,
    command: str,
    app_user_id: str,
    session_manager: SessionManagerLike,
) -> PersonalTmuxInstallResult:
    try:
        record, target = session_manager.ensure_personal_session(
            app_user_id,
            environment,
            environment.default_workdir,
        )
        binding = session_manager.get_binding_by_id(target.binding_id)
        if binding is None:
            raise CodeServerInstallError("Personal terminal binding was not found")
        result = await asyncio.to_thread(
            session_manager.tmux_adapter.run_bounded_session_command,
            binding,
            environment,
            target.session_name,
            command=command,
            timeout_seconds=_INSTALL_TIMEOUT_SECONDS,
        )
    except CodeServerInstallError:
        raise
    except (RuntimeError, TmuxCommandError) as exc:
        raise CodeServerInstallError(str(exc)) from exc
    if result.returncode != 0:
        raise CodeServerInstallError(result.stderr.strip() or result.stdout.strip())
    return PersonalTmuxInstallResult(
        command_result=CommandResult(result.returncode, result.stdout, result.stderr),
        record=record,
        target=target,
    )


def _parse_install_output(result: CommandResult) -> InstallOutput:
    payload_text = ""
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(_INSTALL_RESULT_PREFIX):
            payload_text = stripped.removeprefix(_INSTALL_RESULT_PREFIX)
    if not payload_text:
        raise CodeServerInstallError("invalid install output")
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise CodeServerInstallError("invalid install output") from exc
    if not isinstance(payload, dict):
        raise CodeServerInstallError("invalid install output")
    raw_payload = cast(dict[str, object], payload)
    version = raw_payload.get("version")
    install_dir = raw_payload.get("install_dir")
    code_server_path = raw_payload.get("code_server_path")
    already_installed = raw_payload.get("already_installed")
    if not isinstance(version, str) or not version:
        raise CodeServerInstallError("invalid install output")
    if not isinstance(install_dir, str) or not install_dir:
        raise CodeServerInstallError("invalid install output")
    if not isinstance(code_server_path, str) or not code_server_path:
        raise CodeServerInstallError("invalid install output")
    if not isinstance(already_installed, bool):
        raise CodeServerInstallError("invalid install output")
    return {
        "version": version,
        "install_dir": install_dir,
        "code_server_path": code_server_path,
        "already_installed": already_installed,
    }

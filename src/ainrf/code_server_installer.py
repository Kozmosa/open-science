from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, cast, runtime_checkable

import httpx

from ainrf.environments import InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.errors import SSHConnectionError
from ainrf.execution.models import CommandResult, ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.terminal.tmux import TmuxCommandError

_CODE_SERVER_LATEST_RELEASE_URL = "https://api.github.com/repos/coder/code-server/releases/latest"
_INSTALL_ROOT = "~/.local/ainrf/code-server"
_INSTALL_TIMEOUT_SECONDS = 600.0

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


class InstallOutput(TypedDict):
    version: str
    install_dir: str
    code_server_path: str
    already_installed: bool


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


async def fetch_latest_release_asset() -> CodeServerReleaseAsset:
    async with httpx.AsyncClient() as client:
        response = await client.get(_CODE_SERVER_LATEST_RELEASE_URL, timeout=30.0)
        response.raise_for_status()
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
            'printf \'{"version":"%s","install_dir":"%s","code_server_path":"%s","already_installed":%s}\\n\' "$version" "$install_dir" "$code_server_path" "$already_installed"',
        ]
    )
    return f"bash -lc {shlex.quote(payload_script)}"


async def install_code_server(
    environment_id: str,
    *,
    environment_service: InMemoryEnvironmentService,
    app_user_id: str | None = None,
    terminal_session_manager: SessionManagerLike | None = None,
) -> CodeServerInstallResult:
    environment = environment_service.get_environment(environment_id)
    asset = await fetch_latest_release_asset()
    command = build_code_server_install_command(asset)
    try:
        command_result = await _run_install_over_ssh(environment, command)
        execution_mode: ExecutionMode = "ssh"
    except SSHConnectionError:
        if app_user_id is None or terminal_session_manager is None:
            raise CodeServerInstallError(
                "personal tmux fallback requires a user id and terminal session manager"
            ) from None
        command_result = await _run_install_over_personal_tmux(
            environment=environment,
            command=command,
            app_user_id=app_user_id,
            session_manager=terminal_session_manager,
        )
        execution_mode = "personal_tmux_fallback"

    install_payload = _parse_install_output(command_result)
    environment_service.update_environment(
        environment.id,
        code_server_path=install_payload["code_server_path"],
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
        project_dir=environment.default_workdir or "/workspace/projects",
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
) -> CommandResult:
    _record, target = session_manager.ensure_personal_session(
        app_user_id,
        environment,
        environment.default_workdir,
    )
    binding = session_manager.get_binding_by_id(target.binding_id)
    if binding is None:
        raise CodeServerInstallError("Personal terminal binding was not found")
    try:
        result = await asyncio.to_thread(
            session_manager.tmux_adapter.run_bounded_session_command,
            binding,
            environment,
            target.session_name,
            command=command,
            timeout_seconds=_INSTALL_TIMEOUT_SECONDS,
        )
    except (RuntimeError, TmuxCommandError) as exc:
        raise CodeServerInstallError(str(exc)) from exc
    if result.returncode != 0:
        raise CodeServerInstallError(result.stderr.strip() or result.stdout.strip())
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _parse_install_output(result: CommandResult) -> InstallOutput:
    last_line = ""
    for line in result.stdout.splitlines():
        if line.strip():
            last_line = line.strip()
    try:
        payload = json.loads(last_line)
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

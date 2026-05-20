from __future__ import annotations

import asyncio
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ainrf.environments.local import is_localhost_environment
from ainrf.environments.models import (
    AnthropicEnvStatus,
    DetectionSnapshot,
    DetectionStatus,
    EnvironmentRegistryEntry,
    ToolStatus,
    utc_now,
)
from ainrf.execution.errors import SSHConnectionError
from ainrf.execution.models import CommandResult, ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.terminal.tmux import TmuxCommandError

if TYPE_CHECKING:
    from ainrf.terminal.sessions import SessionManager

ProbeCommandRunner = Callable[[str], Awaitable[CommandResult]]


@dataclass(slots=True)
class EnvironmentProbeOutcome:
    snapshot: DetectionSnapshot
    ssh_unavailable: bool = False


_LOCALHOST_SSH_ATTEMPTS = 3
_LOCALHOST_SSH_CONNECT_TIMEOUT_SECONDS = 1
_PROBE_COMMAND_TIMEOUT_SECONDS = 30.0


def _environment_workdir(environment: EnvironmentRegistryEntry) -> str:
    if environment.default_workdir:
        return environment.default_workdir
    raise ValueError(f"Environment {environment.alias} does not define a working directory")


def _ssh_container_for(environment: EnvironmentRegistryEntry) -> ContainerConfig:
    return ContainerConfig(
        host=environment.host,
        port=environment.port,
        user=environment.user,
        ssh_key_path=environment.identity_file,
        project_dir=_environment_workdir(environment),
        connect_timeout=5,
        command_timeout=30,
    )


async def probe_with_ssh(environment: EnvironmentRegistryEntry) -> EnvironmentProbeOutcome:
    if is_localhost_environment(environment):
        return await _probe_localhost_with_ssh(environment)

    container = _ssh_container_for(environment)
    executor = SSHExecutor(container)
    try:
        snapshot = await build_detection_snapshot(
            environment,
            lambda command: executor.run_command(command, timeout=_PROBE_COMMAND_TIMEOUT_SECONDS),
            ssh_ok=True,
            summary=f"Detection completed for {environment.alias} via SSH.",
        )
        return EnvironmentProbeOutcome(snapshot=snapshot)
    except SSHConnectionError:
        raise
    finally:
        await executor.close()


async def _probe_localhost_with_ssh(
    environment: EnvironmentRegistryEntry,
) -> EnvironmentProbeOutcome:
    last_error: SSHConnectionError | None = None
    for _attempt in range(_LOCALHOST_SSH_ATTEMPTS):
        container = _ssh_container_for(environment)
        container.connect_timeout = _LOCALHOST_SSH_CONNECT_TIMEOUT_SECONDS
        executor = SSHExecutor(container)
        try:
            snapshot = await build_detection_snapshot(
                environment,
                lambda command: executor.run_command(
                    command,
                    timeout=_LOCALHOST_SSH_CONNECT_TIMEOUT_SECONDS,
                ),
                ssh_ok=True,
                summary=f"Detection completed for {environment.alias} via SSH.",
            )
            return EnvironmentProbeOutcome(snapshot=snapshot)
        except SSHConnectionError as exc:
            last_error = exc
        finally:
            await executor.close()
    raise last_error or SSHConnectionError("localhost SSH unavailable")


async def probe_with_personal_tmux(
    *,
    environment: EnvironmentRegistryEntry,
    app_user_id: str,
    session_manager: SessionManager,
) -> EnvironmentProbeOutcome:
    working_directory = environment.default_workdir
    if is_localhost_environment(environment) and working_directory is not None:
        workdir_check = await asyncio.to_thread(Path(working_directory).is_dir)
        if not workdir_check:
            working_directory = None
    _record, target = session_manager.ensure_personal_session(
        app_user_id,
        environment,
        working_directory,
    )
    binding = session_manager.get_binding_by_id(target.binding_id)
    if binding is None:
        raise RuntimeError("Personal terminal binding was not found")

    async def run_command(command: str) -> CommandResult:
        result = await asyncio.to_thread(
            session_manager.tmux_adapter.run_bounded_session_command,
            binding,
            environment,
            target.session_name,
            command=command,
            timeout_seconds=30.0,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)

    snapshot = await build_detection_snapshot(
        environment,
        run_command,
        ssh_ok=False,
        summary=f"Detection completed for {environment.alias} via personal tmux fallback.",
        warnings=["ssh_unavailable", "used_personal_tmux_fallback"],
    )
    return EnvironmentProbeOutcome(snapshot=snapshot, ssh_unavailable=True)


async def build_detection_snapshot(
    environment: EnvironmentRegistryEntry,
    run_command: ProbeCommandRunner,
    *,
    ssh_ok: bool,
    summary: str,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> DetectionSnapshot:
    preferred_python = environment.preferred_python or "python3"
    hostname = (await run_command("hostname")).stdout.strip() or environment.host
    os_info = (await run_command("uname -s")).stdout.strip() or None
    arch = (await run_command("uname -m")).stdout.strip() or None
    workdir = _environment_workdir(environment)
    workdir_result = await run_command(f"test -d {shlex.quote(workdir)}")
    python = await _probe_tool(run_command, preferred_python, f"{preferred_python} --version")
    conda = await _probe_tool(run_command, "conda", "conda --version")
    uv = await _probe_tool(run_command, "uv", "uv --version")
    pixi = await _probe_tool(run_command, "pixi", "pixi --version")
    codex = await _probe_codex(run_command)
    torch = await _probe_python_package(run_command, preferred_python, "torch")
    cuda = await _probe_cuda(run_command)
    gpu_models_result = await run_command("nvidia-smi --query-gpu=name --format=csv,noheader")
    gpu_models = [line.strip() for line in gpu_models_result.stdout.splitlines() if line.strip()]
    claude_cli = await _probe_tool(run_command, "claude", "claude --version")
    anthropic_env_result = await run_command('test -n "$ANTHROPIC_API_KEY"')

    return DetectionSnapshot(
        environment_id=environment.id,
        detected_at=utc_now(),
        status=DetectionStatus.SUCCESS,
        summary=summary,
        errors=list(errors or []),
        warnings=list(warnings or []),
        tmux_ok=ssh_ok,
        ssh_ok=ssh_ok,
        hostname=hostname,
        os_info=os_info,
        arch=arch,
        workdir_exists=workdir_result.exit_code == 0,
        python=python,
        conda=conda,
        uv=uv,
        pixi=pixi,
        codex=codex,
        torch=torch,
        cuda=cuda,
        gpu_models=gpu_models,
        gpu_count=len(gpu_models),
        claude_cli=claude_cli,
        anthropic_env=AnthropicEnvStatus.PRESENT
        if anthropic_env_result.exit_code == 0
        else AnthropicEnvStatus.MISSING,
    )


def failed_missing_user_snapshot(
    environment: EnvironmentRegistryEntry,
) -> DetectionSnapshot:
    return DetectionSnapshot(
        environment_id=environment.id,
        detected_at=utc_now(),
        status=DetectionStatus.FAILED,
        summary=(
            f"Detection failed for {environment.alias} because SSH is unavailable and no user "
            "session is available."
        ),
        errors=["ssh_unavailable", "missing_app_user_id"],
        warnings=["ssh_unavailable"],
        ssh_ok=False,
        hostname=environment.host,
    )


def failed_tmux_snapshot(
    environment: EnvironmentRegistryEntry,
    exc: Exception,
) -> DetectionSnapshot:
    return DetectionSnapshot(
        environment_id=environment.id,
        detected_at=utc_now(),
        status=DetectionStatus.FAILED,
        summary=f"Detection failed for {environment.alias} via personal tmux fallback.",
        errors=["ssh_unavailable", "personal_tmux_fallback_failed"],
        warnings=["ssh_unavailable"],
        ssh_ok=False,
        hostname=environment.host,
        os_info=str(exc),
    )


async def _probe_tool(
    run_command: ProbeCommandRunner,
    binary: str,
    version_command: str,
) -> ToolStatus:
    path_result = await run_command(f"command -v {shlex.quote(binary)}")
    if path_result.exit_code != 0:
        return ToolStatus(available=False)
    path = path_result.stdout.strip() or None
    version_result = await run_command(version_command)
    version = (version_result.stdout or version_result.stderr).strip() or None
    return ToolStatus(available=True, version=version, path=path)


async def _probe_codex(runner: ProbeCommandRunner) -> ToolStatus:
    return await _probe_tool(runner, "codex", "codex --version")


async def _probe_python_package(
    run_command: ProbeCommandRunner,
    python: str,
    package_name: str,
) -> ToolStatus:
    result = await run_command(
        f"{shlex.quote(python)} -c 'import {package_name}; print({package_name}.__version__)'"
    )
    if result.exit_code != 0:
        return ToolStatus(available=False)
    return ToolStatus(available=True, version=result.stdout.strip() or None)


async def _probe_cuda(run_command: ProbeCommandRunner) -> ToolStatus:
    nvcc_path = await run_command("command -v nvcc")
    if nvcc_path.exit_code != 0:
        return ToolStatus(available=False)
    return ToolStatus(available=True, path=nvcc_path.stdout.strip() or None)


__all__ = [
    "SSHExecutor",
    "TmuxCommandError",
    "build_detection_snapshot",
    "failed_missing_user_snapshot",
    "failed_tmux_snapshot",
    "probe_with_personal_tmux",
    "probe_with_ssh",
]

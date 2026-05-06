from __future__ import annotations

import asyncio
import os
import shlex
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.models import ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.task_harness.artifacts import remote_launch_path

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CLAUDE_COMMAND = [
    "claude",
    "-p",
    "--no-session-persistence",
    "--permission-mode",
    "bypassPermissions",
]


class TaskLaunchError(RuntimeError):
    pass


@dataclass(slots=True)
class LaunchPayload:
    runner_kind: str
    working_directory: str
    command: list[str]
    prompt_file: str
    helper_path: str | None = None
    launch_payload_path: str | None = None


@dataclass(slots=True)
class RunningProcess:
    stdout: Any
    stderr: Any
    runner_kind: str
    _wait: Any
    _terminate: Any
    _kill: Any
    _cleanup: Any

    async def wait(self) -> int:
        return int(await self._wait())

    async def terminate(self) -> None:
        await self._terminate()

    async def kill(self) -> None:
        await self._kill()

    async def cleanup(self) -> None:
        await self._cleanup()


def is_local_environment(environment: EnvironmentRegistryEntry) -> bool:
    return (
        environment.host in _LOCAL_HOSTS
        and environment.proxy_jump is None
        and environment.proxy_command is None
    )


def build_local_launcher(
    *,
    working_directory: str,
    prompt_file: Path,
    rendered_prompt: str,
    settings_path: str | None = None,
) -> tuple[LaunchPayload, Any]:
    ainrf_settings = Path(working_directory) / ".ainrf" / "settings.json"
    resolved_settings = str(ainrf_settings) if ainrf_settings.exists() else settings_path

    command = [*_CLAUDE_COMMAND]
    if resolved_settings is not None:
        command.extend(["--settings", resolved_settings])
    command.append(rendered_prompt)
    payload = LaunchPayload(
        runner_kind="local-process",
        working_directory=working_directory,
        command=command,
        prompt_file=str(prompt_file),
    )

    async def launch() -> RunningProcess:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        if process.stdout is None or process.stderr is None:
            raise TaskLaunchError("Local launcher failed to attach pipes")
        return RunningProcess(
            stdout=process.stdout,
            stderr=process.stderr,
            runner_kind=payload.runner_kind,
            _wait=process.wait,
            _terminate=_sync_wrapper(process.terminate),
            _kill=_sync_wrapper(process.kill),
            _cleanup=_async_noop,
        )

    return payload, launch


def build_ssh_executor(
    environment: EnvironmentRegistryEntry,
    *,
    project_dir: str,
) -> SSHExecutor:
    return SSHExecutor(
        ContainerConfig(
            host=environment.host,
            port=environment.port,
            user=environment.user,
            ssh_key_path=environment.identity_file,
            project_dir=project_dir,
        )
    )


async def build_remote_launcher(
    *,
    executor: SSHExecutor,
    task_id: str,
    local_task_dir: Path,
    working_directory: str,
    prompt_file: Path,
    settings_path: Path | None = None,
    ainrf_dir: Path | None = None,
) -> tuple[LaunchPayload, Any]:
    home_result = await executor.run_command('printf %s "$HOME"', timeout=30)
    if home_result.exit_code != 0 or not home_result.stdout.strip():
        raise TaskLaunchError("startup failure: unable to resolve remote home directory")
    remote_root = f"{home_result.stdout.strip()}/.ainrf/task-harness/{task_id}"
    remote_prompt = f"{remote_root}/prompt.txt"
    remote_settings = f"{remote_root}/claude-settings.json" if settings_path is not None else None
    remote_helper = f"{remote_root}/launch.sh"
    helper_path = remote_launch_path(local_task_dir)
    helper_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'PROMPT_FILE="$1"',
        'WORKDIR="$2"',
        'SETTINGS_FILE="${3:-}"',
        'if [ -f "$WORKDIR/.ainrf/settings.json" ]; then',
        '  SETTINGS_FILE="$WORKDIR/.ainrf/settings.json"',
        "fi",
        'PROMPT_CONTENT="$(cat "$PROMPT_FILE")"',
        'cd "$WORKDIR"',
        'if [[ -n "$SETTINGS_FILE" ]]; then',
        '  exec claude -p --no-session-persistence --permission-mode bypassPermissions --settings "$SETTINGS_FILE" "$PROMPT_CONTENT"',
        "fi",
        'exec claude -p --no-session-persistence --permission-mode bypassPermissions "$PROMPT_CONTENT"',
        "",
    ]
    helper_path.write_text("\n".join(helper_lines), encoding="utf-8")
    await executor.upload(prompt_file, remote_prompt)
    if settings_path is not None and remote_settings is not None:
        await executor.upload(settings_path, remote_settings)

    # Upload .ainrf/ directory for remote skill injection
    if ainrf_dir is not None and ainrf_dir.exists():
        tarball_path = local_task_dir / ".ainrf.tar.gz"
        with tarfile.open(tarball_path, "w:gz") as tar:
            tar.add(ainrf_dir, arcname=".ainrf")
        remote_tarball = f"{working_directory}/.ainrf.tar.gz"
        await executor.upload(tarball_path, remote_tarball)
        extract_result = await executor.run_command(
            f"cd {shlex.quote(working_directory)} && tar -xzf .ainrf.tar.gz && rm .ainrf.tar.gz",
            timeout=60,
        )
        if extract_result.exit_code != 0:
            raise TaskLaunchError("startup failure: unable to extract .ainrf tarball on remote")
        sync_script = f"""cd {shlex.quote(working_directory)} && \
if [ -d .claude/skills ] && [ ! -L .claude/skills ]; then \
  mv .claude/skills .claude/skills.bak.$(date +%Y%m%d%H%M%S); \
fi && \
rm -f .claude/skills && \
ln -s .ainrf/skills .claude/skills"""
        sync_result = await executor.run_command(sync_script, timeout=30)
        if sync_result.exit_code != 0:
            raise TaskLaunchError("startup failure: unable to sync .claude/skills on remote")

    await executor.upload(helper_path, remote_helper)
    chmod_result = await executor.run_command(f"chmod +x {shlex.quote(remote_helper)}", timeout=30)
    if chmod_result.exit_code != 0:
        raise TaskLaunchError("startup failure: unable to chmod remote helper script")
    command = [remote_helper, remote_prompt, working_directory]
    if remote_settings is not None:
        command.append(remote_settings)
    payload = LaunchPayload(
        runner_kind="ssh-process",
        working_directory=working_directory,
        command=command,
        prompt_file=remote_prompt,
        helper_path=remote_helper,
    )

    async def launch() -> RunningProcess:
        remote_command = " ".join(shlex.quote(part) for part in command)
        process = await executor.create_process(remote_command)

        async def _wait() -> int:
            await process.wait()
            return int(process.returncode or 0)

        return RunningProcess(
            stdout=process.stdout,
            stderr=process.stderr,
            runner_kind=payload.runner_kind,
            _wait=_wait,
            _terminate=_sync_wrapper(process.terminate),
            _kill=_sync_wrapper(process.kill),
            _cleanup=executor.close,
        )

    return payload, launch


async def _async_noop() -> None:
    return None


def _sync_wrapper(callback: Any) -> Any:
    async def _wrapped() -> None:
        callback()

    return _wrapped

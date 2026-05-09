from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ainrf.environments.local import is_localhost_environment
from ainrf.execution.models import ContainerConfig
from ainrf.execution.ssh import SSHExecutor

if TYPE_CHECKING:
    from ainrf.environments.models import EnvironmentRegistryEntry


@dataclass(slots=True)
class TerminalExecResult:
    stdout: str
    stderr: str
    exit_code: int
    command: str


async def exec_local_command(
    command: list[str],
    cwd: str,
    timeout: float = 60.0,
) -> TerminalExecResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        raise
    return TerminalExecResult(
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        exit_code=process.returncode or 0,
        command=" ".join(shlex.quote(part) for part in command),
    )


async def exec_remote_command(
    environment: EnvironmentRegistryEntry,
    command: list[str],
    cwd: str,
    timeout: float = 60.0,
) -> TerminalExecResult:
    config = ContainerConfig(
        host=environment.host,
        port=environment.port,
        user=environment.user,
        ssh_key_path=environment.identity_file,
        project_dir=cwd,
    )
    executor = SSHExecutor(config)
    try:
        result = await executor.run_command(
            " ".join(shlex.quote(part) for part in command),
            timeout=timeout,
            cwd=cwd,
        )
    finally:
        await executor.close()
    return TerminalExecResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        command=" ".join(shlex.quote(part) for part in command),
    )


async def exec_command(
    environment: EnvironmentRegistryEntry,
    command: list[str],
    cwd: str,
    timeout: float = 60.0,
) -> TerminalExecResult:
    if is_localhost_environment(environment):
        return await exec_local_command(command, cwd, timeout=timeout)
    return await exec_remote_command(environment, command, cwd, timeout=timeout)

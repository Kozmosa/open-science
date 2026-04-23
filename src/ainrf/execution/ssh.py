from __future__ import annotations

import asyncio
import posixpath
import re
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh
import structlog

from ainrf.execution.errors import (
    BootstrapError,
    CommandTimeoutError,
    SSHConnectionError,
    TransferError,
    UnsupportedContainerError,
)
from ainrf.execution.models import CommandResult, ContainerConfig, ContainerHealth

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping


_RSYNC_TRANSFER_THRESHOLD_BYTES = 100 * 1024 * 1024
_REMOTE_KILL_GRACE_SECONDS = 5
_MAX_BACKOFF_SECONDS = 60
_CLAUDE_INSTALL_COMMAND = "npm install -g @anthropic-ai/claude-code"
_CLAUDE_VERSION_PATTERN = re.compile(r"(\d+\.\d+\.\d+)")
_CUDA_VERSION_PATTERN = re.compile(r"release\s+(\d+\.\d+)")
_DF_FREE_BYTES_PATTERN = re.compile(r"^\d+$")
_RETRYABLE_ASYNCSSH_ERROR = getattr(asyncssh, "Error", Exception)
_NON_RETRYABLE_ASYNCSSH_ERRORS = tuple(
    error_type
    for error_type in (
        getattr(asyncssh, "PermissionDenied", None),
        getattr(asyncssh, "HostKeyNotVerifiable", None),
    )
    if isinstance(error_type, type)
)


class SSHExecutor:
    """Async SSH executor for the AINRF execution layer."""

    def __init__(self, container: ContainerConfig) -> None:
        self._container = container
        self._connection: asyncssh.SSHClientConnection | None = None
        self._connect_lock = asyncio.Lock()
        self._logger = structlog.get_logger(__name__).bind(
            component="ssh_executor",
            host=container.host,
            port=container.port,
            user=container.user,
        )

    async def __aenter__(self) -> SSHExecutor:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def connect(self) -> None:
        deadline = asyncio.get_running_loop().time() + float(self._container.connect_timeout)
        await self._ensure_connection(deadline=deadline)

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return

        connection.close()
        try:
            await connection.wait_closed()
        except Exception:
            self._logger.warning("wait_closed_failed")

    async def run_command(
        self,
        cmd: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        effective_timeout = timeout or self._container.command_timeout

        async def operation(connection: asyncssh.SSHClientConnection) -> CommandResult:
            return await self._run_command_once(connection, cmd, effective_timeout, cwd, env)

        return await self._run_with_reconnect(operation, operation_timeout=effective_timeout)

    async def create_process(
        self,
        cmd: str,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> asyncssh.SSHClientProcess:
        deadline = asyncio.get_running_loop().time() + float(self._container.connect_timeout)
        connection = await self._ensure_connection(deadline=deadline)
        remote_command = self._build_remote_command(cmd, cwd=cwd, env=env)
        return await connection.create_process(remote_command)

    async def upload(self, local: str | Path, remote: str) -> None:
        local_path = Path(local)
        if not local_path.exists():
            raise TransferError(f"Local path does not exist: {local_path}")
        if not local_path.is_file():
            raise TransferError(f"Only file upload is supported in P1: {local_path}")

        remote_parent = posixpath.dirname(remote)
        if remote_parent:
            mkdir_result = await self.run_command(f"mkdir -p {shlex.quote(remote_parent)}")
            if mkdir_result.exit_code != 0:
                raise TransferError(f"Failed to create remote parent directory: {remote_parent}")

        if await self._should_use_rsync(local_path.stat().st_size):
            try:
                await self._run_local_rsync(local_path, remote, upload=True)
                return
            except TransferError:
                self._logger.warning("rsync_upload_fallback", remote_path=remote)

        await self._sftp_put(local_path, remote)

    async def download(self, remote: str, local: str | Path) -> None:
        local_path = Path(local)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if await self._should_use_rsync(await self._remote_size(remote)):
            try:
                await self._run_local_rsync(local_path, remote, upload=False)
                return
            except TransferError:
                self._logger.warning("rsync_download_fallback", remote_path=remote)

        await self._sftp_get(remote, local_path)

    async def ensure_claude_code(self, min_version: str = "2.0.0") -> str:
        await self._ensure_supported_container()

        for binary_name in ("node", "npm"):
            result = await self.run_command(f"command -v {binary_name}")
            if result.exit_code != 0 or not result.stdout.strip():
                raise BootstrapError(f"Missing required runtime dependency: {binary_name}")

        installed_version = await self._detect_claude_version()
        if installed_version is None or self._compare_versions(installed_version, min_version) < 0:
            install_result = await self.run_command(_CLAUDE_INSTALL_COMMAND)
            if install_result.exit_code != 0:
                raise BootstrapError(
                    "Failed to install Claude Code CLI: "
                    f"{install_result.stderr.strip() or install_result.stdout.strip()}"
                )
            installed_version = await self._detect_claude_version()

        if installed_version is None:
            raise BootstrapError("Claude Code CLI is unavailable after installation")
        if self._compare_versions(installed_version, min_version) < 0:
            raise BootstrapError(
                f"Claude Code CLI version {installed_version} is below the minimum {min_version}"
            )

        api_key_result = await self.run_command("printenv ANTHROPIC_API_KEY")
        if api_key_result.exit_code != 0 or not api_key_result.stdout.strip():
            raise BootstrapError("Remote ANTHROPIC_API_KEY is not configured")

        return installed_version

    async def ping(self) -> ContainerHealth:
        deadline = asyncio.get_running_loop().time() + float(self._container.connect_timeout)
        try:
            await self._ensure_connection(deadline=deadline)
        except SSHConnectionError as exc:
            return ContainerHealth(
                ssh_ok=False,
                claude_ok=False,
                anthropic_api_key_ok=False,
                project_dir_writable=False,
                warnings=[str(exc)],
            )

        warnings: list[str] = []

        claude_result = await self.run_command("claude --version", timeout=30)
        claude_version = self._extract_claude_version(claude_result.stdout + claude_result.stderr)
        claude_ok = claude_result.exit_code == 0 and claude_version is not None
        if not claude_ok:
            warnings.append("claude_unavailable")

        api_key_result = await self.run_command("printenv ANTHROPIC_API_KEY", timeout=30)
        anthropic_api_key_ok = api_key_result.exit_code == 0 and bool(api_key_result.stdout.strip())
        if not anthropic_api_key_ok:
            warnings.append("anthropic_api_key_missing")

        gpu_models_result = await self.run_command(
            "nvidia-smi --query-gpu=name --format=csv,noheader", timeout=30
        )
        gpu_models = [
            line.strip() for line in gpu_models_result.stdout.splitlines() if line.strip()
        ]
        if not gpu_models:
            warnings.append("gpu_unavailable")

        cuda_result = await self.run_command("nvcc --version", timeout=30)
        cuda_version = self._extract_cuda_version(cuda_result.stdout + cuda_result.stderr)
        if cuda_version is None:
            warnings.append("cuda_unavailable")

        disk_result = await self.run_command(
            f"df -B1 {shlex.quote(self._container.project_dir)} | tail -1 | awk '{{print $4}}'",
            timeout=30,
        )
        disk_value = disk_result.stdout.strip()
        disk_free_bytes = int(disk_value) if _DF_FREE_BYTES_PATTERN.match(disk_value) else None
        if disk_free_bytes is None:
            warnings.append("disk_probe_failed")

        writable_result = await self.run_command(
            f"test -w {shlex.quote(self._container.project_dir)}", timeout=30
        )
        project_dir_writable = writable_result.exit_code == 0
        if not project_dir_writable:
            warnings.append("project_dir_not_writable")

        return ContainerHealth(
            ssh_ok=True,
            claude_ok=claude_ok,
            anthropic_api_key_ok=anthropic_api_key_ok,
            project_dir_writable=project_dir_writable,
            claude_version=claude_version,
            gpu_models=gpu_models,
            cuda_version=cuda_version,
            disk_free_bytes=disk_free_bytes,
            warnings=warnings,
        )

    async def _run_with_reconnect(
        self,
        operation: Callable[[asyncssh.SSHClientConnection], Awaitable[CommandResult]],
        operation_timeout: float,
    ) -> CommandResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(operation_timeout)
        attempt = 0

        while True:
            attempt += 1
            try:
                connection = await self._ensure_connection(deadline=deadline)
                return await operation(connection)
            except CommandTimeoutError:
                raise
            except Exception as exc:
                if not self._is_retryable_error(exc):
                    raise
                self._logger.warning(
                    "operation_retry",
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                await self._invalidate_connection()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise SSHConnectionError(
                        f"SSH operation timed out while reconnecting to {self._container.host}"
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt - 1), _MAX_BACKOFF_SECONDS, remaining))

    async def _ensure_connection(
        self,
        deadline: float,
        backoff_budget: float | None = None,
    ) -> asyncssh.SSHClientConnection:
        async with self._connect_lock:
            if self._connection_is_usable():
                assert self._connection is not None
                return self._connection

            attempt = 0
            last_error: Exception | None = None
            while True:
                attempt += 1
                try:
                    self._logger.info("connect_attempt", attempt=attempt)
                    self._connection = await self._open_connection()
                    return self._connection
                except Exception as exc:
                    last_error = exc
                    if not self._is_retryable_error(exc):
                        raise SSHConnectionError(
                            f"Failed to connect to {self._container.host}: {exc}"
                        ) from exc
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    sleep_for = min(2 ** (attempt - 1), _MAX_BACKOFF_SECONDS, remaining)
                    if backoff_budget is not None:
                        sleep_for = min(sleep_for, backoff_budget)
                    await asyncio.sleep(sleep_for)

            raise SSHConnectionError(
                f"Failed to connect to {self._container.host} within "
                f"{self._container.connect_timeout} seconds"
            ) from last_error

    async def _open_connection(self) -> asyncssh.SSHClientConnection:
        connect_kwargs: dict[str, object] = {
            "host": self._container.host,
            "port": self._container.port,
            "username": self._container.user,
            "connect_timeout": self._container.connect_timeout,
        }
        ssh_config_path = Path.home() / ".ssh" / "config"
        if ssh_config_path.exists():
            connect_kwargs["config"] = [str(ssh_config_path)]
        if self._container.ssh_key_path is not None:
            connect_kwargs["client_keys"] = [self._container.ssh_key_path]
        if self._container.ssh_password is not None:
            connect_kwargs["password"] = self._container.ssh_password
        return await asyncssh.connect(**connect_kwargs)

    async def _invalidate_connection(self) -> None:
        if self._connection is None:
            return
        connection = self._connection
        self._connection = None
        try:
            connection.close()
            await connection.wait_closed()
        except Exception:
            self._logger.warning("invalidate_connection_failed")

    def _connection_is_usable(self) -> bool:
        if self._connection is None:
            return False
        is_closing = getattr(self._connection, "is_closing", None)
        if callable(is_closing):
            return not bool(is_closing())
        return True

    async def _run_command_once(
        self,
        connection: asyncssh.SSHClientConnection,
        cmd: str,
        timeout: float,
        cwd: str | None,
        env: Mapping[str, str] | None,
    ) -> CommandResult:
        remote_command = self._build_remote_command(cmd, cwd=cwd, env=env)
        process = await connection.create_process(remote_command)
        communicate_task = asyncio.create_task(process.communicate())

        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communicate_task), timeout)
        except TimeoutError as exc:
            process.terminate()
            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(communicate_task), _REMOTE_KILL_GRACE_SECONDS
                )
            except TimeoutError:
                process.kill()
                stdout, stderr = await asyncio.shield(communicate_task)
            raise CommandTimeoutError(
                f"Remote command timed out after {timeout} seconds",
                stdout=stdout,
                stderr=stderr,
            ) from exc

        exit_code = int(process.returncode) if process.returncode is not None else 0
        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _build_remote_command(
        self,
        cmd: str,
        cwd: str | None,
        env: Mapping[str, str] | None,
    ) -> str:
        steps: list[str] = []
        if cwd is not None:
            steps.append(f"cd {shlex.quote(cwd)}")
        if env:
            export_parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
            steps.append(f"export {' '.join(export_parts)}")
        steps.append(cmd)
        return f"bash -lc {shlex.quote(' && '.join(steps))}"

    async def _sftp_put(self, local_path: Path, remote_path: str) -> None:
        async def operation(connection: asyncssh.SSHClientConnection) -> CommandResult:
            sftp = await connection.start_sftp_client()
            await sftp.put(str(local_path), remote_path)
            return CommandResult(exit_code=0, stdout="", stderr="")

        try:
            await self._run_with_reconnect(
                operation, operation_timeout=self._container.command_timeout
            )
        except Exception as exc:
            raise TransferError(f"Failed to upload {local_path} to {remote_path}") from exc

    async def _sftp_get(self, remote_path: str, local_path: Path) -> None:
        async def operation(connection: asyncssh.SSHClientConnection) -> CommandResult:
            sftp = await connection.start_sftp_client()
            await sftp.get(remote_path, str(local_path))
            return CommandResult(exit_code=0, stdout="", stderr="")

        try:
            await self._run_with_reconnect(
                operation, operation_timeout=self._container.command_timeout
            )
        except Exception as exc:
            raise TransferError(f"Failed to download {remote_path} to {local_path}") from exc

    async def _remote_size(self, remote_path: str) -> int:
        async def operation(connection: asyncssh.SSHClientConnection) -> CommandResult:
            sftp = await connection.start_sftp_client()
            attrs = await sftp.stat(remote_path)
            if attrs.size is None:
                raise TransferError(f"Unable to determine remote file size: {remote_path}")
            return CommandResult(exit_code=0, stdout=str(attrs.size), stderr="")

        result = await self._run_with_reconnect(
            operation, operation_timeout=self._container.command_timeout
        )
        return int(result.stdout)

    async def _should_use_rsync(self, file_size: int) -> bool:
        if file_size <= _RSYNC_TRANSFER_THRESHOLD_BYTES:
            return False
        if not self._local_rsync_available():
            return False
        remote_result = await self.run_command("command -v rsync", timeout=30)
        return remote_result.exit_code == 0

    def _local_rsync_available(self) -> bool:
        return shutil.which("rsync") is not None

    async def _run_local_rsync(self, local_path: Path, remote_path: str, upload: bool) -> None:
        ssh_parts = ["ssh"]
        ssh_config_path = Path.home() / ".ssh" / "config"
        if ssh_config_path.exists():
            ssh_parts.extend(["-F", str(ssh_config_path)])
        ssh_parts.extend(["-p", str(self._container.port)])
        if self._container.ssh_key_path is not None:
            ssh_parts.extend(["-i", self._container.ssh_key_path])

        target = f"{self._container.user}@{self._container.host}"
        rsync_command: list[str] = ["rsync", "-az", "-e", " ".join(ssh_parts)]
        if upload:
            rsync_command.extend([str(local_path), f"{target}:{shlex.quote(remote_path)}"])
        else:
            rsync_command.extend([f"{target}:{shlex.quote(remote_path)}", str(local_path)])

        process = await asyncio.create_subprocess_exec(
            *rsync_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        if process.returncode != 0:
            raise TransferError(
                f"rsync failed with exit code {process.returncode}: "
                f"{stderr_bytes.decode().strip() or stdout_bytes.decode().strip()}"
            )

    async def _ensure_supported_container(self) -> None:
        shell_result = await self.run_command("command -v bash", timeout=30)
        if shell_result.exit_code != 0:
            raise UnsupportedContainerError("Only bash-based containers are supported in P1")

        os_result = await self.run_command(
            'test -r /etc/os-release && . /etc/os-release && printf "%s" "$ID"', timeout=30
        )
        distro_id = os_result.stdout.strip().lower()
        if distro_id not in {"ubuntu", "debian"}:
            raise UnsupportedContainerError(
                f"Unsupported container OS '{distro_id or 'unknown'}'; "
                "P1 only supports Ubuntu/Debian"
            )

    async def _detect_claude_version(self) -> str | None:
        result = await self.run_command("claude --version", timeout=30)
        if result.exit_code != 0:
            return None
        return self._extract_claude_version(result.stdout + result.stderr)

    def _extract_claude_version(self, text: str) -> str | None:
        match = _CLAUDE_VERSION_PATTERN.search(text)
        if match is None:
            return None
        return match.group(1)

    def _extract_cuda_version(self, text: str) -> str | None:
        match = _CUDA_VERSION_PATTERN.search(text)
        if match is None:
            return None
        return match.group(1)

    def _compare_versions(self, current: str, minimum: str) -> int:
        current_parts = self._version_tuple(current)
        minimum_parts = self._version_tuple(minimum)
        if current_parts < minimum_parts:
            return -1
        if current_parts > minimum_parts:
            return 1
        return 0

    def _version_tuple(self, version: str) -> tuple[int, int, int]:
        parts = version.split(".")
        normalized = [int(part) for part in parts[:3]]
        while len(normalized) < 3:
            normalized.append(0)
        return (normalized[0], normalized[1], normalized[2])

    def _is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, CommandTimeoutError):
            return False
        if _NON_RETRYABLE_ASYNCSSH_ERRORS and isinstance(exc, _NON_RETRYABLE_ASYNCSSH_ERRORS):
            return False
        if isinstance(exc, (OSError, ConnectionError)):
            return True
        return isinstance(exc, _RETRYABLE_ASYNCSSH_ERROR)

    @property
    def container(self) -> ContainerConfig:
        return self._container

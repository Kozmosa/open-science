from __future__ import annotations

import asyncio
import shlex
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import asyncssh
import httpx

from ainrf.code_server_binary import resolve_local_code_server_binary
from ainrf.environments import EnvironmentAuthKind, InMemoryEnvironmentService
from ainrf.environments.local import is_localhost_environment
from ainrf.environments.models import EnvironmentRegistryEntry

_DEFAULT_PROJECT_ID = "default"
_READY_HTTP_CODES = {200, 302, 401, 403}
_READY_TIMEOUT_SECONDS = 10.0
_PROCESS_CLOSE_TIMEOUT_SECONDS = 5.0
_REMOTE_CODE_SERVER_HOST = "127.0.0.1"
_REMOTE_CODE_SERVER_PORT = 18080


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


class UnsupportedWorkspaceEnvironmentError(ValueError):
    pass


class CodeServerLifecycleStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class CodeServerState:
    status: CodeServerLifecycleStatus
    environment_id: str | None = None
    environment_alias: str | None = None
    workspace_dir: str | None = None
    detail: str | None = None
    managed: bool = True
    pid: int | None = None


@dataclass(slots=True)
class ActiveCodeServerSession:
    state: CodeServerState
    base_url: str
    local_process: subprocess.Popen[str] | None = None
    remote_connection: Any | None = None
    remote_process: Any | None = None
    tunnel: Any | None = None
    tmux_binding: Any | None = None
    tmux_adapter: Any | None = None
    tmux_environment: EnvironmentRegistryEntry | None = None
    tmux_session_name: str | None = None
    tmux_pid_file: Path | None = None


def build_code_server_command(
    host: str,
    port: int,
    workspace_dir: str | Path,
    *,
    executable_path: str = "code-server",
) -> list[str]:
    return [
        executable_path,
        "--bind-addr",
        f"{host}:{port}",
        "--auth",
        "none",
        str(workspace_dir),
    ]


def build_remote_code_server_command(
    workspace_dir: str, *, executable_path: str = "code-server"
) -> str:
    code_server_command = " ".join(
        shlex.quote(part)
        for part in build_code_server_command(
            _REMOTE_CODE_SERVER_HOST,
            _REMOTE_CODE_SERVER_PORT,
            workspace_dir,
            executable_path=executable_path,
        )
    )
    return f"bash -lc {shlex.quote(f'exec {code_server_command}')}"


def _resolve_local_workspace_dir(workspace_dir: str, state_root: Path) -> Path:
    candidate = Path(workspace_dir).expanduser()
    if candidate.is_absolute():
        return candidate
    return state_root / candidate


def _resolve_local_code_server_executable(environment: EnvironmentRegistryEntry) -> str:
    resolution = resolve_local_code_server_binary(environment.code_server_path)
    if resolution.available and resolution.path is not None:
        return resolution.path
    raise RuntimeError(resolution.detail or "code-server binary is unavailable")


def _resolve_remote_code_server_executable(environment: EnvironmentRegistryEntry) -> str:
    if environment.code_server_path:
        return environment.code_server_path
    raise RuntimeError("Remote workspace does not have a configured code-server path")


def _build_asyncssh_connect_kwargs(environment: EnvironmentRegistryEntry) -> dict[str, object]:
    connect_kwargs: dict[str, object] = {
        "host": environment.host,
        "port": environment.port,
        "username": environment.user,
    }
    ssh_config_path = Path.home() / ".ssh" / "config"
    if ssh_config_path.exists():
        connect_kwargs["config"] = [str(ssh_config_path)]
    if environment.identity_file:
        connect_kwargs["client_keys"] = [environment.identity_file]
    if environment.proxy_jump:
        connect_kwargs["tunnel"] = environment.proxy_jump
    if environment.proxy_command:
        connect_kwargs["proxy_command"] = environment.proxy_command
    return connect_kwargs


async def _wait_until_ready(
    host: str, port: int, timeout_seconds: float = _READY_TIMEOUT_SECONDS
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{host}:{port}/"
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url, timeout=1.0, follow_redirects=False)
                if response.status_code in _READY_HTTP_CODES:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    return False


def _terminate_process(
    process: subprocess.Popen[str], timeout_seconds: float = _PROCESS_CLOSE_TIMEOUT_SECONDS
) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


class EnvironmentCodeServerManager:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: InMemoryEnvironmentService,
        project_id: str = _DEFAULT_PROJECT_ID,
        local_host: str = _REMOTE_CODE_SERVER_HOST,
        local_port: int = _REMOTE_CODE_SERVER_PORT,
    ) -> None:
        self._state_root = state_root
        self._environment_service = environment_service
        self._project_id = project_id
        self._local_host = local_host
        self._local_port = local_port
        self._lock = asyncio.Lock()
        self._active_session: ActiveCodeServerSession | None = None
        self._state = CodeServerState(
            status=CodeServerLifecycleStatus.UNAVAILABLE,
            detail="code-server session not started",
            managed=True,
        )

    @property
    def base_url(self) -> str | None:
        session = self._active_session
        if session is None or self._state.status is not CodeServerLifecycleStatus.READY:
            return None
        return session.base_url

    def start(self) -> None:
        return None

    def _build_state(
        self,
        *,
        status: CodeServerLifecycleStatus,
        environment: EnvironmentRegistryEntry | None = None,
        workspace_dir: str | None = None,
        detail: str | None = None,
        pid: int | None = None,
    ) -> CodeServerState:
        return CodeServerState(
            status=status,
            environment_id=environment.id if environment is not None else None,
            environment_alias=environment.alias if environment is not None else None,
            workspace_dir=workspace_dir,
            detail=detail,
            managed=True,
            pid=pid,
        )

    async def status(self, environment_id: str | None = None) -> CodeServerState:
        async with self._lock:
            await self._refresh_state_locked()
            if environment_id is None:
                return self._state

            environment = self._environment_service.get_environment(environment_id)
            workspace_dir = self._environment_service.resolve_effective_workdir(
                self._project_id,
                environment_id,
                self._state_root,
            )
            if self._state.environment_id == environment_id:
                return self._state
            return self._build_state(
                status=CodeServerLifecycleStatus.UNAVAILABLE,
                environment=environment,
                workspace_dir=workspace_dir,
                detail="code-server session not started",
            )

    async def ensure(
        self,
        environment_id: str,
        *,
        app_user_id: str | None = None,
        terminal_session_manager: SessionManagerLike | None = None,
    ) -> CodeServerState:
        async with self._lock:
            await self._refresh_state_locked()
            environment = self._environment_service.get_environment(environment_id)
            workspace_dir = self._environment_service.resolve_effective_workdir(
                self._project_id,
                environment_id,
                self._state_root,
            )

            if environment.auth_kind is EnvironmentAuthKind.PASSWORD:
                detail = "Workspace does not support password-auth environments"
                self._state = self._build_state(
                    status=CodeServerLifecycleStatus.UNAVAILABLE,
                    environment=environment,
                    workspace_dir=workspace_dir,
                    detail=detail,
                )
                raise UnsupportedWorkspaceEnvironmentError(detail)

            if (
                self._state.environment_id == environment_id
                and self._state.status is CodeServerLifecycleStatus.READY
            ):
                return self._state

            if self._active_session is not None:
                await self._stop_locked(detail="code-server session replaced")

            self._state = self._build_state(
                status=CodeServerLifecycleStatus.STARTING,
                environment=environment,
                workspace_dir=workspace_dir,
                detail=None,
            )

            try:
                if is_localhost_environment(environment):
                    session = await self._start_localhost_tmux_session(
                        environment,
                        workspace_dir,
                        app_user_id=app_user_id,
                        terminal_session_manager=terminal_session_manager,
                    )
                else:
                    session = await self._start_remote_session(environment, workspace_dir)
            except UnsupportedWorkspaceEnvironmentError:
                raise
            except Exception as exc:
                self._state = self._build_state(
                    status=CodeServerLifecycleStatus.UNAVAILABLE,
                    environment=environment,
                    workspace_dir=workspace_dir,
                    detail=str(exc),
                )
                self._active_session = None
                return self._state

            self._active_session = session
            self._state = session.state
            return self._state

    async def stop(self) -> CodeServerState:
        async with self._lock:
            return await self._stop_locked(detail="code-server stopped")

    async def _refresh_state_locked(self) -> None:
        session = self._active_session
        if session is None:
            return

        if session.local_process is not None and session.local_process.poll() is not None:
            await self._stop_locked(
                detail=f"code-server exited with code {session.local_process.returncode}"
            )
            return

        remote_process = session.remote_process
        if remote_process is not None and remote_process.returncode is not None:
            await self._stop_locked(
                detail=f"remote code-server exited with code {remote_process.returncode}"
            )

    async def _stop_locked(self, detail: str) -> CodeServerState:
        session = self._active_session
        previous_state = self._state
        self._active_session = None

        if session is not None:
            if session.local_process is not None:
                _terminate_process(session.local_process)

            remote_process = session.remote_process
            if remote_process is not None:
                remote_process.terminate()
                try:
                    await asyncio.wait_for(
                        remote_process.wait_closed(),
                        timeout=_PROCESS_CLOSE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    remote_process.kill()
                    await remote_process.wait_closed()

            tunnel = session.tunnel
            if tunnel is not None:
                tunnel.close()
                await tunnel.wait_closed()

            if session.tmux_binding is not None and session.tmux_environment is not None:
                self._run_tmux_stop_command(session)

            remote_connection = session.remote_connection
            if remote_connection is not None:
                remote_connection.close()
                await remote_connection.wait_closed()

        self._state = CodeServerState(
            status=CodeServerLifecycleStatus.UNAVAILABLE,
            environment_id=previous_state.environment_id,
            environment_alias=previous_state.environment_alias,
            workspace_dir=previous_state.workspace_dir,
            detail=detail,
            managed=True,
        )
        return self._state

    async def _start_localhost_tmux_session(
        self,
        environment: EnvironmentRegistryEntry,
        workspace_dir: str,
        *,
        app_user_id: str | None,
        terminal_session_manager: SessionManagerLike | None,
    ) -> ActiveCodeServerSession:
        if app_user_id is None or terminal_session_manager is None:
            detail = "localhost code-server requires a user id and personal tmux session manager"
            self._state = self._build_state(
                status=CodeServerLifecycleStatus.UNAVAILABLE,
                environment=environment,
                workspace_dir=workspace_dir,
                detail=detail,
            )
            raise UnsupportedWorkspaceEnvironmentError(detail)

        runtime_dir = self._state_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        pid_file = runtime_dir / f"code-server-{environment.id}.pid"
        log_file = runtime_dir / f"code-server-{environment.id}.log"
        executable_path = _resolve_local_code_server_executable(environment)
        command = " ".join(
            shlex.quote(part)
            for part in build_code_server_command(
                self._local_host,
                self._local_port,
                workspace_dir,
                executable_path=executable_path,
            )
        )
        start_command = (
            f"mkdir -p {shlex.quote(str(runtime_dir))}; "
            f"if [ -f {shlex.quote(str(pid_file))} ] && "
            f"kill -0 $(cat {shlex.quote(str(pid_file))}) >/dev/null 2>&1; then exit 0; fi; "
            f"nohup {command} >{shlex.quote(str(log_file))} 2>&1 & "
            f"printf '%s\\n' \"$!\" > {shlex.quote(str(pid_file))}"
        )
        _record, target = terminal_session_manager.ensure_personal_session(
            app_user_id,
            environment,
            workspace_dir,
        )
        binding = terminal_session_manager.get_binding_by_id(target.binding_id)
        if binding is None:
            raise RuntimeError("Personal terminal binding was not found")
        result = await asyncio.to_thread(
            terminal_session_manager.tmux_adapter.run_bounded_session_command,
            binding,
            environment,
            target.session_name,
            command=start_command,
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        if not await _wait_until_ready(self._local_host, self._local_port):
            self._run_tmux_stop_command(
                ActiveCodeServerSession(
                    state=self._build_state(
                        status=CodeServerLifecycleStatus.STARTING,
                        environment=environment,
                        workspace_dir=workspace_dir,
                    ),
                    base_url=f"http://{self._local_host}:{self._local_port}",
                    tmux_binding=binding,
                    tmux_adapter=terminal_session_manager.tmux_adapter,
                    tmux_environment=environment,
                    tmux_session_name=target.session_name,
                    tmux_pid_file=pid_file,
                )
            )
            raise RuntimeError(
                f"code-server failed to become ready on {self._local_host}:{self._local_port}"
            )

        return ActiveCodeServerSession(
            state=self._build_state(
                status=CodeServerLifecycleStatus.READY,
                environment=environment,
                workspace_dir=workspace_dir,
                detail=None,
            ),
            base_url=f"http://{self._local_host}:{self._local_port}",
            tmux_binding=binding,
            tmux_adapter=terminal_session_manager.tmux_adapter,
            tmux_environment=environment,
            tmux_session_name=target.session_name,
            tmux_pid_file=pid_file,
        )

    def _run_tmux_stop_command(self, session: ActiveCodeServerSession) -> None:
        if (
            session.tmux_binding is None
            or session.tmux_adapter is None
            or session.tmux_environment is None
            or session.tmux_session_name is None
            or session.tmux_pid_file is None
        ):
            return
        pid_file = shlex.quote(str(session.tmux_pid_file))
        stop_command = (
            f"if [ -f {pid_file} ]; then "
            f"pid=$(cat {pid_file}); "
            'kill "$pid" >/dev/null 2>&1 || true; '
            "for i in 1 2 3 4 5; do "
            'kill -0 "$pid" >/dev/null 2>&1 || break; '
            "sleep 0.2; "
            "done; "
            'kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" >/dev/null 2>&1 || true; '
            f"rm -f {pid_file}; "
            "fi"
        )
        with suppress(Exception):
            session.tmux_adapter.run_bounded_session_command(
                session.tmux_binding,
                session.tmux_environment,
                session.tmux_session_name,
                command=stop_command,
                timeout_seconds=5.0,
            )

    async def _start_remote_session(
        self,
        environment: EnvironmentRegistryEntry,
        workspace_dir: str,
    ) -> ActiveCodeServerSession:
        executable_path = _resolve_remote_code_server_executable(environment)
        connection = await asyncssh.connect(**_build_asyncssh_connect_kwargs(environment))
        remote_process: Any | None = None
        tunnel: Any | None = None

        try:
            remote_process = await connection.create_process(
                build_remote_code_server_command(
                    workspace_dir,
                    executable_path=executable_path,
                ),
                stdin=asyncssh.DEVNULL,
                stdout=asyncssh.DEVNULL,
                stderr=asyncssh.DEVNULL,
            )
            tunnel = await connection.forward_local_port(
                self._local_host,
                0,
                _REMOTE_CODE_SERVER_HOST,
                _REMOTE_CODE_SERVER_PORT,
            )
            local_port = tunnel.get_port()
            if not await _wait_until_ready(self._local_host, local_port):
                if remote_process.returncode is not None:
                    raise RuntimeError(
                        "remote code-server exited before becoming ready on "
                        f"{_REMOTE_CODE_SERVER_HOST}:{_REMOTE_CODE_SERVER_PORT}; "
                        "the remote port may already be in use"
                    )
                raise RuntimeError(
                    "remote code-server failed to become ready on "
                    f"{_REMOTE_CODE_SERVER_HOST}:{_REMOTE_CODE_SERVER_PORT}"
                )

            return ActiveCodeServerSession(
                state=self._build_state(
                    status=CodeServerLifecycleStatus.READY,
                    environment=environment,
                    workspace_dir=workspace_dir,
                    detail=None,
                ),
                base_url=f"http://{self._local_host}:{local_port}",
                remote_connection=connection,
                remote_process=remote_process,
                tunnel=tunnel,
            )
        except Exception:
            if remote_process is not None:
                remote_process.terminate()
                with suppress(Exception):
                    await remote_process.wait_closed()
            if tunnel is not None:
                tunnel.close()
                with suppress(Exception):
                    await tunnel.wait_closed()
            connection.close()
            with suppress(Exception):
                await connection.wait_closed()
            raise


CodeServerSupervisor = EnvironmentCodeServerManager

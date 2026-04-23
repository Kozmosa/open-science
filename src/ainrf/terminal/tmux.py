from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from hashlib import blake2s
from pathlib import Path

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.tasks.runtime import build_runtime_control_invocation
from ainrf.terminal.models import UserEnvironmentBinding
from ainrf.terminal.pty import TERMINAL_LOCAL_TARGET_KIND, TERMINAL_SSH_TARGET_KIND

_LOCAL_HOSTS = {"127.0.0.1", "localhost"}
_REMOTE_TMUX_MISSING_MARKER = "__AINRF_REMOTE_TMUX_MISSING__"
_TMUX_UNSAFE_SESSION_TARGET_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class TmuxCommandError(RuntimeError):
    pass


@dataclass(slots=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class TmuxWindowInfo:
    window_id: str
    window_name: str
    is_dead: bool = False
    exit_status: int | None = None
    current_path: str | None = None


class TmuxAdapter:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root

    @staticmethod
    def session_name_for(user_id: str, environment_id: str, *, kind: str = "personal") -> str:
        prefix = "a" if kind == "agent" else "p"
        digest = blake2s(
            f"{user_id}\0{environment_id}\0{kind}".encode("utf-8"),
            digest_size=5,
        ).hexdigest()
        return f"{prefix}-{digest}"

    @staticmethod
    def target_kind_for(environment: EnvironmentRegistryEntry) -> str:
        if (
            environment.host in _LOCAL_HOSTS
            and environment.proxy_jump is None
            and environment.proxy_command is None
        ):
            return TERMINAL_LOCAL_TARGET_KIND
        return TERMINAL_SSH_TARGET_KIND

    @staticmethod
    def session_target_for(session_name: str) -> str:
        return _TMUX_UNSAFE_SESSION_TARGET_PATTERN.sub("_", session_name)

    def has_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> bool:
        session_target = self.session_target_for(session_name)
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(("tmux", "has-session", "-t", session_target))
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(
                    shlex.join(["tmux", "has-session", "-t", session_target])
                ),
            )

        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        self._raise_command_error(result, environment)
        return False

    def ensure_personal_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        self._ensure_session(binding, environment, session_name)

    def ensure_agent_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        self._ensure_session(binding, environment, session_name)
        self._configure_remain_on_exit(binding, environment, session_name)

    def _ensure_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        if self.has_session(binding, environment, session_name):
            return

        session_target = self.session_target_for(session_name)
        default_workdir = binding.default_workdir or str(self._state_root)
        default_shell = binding.default_shell or "/bin/bash"
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(
                (
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    session_target,
                    "-c",
                    default_workdir,
                    default_shell,
                    "-l",
                )
            )
        else:
            remote_command = self._wrap_remote_tmux_check(
                shlex.join(
                    [
                        "tmux",
                        "new-session",
                        "-d",
                        "-s",
                        session_target,
                        "-c",
                        default_workdir,
                        default_shell,
                        "-l",
                    ]
                )
            )
            result = self._run_remote_command(
                environment, binding.remote_login_user, remote_command
            )

        if result.returncode != 0:
            if self._is_duplicate_session_result(result, session_target) and self.has_session(
                binding,
                environment,
                session_name,
            ):
                return
            self._raise_command_error(result, environment)

    def reset_personal_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        if self.has_session(binding, environment, session_name):
            self.kill_session(binding, environment, session_name)
        self.ensure_personal_session(binding, environment, session_name)

    def kill_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        session_target = self.session_target_for(session_name)
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(("tmux", "kill-session", "-t", session_target))
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(
                    shlex.join(["tmux", "kill-session", "-t", session_target])
                ),
            )
        if result.returncode not in {0, 1}:
            self._raise_command_error(result, environment)

    def create_window(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
        *,
        window_name: str,
        working_directory: str,
        command: str,
    ) -> TmuxWindowInfo:
        session_target = self.session_target_for(session_name)
        shell_command = self._build_shell_exec_command(binding.default_shell, command)
        format_string = "#{window_id}\t#{window_name}"
        tmux_command = (
            "tmux",
            "new-window",
            "-P",
            "-F",
            format_string,
            "-t",
            session_target,
            "-n",
            window_name,
            "-c",
            working_directory,
            shell_command,
        )
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(tmux_command)
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(shlex.join(tmux_command)),
            )

        if result.returncode != 0:
            self._raise_command_error(result, environment)
        return self._parse_window_creation(result.stdout)

    def inspect_window(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
        window_id: str,
    ) -> TmuxWindowInfo | None:
        format_string = "#{window_id}\t#{window_name}\t#{window_dead}\t#{pane_dead_status}\t#{pane_current_path}"
        tmux_command = (
            "tmux",
            "list-windows",
            "-t",
            self.session_target_for(session_name),
            "-F",
            format_string,
        )
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(tmux_command)
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(shlex.join(tmux_command)),
            )

        if result.returncode == 1:
            return None
        if result.returncode != 0:
            self._raise_command_error(result, environment)
        for line in result.stdout.splitlines():
            parsed = self._parse_window_line(line)
            if parsed is not None and parsed.window_id == window_id:
                return parsed
        return None

    def build_window_attach_command(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
        window_id: str,
    ) -> tuple[str, ...]:
        session_target = self.session_target_for(session_name)
        tmux_command = (
            "tmux",
            "attach-session",
            "-t",
            session_target,
            ";",
            "select-window",
            "-t",
            window_id,
        )
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            return tmux_command
        return self._build_ssh_command(
            environment,
            binding.remote_login_user,
            f"exec {shlex.join(tmux_command)}",
            tty=True,
        )

    def send_window_interrupt(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        window_id: str,
    ) -> None:
        tmux_command = ("tmux", "send-keys", "-t", window_id, "C-c")
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(tmux_command)
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(shlex.join(tmux_command)),
            )
        if result.returncode != 0:
            self._raise_command_error(result, environment)

    def kill_window(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        window_id: str,
    ) -> None:
        tmux_command = ("tmux", "kill-window", "-t", window_id)
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(tmux_command)
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(shlex.join(tmux_command)),
            )
        if result.returncode not in {0, 1}:
            self._raise_command_error(result, environment)

    def build_attach_command(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> tuple[str, ...]:
        session_target = self.session_target_for(session_name)
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            return ("tmux", "attach-session", "-t", session_target)
        return self._build_ssh_command(
            environment,
            binding.remote_login_user,
            f"exec {shlex.join(['tmux', 'attach-session', '-t', session_target])}",
            tty=True,
        )

    def run_shell_command(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        command: tuple[str, ...],
    ) -> _CommandResult:
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            return self._run_local_command(command)
        return self._run_remote_command(
            environment,
            binding.remote_login_user,
            shlex.join(command),
        )

    def run_task_runtime_control(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        *,
        runtime_dir: str,
        action: str,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        result = self.run_shell_command(
            binding,
            environment,
            build_runtime_control_invocation(
                runtime_dir=runtime_dir,
                action=action,
                timeout_seconds=timeout_seconds,
            ),
        )
        if result.returncode != 0:
            self._raise_command_error(result, environment)
        stdout = result.stdout.strip()
        if not stdout:
            raise TmuxCommandError(f"Task runtime {action} returned an empty response")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise TmuxCommandError(
                f"Task runtime {action} returned invalid JSON: {stdout}"
            ) from exc

    def _configure_remain_on_exit(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        tmux_command = (
            "tmux",
            "set-option",
            "-t",
            self.session_target_for(session_name),
            "remain-on-exit",
            "on",
        )
        if self.target_kind_for(environment) == TERMINAL_LOCAL_TARGET_KIND:
            result = self._run_local_command(tmux_command)
        else:
            result = self._run_remote_command(
                environment,
                binding.remote_login_user,
                self._wrap_remote_tmux_check(shlex.join(tmux_command)),
            )
        if result.returncode != 0:
            self._raise_command_error(result, environment)

    @staticmethod
    def _is_duplicate_session_result(result: _CommandResult, session_target: str) -> bool:
        output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
        return "duplicate session" in output.lower() and session_target in output

    def _run_local_command(self, command: tuple[str, ...]) -> _CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                cwd=self._state_root,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise TmuxCommandError("tmux is not installed on the daemon host") from exc

        return _CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _run_remote_command(
        self,
        environment: EnvironmentRegistryEntry,
        remote_login_user: str,
        remote_command: str,
    ) -> _CommandResult:
        completed = subprocess.run(
            list(
                self._build_ssh_command(
                    environment,
                    remote_login_user,
                    remote_command,
                    tty=False,
                )
            ),
            cwd=self._state_root,
            check=False,
            capture_output=True,
            text=True,
        )
        return _CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    @staticmethod
    def _wrap_remote_tmux_check(command: str) -> str:
        return (
            f"command -v tmux >/dev/null 2>&1 || "
            f"{{ echo {_REMOTE_TMUX_MISSING_MARKER}; exit 127; }}; "
            f"{command}"
        )

    def _build_ssh_command(
        self,
        environment: EnvironmentRegistryEntry,
        remote_login_user: str,
        remote_command: str,
        *,
        tty: bool,
    ) -> tuple[str, ...]:
        command: list[str] = ["ssh"]
        if tty:
            command.append("-tt")
        ssh_config_path = Path.home() / ".ssh" / "config"
        if ssh_config_path.exists():
            command.extend(["-F", str(ssh_config_path)])
        if environment.port:
            command.extend(["-p", str(environment.port)])
        if environment.identity_file:
            command.extend(["-i", environment.identity_file])
        if environment.proxy_jump:
            command.extend(["-o", f"ProxyJump={environment.proxy_jump}"])
        if environment.proxy_command:
            command.extend(["-o", f"ProxyCommand={environment.proxy_command}"])
        for key, value in sorted(environment.ssh_options.items()):
            command.extend(["-o", f"{key}={value}"])
        command.append(f"{remote_login_user}@{environment.host}")
        command.append(remote_command)
        return tuple(command)

    @staticmethod
    def _raise_command_error(
        result: _CommandResult,
        environment: EnvironmentRegistryEntry,
    ) -> None:
        output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
        if _REMOTE_TMUX_MISSING_MARKER in output:
            raise TmuxCommandError(
                f"tmux is not installed on remote environment {environment.alias}"
            )
        if not output:
            output = f"tmux command failed with exit code {result.returncode}"
        raise TmuxCommandError(output)

    @staticmethod
    def _build_shell_exec_command(default_shell: str | None, command: str) -> str:
        shell = default_shell or "/bin/bash"
        return f"exec {shlex.quote(shell)} -lc {shlex.quote(command)}"

    @staticmethod
    def _parse_window_creation(output: str) -> TmuxWindowInfo:
        for line in output.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2 or not parts[0]:
                continue
            return TmuxWindowInfo(window_id=parts[0], window_name=parts[1])
        raise TmuxCommandError("tmux did not return the created window metadata")

    @staticmethod
    def _parse_window_line(line: str) -> TmuxWindowInfo | None:
        parts = line.split("\t", 4)
        if len(parts) != 5 or not parts[0]:
            return None
        exit_status: int | None = None
        if parts[3].strip():
            try:
                exit_status = int(parts[3].strip())
            except ValueError:
                exit_status = None
        return TmuxWindowInfo(
            window_id=parts[0],
            window_name=parts[1],
            is_dead=parts[2].strip() == "1",
            exit_status=exit_status,
            current_path=parts[4] or None,
        )

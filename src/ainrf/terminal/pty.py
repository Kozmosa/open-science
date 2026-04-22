from __future__ import annotations

import errno
import os
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

TERMINAL_PROVIDER = "tmux"
TERMINAL_IDLE_TARGET_KIND = "daemon-host"
TERMINAL_LOCAL_TARGET_KIND = "environment-local"
TERMINAL_SSH_TARGET_KIND = "environment-ssh"
TERMINAL_ATTACHMENT_TOKEN_TTL = timedelta(minutes=5)
_TERMINAL_CLOSE_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class TerminalBridgeRuntime:
    process: subprocess.Popen[Any]
    master_fd: int | None


def _to_websocket_base(api_base_url: str) -> str:
    normalized = api_base_url.rstrip("/")
    if normalized.startswith("https://"):
        return "wss://" + normalized.removeprefix("https://")
    if normalized.startswith("http://"):
        return "ws://" + normalized.removeprefix("http://")
    return normalized


def build_attachment_ws_url(api_base_url: str, attachment_id: str, token: str) -> str:
    websocket_base = _to_websocket_base(api_base_url)
    return f"{websocket_base}/terminal/attachments/{attachment_id}/ws?token={token}"


def _close_master_fd(master_fd: int | None) -> None:
    if master_fd is None:
        return
    try:
        os.close(master_fd)
    except OSError:
        pass


def start_terminal_bridge(
    shell_command: tuple[str, ...],
    spawn_working_directory: Path,
) -> TerminalBridgeRuntime:
    spawn_working_directory.mkdir(parents=True, exist_ok=True)
    normalized_working_directory = spawn_working_directory.resolve(strict=True)
    master_fd, slave_fd = os.openpty()
    try:
        process = subprocess.Popen(
            list(shell_command),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=normalized_working_directory,
            start_new_session=True,
            text=False,
            close_fds=True,
        )
    except Exception:
        _close_master_fd(master_fd)
        _close_master_fd(slave_fd)
        raise
    finally:
        _close_master_fd(slave_fd)

    os.set_blocking(master_fd, False)
    return TerminalBridgeRuntime(process=process, master_fd=master_fd)


def stop_terminal_bridge(runtime: TerminalBridgeRuntime | None) -> None:
    if runtime is None:
        return

    _close_master_fd(runtime.master_fd)
    runtime.master_fd = None

    if runtime.process.poll() is None:
        try:
            os.killpg(runtime.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            runtime.process.wait(timeout=_TERMINAL_CLOSE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(runtime.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            runtime.process.wait(timeout=_TERMINAL_CLOSE_TIMEOUT_SECONDS)


def write_terminal_input(runtime: TerminalBridgeRuntime, data: str) -> None:
    if runtime.master_fd is None:
        return
    os.write(runtime.master_fd, data.encode("utf-8"))


def resize_terminal(runtime: TerminalBridgeRuntime, cols: int, rows: int) -> None:
    if runtime.master_fd is None:
        return
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        import fcntl

        fcntl.ioctl(runtime.master_fd, termios.TIOCSWINSZ, packed)
    except OSError as exc:
        if exc.errno not in {errno.EIO, errno.EBADF}:
            raise

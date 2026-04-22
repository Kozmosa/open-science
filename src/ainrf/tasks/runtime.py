from __future__ import annotations

import base64
import json
import shlex
from pathlib import Path, PurePosixPath

_TASK_RUNTIME_SOURCE = r"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def metadata_path(runtime_dir: Path) -> Path:
    return runtime_dir / "metadata.json"


def socket_path(runtime_dir: Path) -> Path:
    return runtime_dir / "control.sock"


class RuntimeController:
    def __init__(
        self,
        *,
        task_id: str,
        runtime_dir: Path,
        child: subprocess.Popen[str],
    ) -> None:
        self._task_id = task_id
        self._runtime_dir = runtime_dir
        self._child = child
        self._lock = threading.Lock()
        self._paused = False
        self._state = "running"
        self._detail = None
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.settimeout(0.5)
        self._running = True
        socket_file = socket_path(runtime_dir)
        if socket_file.exists():
            socket_file.unlink()
        self._server.bind(str(socket_file))
        self._server.listen(4)
        self._write_metadata()

    def serve(self) -> None:
        while self._running:
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._running:
                    raise
                return
            with connection:
                payload = self._read_payload(connection)
                response = self._handle(payload)
                connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._running = False
        try:
            self._server.close()
        finally:
            with contextlib_suppress():
                socket_path(self._runtime_dir).unlink()

    def set_completed(self, return_code: int) -> None:
        with self._lock:
            self._paused = False
            self._state = "completed" if return_code == 0 else "failed"
            self._detail = None if return_code == 0 else f"Task exited with code {return_code}"
            self._write_metadata(return_code=return_code)

    def forward_signal(self, signum: int) -> None:
        if self._child.poll() is not None:
            return
        try:
            os.killpg(self._child.pid, signum)
        except ProcessLookupError:
            return

    def _read_payload(self, connection: socket.socket) -> dict[str, object]:
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        raw = b"".join(chunks).decode("utf-8").strip()
        if not raw:
            return {"action": "status"}
        return json.loads(raw)

    def _handle(self, payload: dict[str, object]) -> dict[str, object]:
        action = payload.get("action")
        if action == "status":
            return self._status_response(ok=True)
        if action == "pause":
            return self._pause()
        if action == "resume":
            return self._resume()
        if action == "interrupt":
            return self._interrupt()
        return {"ok": False, "detail": f"Unsupported action: {action!r}"}

    def _pause(self) -> dict[str, object]:
        if self._child.poll() is not None:
            return self._status_response(ok=False, detail="Task runtime is no longer running")
        with self._lock:
            if self._paused:
                return self._status_response(ok=True)
            os.killpg(self._child.pid, signal.SIGSTOP)
            self._paused = True
            self._state = "paused"
            self._detail = None
            self._write_metadata()
            return self._status_response(ok=True)

    def _resume(self) -> dict[str, object]:
        if self._child.poll() is not None:
            return self._status_response(ok=False, detail="Task runtime is no longer running")
        with self._lock:
            if not self._paused:
                return self._status_response(ok=True)
            os.killpg(self._child.pid, signal.SIGCONT)
            self._paused = False
            self._state = "running"
            self._detail = None
            self._write_metadata()
            return self._status_response(ok=True)

    def _interrupt(self) -> dict[str, object]:
        if self._child.poll() is not None:
            return self._status_response(ok=False, detail="Task runtime is no longer running")
        with self._lock:
            os.killpg(self._child.pid, signal.SIGINT)
            self._detail = "Interrupt signal forwarded to task runtime"
            self._write_metadata()
            return self._status_response(ok=True)

    def _status_response(
        self,
        *,
        ok: bool,
        detail: str | None = None,
    ) -> dict[str, object]:
        return {
            "ok": ok,
            "task_id": self._task_id,
            "state": self._state,
            "paused": self._paused,
            "detail": detail or self._detail,
            "child_pid": self._child.pid,
            "child_pgid": self._child.pid,
            "return_code": self._child.poll(),
        }

    def _write_metadata(self, *, return_code: int | None = None) -> None:
        payload = {
            "task_id": self._task_id,
            "updated_at": utc_now(),
            "state": self._state,
            "paused": self._paused,
            "detail": self._detail,
            "child_pid": self._child.pid,
            "child_pgid": self._child.pid,
            "return_code": self._child.poll() if return_code is None else return_code,
            "socket_path": str(socket_path(self._runtime_dir)),
        }
        metadata_path(self._runtime_dir).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


class contextlib_suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc is not None


def wait_for_socket(runtime_dir: Path, timeout_seconds: float) -> Path:
    path = socket_path(runtime_dir)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return path
        time.sleep(0.05)
    raise RuntimeError(f"Task runtime control socket did not appear at {path}")


def connect_and_request(runtime_dir: Path, action: str, timeout_seconds: float) -> dict[str, object]:
    path = wait_for_socket(runtime_dir, timeout_seconds)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout_seconds)
        connection.connect(str(path))
        connection.sendall((json.dumps({"action": action}) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    raw = b"".join(chunks).decode("utf-8").strip()
    if not raw:
        raise RuntimeError("Task runtime control returned an empty response")
    return json.loads(raw)


def run_runtime(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    shell = args.shell or shutil.which("bash") or "/bin/sh"
    child = subprocess.Popen(
        [shell, "-lc", args.command],
        cwd=args.working_directory,
        start_new_session=True,
        text=True,
    )
    controller = RuntimeController(
        task_id=args.task_id,
        runtime_dir=runtime_dir,
        child=child,
    )
    server_thread = threading.Thread(target=controller.serve, daemon=True)
    server_thread.start()

    def forward(signum: int, _frame: object) -> None:
        controller.forward_signal(signum)

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)
    try:
        return_code = child.wait()
    finally:
        controller.set_completed(child.returncode if child.returncode is not None else 1)
        controller.close()
    return return_code


def control_runtime(args: argparse.Namespace) -> int:
    payload = connect_and_request(Path(args.runtime_dir), args.action, args.timeout_seconds)
    print(json.dumps(payload, ensure_ascii=True))
    return 0 if payload.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ainrf-task-runtime")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--task-id", required=True)
    run_parser.add_argument("--runtime-dir", required=True)
    run_parser.add_argument("--working-directory", required=True)
    run_parser.add_argument("--shell", required=False)
    run_parser.add_argument("--command", required=True)

    control_parser = subparsers.add_parser("control")
    control_parser.add_argument("--runtime-dir", required=True)
    control_parser.add_argument(
        "--action",
        required=True,
        choices=("pause", "resume", "status", "interrupt"),
    )
    control_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand == "run":
        return run_runtime(args)
    return control_runtime(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[2:]))
"""

_TASK_RUNTIME_SOURCE_B64 = base64.b64encode(_TASK_RUNTIME_SOURCE.encode("utf-8")).decode("ascii")
_TASK_RUNTIME_BOOTSTRAP = (
    "import base64,sys;"
    "source=base64.b64decode(sys.argv[1]).decode('utf-8');"
    "globals_dict={'__name__':'__main__'};"
    "exec(compile(source,'<ainrf-task-runtime>','exec'),globals_dict)"
)


def runtime_dir_for_task(working_directory: str, task_id: str) -> str:
    return str(PurePosixPath(working_directory) / ".ainrf" / "runtime" / "tasks" / task_id)


def control_socket_path(runtime_dir: str) -> str:
    return str(PurePosixPath(runtime_dir) / "control.sock")


def metadata_path(runtime_dir: str) -> str:
    return str(PurePosixPath(runtime_dir) / "metadata.json")


def build_runtime_run_invocation(
    *,
    task_id: str,
    runtime_dir: str,
    working_directory: str,
    command: str,
    shell: str,
) -> tuple[str, ...]:
    return (
        "python3",
        "-c",
        _TASK_RUNTIME_BOOTSTRAP,
        _TASK_RUNTIME_SOURCE_B64,
        "run",
        "--task-id",
        task_id,
        "--runtime-dir",
        runtime_dir,
        "--working-directory",
        working_directory,
        "--shell",
        shell,
        "--command",
        command,
    )


def build_runtime_control_invocation(
    *,
    runtime_dir: str,
    action: str,
    timeout_seconds: float = 5.0,
) -> tuple[str, ...]:
    return (
        "python3",
        "-c",
        _TASK_RUNTIME_BOOTSTRAP,
        _TASK_RUNTIME_SOURCE_B64,
        "control",
        "--runtime-dir",
        runtime_dir,
        "--action",
        action,
        "--timeout-seconds",
        str(timeout_seconds),
    )


def build_runtime_run_command(
    *,
    task_id: str,
    runtime_dir: str,
    working_directory: str,
    command: str,
    shell: str,
) -> str:
    return shlex.join(
        build_runtime_run_invocation(
            task_id=task_id,
            runtime_dir=runtime_dir,
            working_directory=working_directory,
            command=command,
            shell=shell,
        )
    )


def build_runtime_control_command(
    *,
    runtime_dir: str,
    action: str,
    timeout_seconds: float = 5.0,
) -> str:
    return shlex.join(
        build_runtime_control_invocation(
            runtime_dir=runtime_dir,
            action=action,
            timeout_seconds=timeout_seconds,
        )
    )


def read_runtime_metadata(runtime_dir: str) -> dict[str, object] | None:
    path = Path(metadata_path(runtime_dir))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

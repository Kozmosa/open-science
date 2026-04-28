from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn

from ainrf.api import ApiConfig, create_app


def run_server(host: str, port: int, state_root: Path) -> None:
    app = create_app(ApiConfig.from_env(state_root))
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        ws_ping_interval=10.0,
        ws_ping_timeout=30.0,
    )


def run_server_daemon(
    host: str,
    port: int,
    state_root: Path,
    pid_file: Path,
    log_file: Path,
) -> int:
    _ensure_not_running(pid_file)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ainrf",
                "serve",
                "--host",
                host,
                "--port",
                str(port),
                "--state-root",
                str(state_root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
            text=True,
        )

    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    if _wait_until_healthy(host, port):
        return process.pid

    _terminate_process(process.pid)
    pid_file.unlink(missing_ok=True)
    raise RuntimeError(f"AINRF API daemon failed to become healthy on {host}:{port}")


def stop_server_daemon(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    raw_value = pid_file.read_text(encoding="utf-8").strip()
    if not raw_value.isdigit():
        pid_file.unlink(missing_ok=True)
        return False
    pid = int(raw_value)
    if _process_exists(pid):
        _terminate_process(pid)
    pid_file.unlink(missing_ok=True)
    return True


def _wait_until_healthy(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{host}:{port}/health"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code in {200, 503}:
                return True
        except httpx.HTTPError:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    return False


def _ensure_not_running(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    raw_value = pid_file.read_text(encoding="utf-8").strip()
    if raw_value.isdigit() and _process_exists(int(raw_value)):
        raise RuntimeError(f"AINRF API daemon is already running with pid {raw_value}")
    pid_file.unlink(missing_ok=True)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process(pid: int) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return

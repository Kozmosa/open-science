"""py-spy hotspot profiler helper.

Attaches py-spy to the running OpenScience server process and triggers a
representative workload, producing a flamegraph SVG.

Requires: py-spy (pip install py-spy)
Requires: A running OpenScience server with a known PID.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_URL = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")
STATE_ROOT = Path(os.environ.get("AINRF_STATE_ROOT", Path.home() / ".ainrf"))
PID_FILE = STATE_ROOT / "server.pid"
DURATION = int(os.environ.get("AINRF_PERF_PROFILE_DURATION", "30"))

WORKLOAD_SCRIPT = r'''
import httpx, os, sys, json
BASE = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")

def get_token():
    r = httpx.post(f"{BASE}/auth/login", json={"username": "perf-admin", "password": "perf-test-pass"})
    if r.status_code != 200:
        r = httpx.post(f"{BASE}/auth/register", json={"username": "perf-admin", "display_name": "Perf Admin", "password": "perf-test-pass"})
        r = httpx.post(f"{BASE}/auth/login", json={"username": "perf-admin", "password": "perf-test-pass"})
        if r.status_code != 200:
            print(f"Cannot authenticate: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
    return r.json()["access_token"]

token = get_token()
h = {"Authorization": f"Bearer {token}"}

for i in range(10):
    httpx.get(f"{BASE}/projects/default/tasks", headers=h)
    httpx.get(f"{BASE}/files/list?environment_id=env-localhost&path=/", headers=h)
    httpx.post(f"{BASE}/tasks", json={
        "project_id": "default", "workspace_id": "workspace-default",
        "environment_id": "env-localhost", "task_profile": "claude-code",
        "task_input": "perf profile", "title": f"perf-profile-{i}",
    }, headers=h)
'''


def find_pid() -> int:
    """Find the OpenScience server PID from PID file or process search."""
    if PID_FILE.exists():
        return int(PID_FILE.read_text().strip())

    # Fallback: find the uvicorn process
    result = subprocess.run(
        ["pgrep", "-f", "openscience serve"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return int(result.stdout.strip().split('\n')[0])

    print("ERROR: Cannot find OpenScience server process. Start the server first or set AINRF_STATE_ROOT.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    from scripts.perf._common import today_dir

    report_dir = today_dir()

    # Check py-spy is available
    try:
        subprocess.run(["py-spy", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: py-spy not found. Install with: pip install py-spy", file=sys.stderr)
        sys.exit(1)

    pid = find_pid()
    flamegraph_path = report_dir / "flamegraph.svg"

    print(f"Profiling PID {pid} for {DURATION}s...")

    # Start py-spy in background
    py_spy = subprocess.Popen([
        "py-spy", "record",
        "-o", str(flamegraph_path),
        "--pid", str(pid),
        "--duration", str(DURATION),
        "--native",
    ])

    # Give py-spy a moment to attach, then trigger workload
    time.sleep(1)
    print("Triggering workload...")
    try:
        subprocess.run(
            [sys.executable, "-c", WORKLOAD_SCRIPT],
            timeout=DURATION + 10,
        )
    except subprocess.TimeoutExpired:
        print("Workload timed out (this may be OK)")

    # Wait for py-spy to finish
    py_spy.wait(timeout=DURATION + 15)
    print(f"Flamegraph written to {flamegraph_path}")


if __name__ == "__main__":
    main()

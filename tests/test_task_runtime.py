from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ainrf.tasks.runtime import build_runtime_control_invocation, build_runtime_run_invocation


def test_task_runtime_run_status_pause_resume_roundtrip(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime" / "task-1"
    process = subprocess.Popen(
        list(
            build_runtime_run_invocation(
                task_id="task-1",
                runtime_dir=str(runtime_dir),
                working_directory=str(tmp_path),
                shell="/bin/bash",
                command="python3 -c 'import time; time.sleep(30)'",
            )
        ),
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if (runtime_dir / "control.sock").exists() and (runtime_dir / "metadata.json").exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("task runtime control socket was not created in time")

        status = subprocess.run(
            list(
                build_runtime_control_invocation(
                    runtime_dir=str(runtime_dir),
                    action="status",
                    timeout_seconds=5.0,
                )
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        paused = subprocess.run(
            list(
                build_runtime_control_invocation(
                    runtime_dir=str(runtime_dir),
                    action="pause",
                    timeout_seconds=5.0,
                )
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        resumed = subprocess.run(
            list(
                build_runtime_control_invocation(
                    runtime_dir=str(runtime_dir),
                    action="resume",
                    timeout_seconds=5.0,
                )
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )

        assert status.returncode == 0
        assert paused.returncode == 0
        assert resumed.returncode == 0
        assert json.loads(status.stdout)["state"] == "running"
        assert json.loads(paused.stdout)["state"] == "paused"
        assert json.loads(paused.stdout)["paused"] is True
        assert json.loads(resumed.stdout)["state"] == "running"
        assert json.loads(resumed.stdout)["paused"] is False
    finally:
        subprocess.run(
            list(
                build_runtime_control_invocation(
                    runtime_dir=str(runtime_dir),
                    action="interrupt",
                    timeout_seconds=2.0,
                )
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        process.wait(timeout=10.0)

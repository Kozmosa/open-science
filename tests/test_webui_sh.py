from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cli]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _load_key_value_lines(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        payload[key] = value
    return payload


def _make_fake_command_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = """#!/usr/bin/env bash
set -euo pipefail
log_path="${AINRF_TEST_LOG_DIR}/launcher.log"
{
  printf 'PWD=%s\n' "${PWD}"
  printf 'UV_CACHE_DIR=%s\n' "${UV_CACHE_DIR:-}"
  printf 'ARGS=%s\n' "$*"
} > "${log_path}"
"""
    _write_executable(bin_dir / "uv", fake_uv)
    return bin_dir


def _run_webui_script(
    repo_root: Path,
    tmp_path: Path,
    args: list[str],
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{_make_fake_command_bin(tmp_path)}:{env['PATH']}"
    env["AINRF_TEST_LOG_DIR"] = str(tmp_path)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(repo_root / "scripts" / "webui.sh"), *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_webui_sh_maps_default_personal_dev_mode_to_unified_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)

    result = _run_webui_script(repo_root, tmp_path, [])

    assert result.returncode == 0
    launcher = _load_key_value_lines(tmp_path / "launcher.log")

    assert launcher["PWD"] == str(repo_root)
    assert launcher["UV_CACHE_DIR"] == "/tmp/uv-cache"
    assert launcher["ARGS"] == (
        f"run python {repo_root / 'scripts' / 'dev.py'} up --mode dev "
        f"--personal-state-root {Path.home() / '.ainrf'} --bind-host 127.0.0.1 "
        "--frontend-host 0.0.0.0 --api-port 8000 --frontend-port 5173 --foreground"
    )


def test_webui_sh_supports_preview_and_backend_public_with_explicit_token(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_webui_script(
        repo_root,
        tmp_path,
        ["preview", "--backend-public"],
        env_overrides={
            "UV_CACHE_DIR": "/var/tmp/custom-uv-cache",
            "AINRF_WEBUI_API_KEY": "fixed-test-token",
        },
    )

    assert result.returncode == 0
    launcher = _load_key_value_lines(tmp_path / "launcher.log")

    assert launcher["UV_CACHE_DIR"] == "/var/tmp/custom-uv-cache"
    assert launcher["ARGS"] == (
        f"run python {repo_root / 'scripts' / 'dev.py'} up --mode preview "
        f"--personal-state-root {Path.home() / '.ainrf'} --bind-host 0.0.0.0 "
        "--frontend-host 0.0.0.0 --api-port 8000 --frontend-port 4173 --foreground "
        "--api-key fixed-test-token"
    )

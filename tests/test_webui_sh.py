from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path


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
log_path="${AINRF_TEST_LOG_DIR}/backend.log"
{
  printf 'PWD=%s\n' "${PWD}"
  printf 'UV_CACHE_DIR=%s\n' "${UV_CACHE_DIR:-}"
  printf 'AINRF_API_KEY_HASHES=%s\n' "${AINRF_API_KEY_HASHES:-}"
  printf 'AINRF_WEBUI_API_KEY=%s\n' "${AINRF_WEBUI_API_KEY:-}"
  printf 'ARGS=%s\n' "$*"
} > "${log_path}"
sleep 0.1
"""
    fake_npm = """#!/usr/bin/env bash
set -euo pipefail
log_path="${AINRF_TEST_LOG_DIR}/frontend.log"
{
  printf 'PWD=%s\n' "${PWD}"
  printf 'UV_CACHE_DIR=%s\n' "${UV_CACHE_DIR:-}"
  printf 'AINRF_WEBUI_API_KEY=%s\n' "${AINRF_WEBUI_API_KEY:-}"
  printf 'ARGS=%s\n' "$*"
} > "${log_path}"
sleep 0.2
"""
    _write_executable(bin_dir / "uv", fake_uv)
    _write_executable(bin_dir / "npm", fake_npm)
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


def test_webui_sh_sets_default_cache_and_generates_session_token(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result = _run_webui_script(repo_root, tmp_path, [])

    assert result.returncode == 0
    backend = _load_key_value_lines(tmp_path / "backend.log")
    frontend = _load_key_value_lines(tmp_path / "frontend.log")
    expected_hash = hashlib.sha256(frontend["AINRF_WEBUI_API_KEY"].encode("utf-8")).hexdigest()

    assert backend["PWD"] == str(repo_root)
    assert frontend["PWD"] == str(repo_root / "frontend")
    assert backend["UV_CACHE_DIR"] == "/tmp/uv-cache"
    assert frontend["UV_CACHE_DIR"] == "/tmp/uv-cache"
    assert frontend["AINRF_WEBUI_API_KEY"] != ""
    assert backend["AINRF_API_KEY_HASHES"] == expected_hash
    assert (
        backend["ARGS"]
        == f"run ainrf serve --host 127.0.0.1 --port 8000 --state-root {Path.home()}/.ainrf"
    )
    assert frontend["ARGS"] == "run dev -- --host 0.0.0.0 --port 5173"


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
    backend = _load_key_value_lines(tmp_path / "backend.log")
    frontend = _load_key_value_lines(tmp_path / "frontend.log")

    assert backend["UV_CACHE_DIR"] == "/var/tmp/custom-uv-cache"
    assert frontend["UV_CACHE_DIR"] == "/var/tmp/custom-uv-cache"
    assert frontend["AINRF_WEBUI_API_KEY"] == "fixed-test-token"
    assert backend["AINRF_API_KEY_HASHES"] == hashlib.sha256(b"fixed-test-token").hexdigest()
    assert (
        backend["ARGS"]
        == f"run ainrf serve --host 0.0.0.0 --port 8000 --state-root {Path.home()}/.ainrf"
    )
    assert frontend["ARGS"] == "run preview -- --host 0.0.0.0 --port 4173"

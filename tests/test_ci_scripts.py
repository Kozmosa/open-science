from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tomllib
from typing import cast

import pytest
import yaml

pytestmark = [pytest.mark.cli]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_tool_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    logger = """#!/usr/bin/env bash
set -euo pipefail
printf '%s %s\n' "$(basename "$0")" "$*" >> "${OPENSCIENCE_CI_TEST_LOG}"
"""
    _write_executable(bin_dir / "uv", logger)
    _write_executable(bin_dir / "npm", logger)
    _write_executable(bin_dir / "docker", logger + "exit 97\n")
    _write_executable(
        bin_dir / "curl",
        logger
        + """
if [[ " $* " == *" --write-out "* ]]; then
  if [[ "$*" == *"/v1/models"* ]]; then
    printf '401'
  else
    printf '404'
  fi
elif [[ "$*" == *"/staging-identity.json"* ]]; then
  printf '{"environment":"staging"}'
elif [[ "$*" == *"/build-info.json"* ]]; then
  printf '{"short_commit":"abc123","committed_at":"20260711-0100"}'
elif [[ "$*" == *"/health"* ]]; then
  printf '{"status":"ok","checks":{"database":{"status":"ok"},"filesystem":{"status":"ok"}}}'
else
  printf '<html>OpenScience</html>'
fi
""",
    )
    return bin_dir


def _run_repo_script(
    repo_root: Path,
    tmp_path: Path,
    script_name: str,
    args: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    log_path = tmp_path / "commands.log"
    env = os.environ.copy()
    env["PATH"] = f"{_fake_tool_bin(tmp_path)}:{env['PATH']}"
    env["OPENSCIENCE_CI_TEST_LOG"] = str(log_path)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [str(repo_root / "scripts" / script_name), *args],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, log_path


def _command_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_l0_runs_bounded_backend_and_frontend_checks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "ci.sh",
        ["l0"],
        env_overrides={"OPENSCIENCE_PYTEST_WORKERS": "3"},
    )

    assert result.returncode == 0, result.stderr
    commands = _command_lines(log_path)
    assert "uv run ruff check src tests scripts" in commands
    assert "uv run ruff format --check src tests scripts" in commands
    assert (
        "uv run pytest -m (unit or middleware or json_edge) and not concurrent and not db_race "
        "-q --timeout=30 -n 3"
    ) in commands
    assert "npm --prefix frontend run lint" in commands
    assert "npm --prefix frontend run test:run" in commands
    assert not any("ty check" in command for command in commands)
    assert not any("run build" in command for command in commands)


def test_l1_backend_partitions_parallel_and_serial_tests(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "ci.sh",
        ["l1-backend"],
        env_overrides={"OPENSCIENCE_PYTEST_WORKERS": "4"},
    )

    assert result.returncode == 0, result.stderr
    commands = _command_lines(log_path)
    assert "uv run ty check" in commands
    assert "uv run pytest tests/ -m not concurrent and not db_race -q --timeout=60 -n 4" in commands
    assert "uv run pytest tests/ -m concurrent or db_race -q --timeout=120 -n 0" in commands
    assert not any("-n auto" in command for command in commands)
    assert not any("--reruns" in command for command in commands)


def test_selective_unit_lane_keeps_race_tests_serial(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "test.sh",
        ["unit"],
        env_overrides={"OPENSCIENCE_PYTEST_WORKERS": "2"},
    )

    assert result.returncode == 0, result.stderr
    commands = _command_lines(log_path)
    assert (
        "uv run pytest -m (unit) and not concurrent and not db_race -q --timeout=30 -n 2"
    ) in commands
    assert ("uv run pytest -m (unit) and (concurrent or db_race) -q --timeout=120 -n 0") in commands


def test_backend_runner_rejects_unbounded_worker_value(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "test.sh",
        ["fast"],
        env_overrides={"OPENSCIENCE_PYTEST_WORKERS": "auto"},
    )

    assert result.returncode == 2
    assert "must be a positive integer" in result.stderr
    assert not log_path.exists()


def test_frontend_runner_rejects_unbounded_worker_value(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "ci.sh",
        ["l1-frontend"],
        env_overrides={"OPENSCIENCE_VITEST_WORKERS": "auto"},
    )

    assert result.returncode == 2
    assert "OPENSCIENCE_VITEST_WORKERS must be a positive integer" in result.stderr
    commands = _command_lines(log_path)
    assert "npm --prefix frontend run lint" in commands
    assert not any("test:run" in command or "run build" in command for command in commands)


def test_staging_lane_is_non_destructive_smoke_against_running_instance(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "test.sh",
        ["staging"],
        env_overrides={
            "OPENSCIENCE_STAGING_APP_URL": "http://127.0.0.1:27192",
            "OPENSCIENCE_STAGING_BACKEND_URL": "http://127.0.0.1:27000",
            "OPENSCIENCE_EXPECTED_BUILD_COMMIT": "abc123fedcba",
        },
    )

    assert result.returncode == 0, result.stderr
    commands = _command_lines(log_path)
    assert any("http://127.0.0.1:27192/staging-identity.json" in command for command in commands)
    assert any("http://127.0.0.1:27000/health" in command for command in commands)
    assert any("http://127.0.0.1:27192/api/health" in command for command in commands)
    assert any("http://127.0.0.1:27000/v1/models" in command for command in commands)
    assert any("http://127.0.0.1:27192/docs" in command for command in commands)
    assert any("http://127.0.0.1:27192/openapi.json" in command for command in commands)
    assert all(not command.startswith("uv ") for command in commands)
    assert all(not command.startswith("docker ") for command in commands)


def test_staging_test_lane_requires_expected_commit(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(repo_root, tmp_path, "test.sh", ["staging"])

    assert result.returncode == 2
    assert "OPENSCIENCE_EXPECTED_BUILD_COMMIT is required" in result.stderr
    assert not log_path.exists()


def test_staging_smoke_rejects_wrong_frontend_commit(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(
        repo_root,
        tmp_path,
        "staging.sh",
        ["smoke"],
        env_overrides={"OPENSCIENCE_EXPECTED_BUILD_COMMIT": "deadbeef"},
    )

    assert result.returncode != 0
    assert "does not match expected" in result.stderr
    assert all(not command.startswith("docker ") for command in _command_lines(log_path))


def test_ci_describe_exposes_five_layers(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, _ = _run_repo_script(repo_root, tmp_path, "ci.sh", ["describe"])

    assert result.returncode == 0
    for layer in ("L0", "L1", "L2", "L3", "L4"):
        assert layer in result.stdout


def test_l1_docs_builds_public_site(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, log_path = _run_repo_script(repo_root, tmp_path, "ci.sh", ["l1-docs"])

    assert result.returncode == 0, result.stderr
    assert _command_lines(log_path) == ["npm --prefix docs-site run build"]


def test_pytest_defaults_do_not_auto_scale_or_rerun() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert "-n auto" not in addopts
    assert "--reruns" not in addopts


def test_frontend_perf_suite_is_explicit() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    vitest_config = (repo_root / "frontend" / "vitest.config.ts").read_text(encoding="utf-8")
    package = json.loads((repo_root / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert "**/*.perf." not in vitest_config
    assert "OPENSCIENCE_VITEST_WORKERS" in vitest_config
    assert "maxWorkers: Number(workerSetting)" in vitest_config
    assert package["scripts"]["test:perf"] == "vitest run --config vitest.perf.config.ts"


def test_threaded_backend_tests_are_marked_serial_sensitive() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    unmarked = []
    for path in (repo_root / "tests").rglob("test_*.py"):
        source = path.read_text(encoding="utf-8")
        if "ThreadPoolExecutor" not in source and "threading.Thread" not in source:
            continue
        if "pytest.mark.concurrent" not in source and "pytest.mark.db_race" not in source:
            unmarked.append(path.relative_to(repo_root))

    assert unmarked == []


def test_frontend_msw_suites_do_not_bypass_unhandled_requests() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    frontend_tests = repo_root / "frontend" / "__tests__"

    bypassing_files = [
        path.relative_to(repo_root)
        for path in frontend_tests.rglob("*.test.ts*")
        if "onUnhandledRequest: 'bypass'" in path.read_text(encoding="utf-8")
        or 'onUnhandledRequest: "bypass"' in path.read_text(encoding="utf-8")
    ]

    assert bypassing_files == []


def test_l1_workflow_is_github_hosted_and_minimally_privileged() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = _mapping(yaml.safe_load(workflow_text))
    jobs = _mapping(workflow["jobs"])
    trigger_block = workflow_text.split("permissions:", maxsplit=1)[0]

    assert workflow["name"] == "L1 Deterministic Gate"
    assert _mapping(workflow["permissions"])["contents"] == "read"
    assert "\n  pull_request:" in trigger_block
    assert "\n  push:" in trigger_block
    assert set(jobs) == {"backend", "frontend", "docs"}
    for job in jobs.values():
        job_mapping = _mapping(job)
        assert job_mapping["runs-on"] == "ubuntu-24.04"
    assert "self-hosted" not in workflow_text
    assert "docker" not in workflow_text.lower()
    assert "bash scripts/ci.sh l1-backend" in workflow_text
    assert "bash scripts/ci.sh l1-frontend" in workflow_text
    assert "bash scripts/ci.sh l1-docs" in workflow_text
    assert 'UV_LOCKED: "1"' in workflow_text
    assert "persist-credentials: false" in workflow_text
    assert not (repo_root / ".github" / "workflows" / "perf-check.yml").exists()


def test_l1_command_enforces_locked_uv() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    ci_script = (repo_root / "scripts" / "ci.sh").read_text(encoding="utf-8")

    assert "export UV_LOCKED=1" in ci_script


def test_precommit_installs_pre_push_hook() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    config = _mapping(
        yaml.safe_load((repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    )

    assert config["default_install_hook_types"] == ["pre-commit", "pre-push"]

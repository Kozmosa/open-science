from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeploymentVersionInfo:
    short_commit: str | None = None
    committed_at: str | None = None


def resolve_deployment_version(startup_cwd: Path) -> DeploymentVersionInfo:
    env_info = _info_from_env()
    file_info = _info_from_file(startup_cwd)
    git_info = _info_from_git(startup_cwd)
    return DeploymentVersionInfo(
        short_commit=env_info.short_commit or file_info.short_commit or git_info.short_commit,
        committed_at=env_info.committed_at or file_info.committed_at or git_info.committed_at,
    )


def _info_from_env() -> DeploymentVersionInfo:
    short_commit = _normalize_commit(
        os.environ.get("AINRF_BUILD_COMMIT") or os.environ.get("VITE_AINRF_BUILD_COMMIT")
    )
    committed_at = _normalize_timestamp(
        os.environ.get("AINRF_BUILD_COMMITTED_AT")
        or os.environ.get("VITE_AINRF_BUILD_COMMITTED_AT")
    )
    return DeploymentVersionInfo(short_commit=short_commit, committed_at=committed_at)


def _info_from_file(startup_cwd: Path) -> DeploymentVersionInfo:
    for candidate in _build_info_candidates(startup_cwd):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        data = payload
        return DeploymentVersionInfo(
            short_commit=_normalize_commit(
                _coerce_string(data.get("short_commit")) or _coerce_string(data.get("shortCommit"))
            ),
            committed_at=_normalize_timestamp(
                _coerce_string(data.get("committed_at")) or _coerce_string(data.get("committedAt"))
            ),
        )
    return DeploymentVersionInfo()


def _build_info_candidates(startup_cwd: Path) -> tuple[Path, ...]:
    return (
        startup_cwd / "frontend" / "public" / "build-info.json",
        startup_cwd / "frontend" / "dist" / "build-info.json",
        Path("/opt/ainrf/frontend/dist/build-info.json"),
    )


def _info_from_git(startup_cwd: Path) -> DeploymentVersionInfo:
    short_commit = _run_git(
        startup_cwd,
        ["rev-parse", "--short=6", "HEAD"],
        normalize=_normalize_commit,
    )
    committed_at = _run_git(
        startup_cwd,
        ["show", "-s", "--format=%cd", "--date=format:%Y%m%d-%H%M", "HEAD"],
        normalize=_normalize_timestamp,
    )
    return DeploymentVersionInfo(short_commit=short_commit, committed_at=committed_at)

def _run_git(
    startup_cwd: Path,
    args: list[str],
    *,
    normalize: Callable[[str | None], str | None],
) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=startup_cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return normalize(result.stdout)


def _normalize_commit(value: str | None) -> str | None:
    normalized = _coerce_string(value)
    if normalized is None:
        return None
    return normalized[:6]


def _normalize_timestamp(value: str | None) -> str | None:
    return _coerce_string(value)


def _coerce_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None

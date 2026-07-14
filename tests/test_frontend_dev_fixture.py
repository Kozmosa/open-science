"""CLI and script contracts for the isolated frontend v2 development fixture."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from ainrf.api.config import hash_api_key
from ainrf.cli import app
from ainrf.domain import DomainService
from ainrf.domain_control import DomainCutoverController


pytestmark = [pytest.mark.cli]


def test_frontend_dev_prepare_is_idempotent_and_seeds_console_states(tmp_path: Path) -> None:
    state_root = tmp_path / "frontend-state"
    api_key = "fixture-api-key"
    artifact_sha = "c" * 64
    runner = CliRunner()
    args = [
        "frontend-dev",
        "prepare",
        "--state-root",
        str(state_root),
        "--api-key",
        api_key,
        "--artifact-sha",
        artifact_sha,
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = cast(dict[str, str], json.loads(first.stdout))
    second_payload = cast(dict[str, str], json.loads(second.stdout))
    assert second_payload == first_payload
    assert first_payload["state_root"] == str(state_root)
    assert first_payload["artifact_sha"] == artifact_sha

    status = DomainCutoverController(state_root).status()
    assert status.state == "v2"
    assert status.artifact_sha == artifact_sha
    config = json.loads((state_root / "config.json").read_text(encoding="utf-8"))
    assert config == {"api_key_hashes": [hash_api_key(api_key)]}

    domain = DomainService(state_root, artifact_sha=artifact_sha)
    user: dict[str, object] = {"id": "api-key-user", "role": "user"}
    projects = domain.project_console_summaries(user)
    workspaces = domain.workspace_console_entries(user)
    assert any(
        cast(dict[str, object], project["permissions"])["can_create_task"] is True
        for project in projects
    )
    assert any(project["attention_reasons"] == ["no_workspace"] for project in projects)
    assert any(workspace["can_execute"] is True for workspace in workspaces)
    assert any(
        workspace["cannot_execute_reason"] == "environment_grant_required"
        for workspace in workspaces
    )


def test_frontend_dev_fixture_refuses_repository_state_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "frontend-dev",
            "prepare",
            "--state-root",
            str(repository / "runtime-state"),
        ],
    )

    assert result.exit_code == 2
    assert "outside every Git worktree" in result.output


def test_frontend_dev_script_documents_non_l2_headless_boundary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "frontend-dev.sh"
    help_result = subprocess.run(
        ["bash", str(script), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    env_result = subprocess.run(
        ["bash", str(script), "env"],
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "OPENSCIENCE_FRONTEND_DEV_STATE_ROOT": str(tmp_path / "state"),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert help_result.returncode == 0
    assert "not an L2 or browser E2E gate" in help_result.stdout
    assert env_result.returncode == 0
    assert f"OPENSCIENCE_STATE_ROOT={tmp_path / 'state'}" in env_result.stdout
    assert "OPENSCIENCE_DOMAIN_MODEL_MODE=v2" in env_result.stdout

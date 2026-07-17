"""CLI and script contracts for the isolated frontend v2 development fixture."""

from __future__ import annotations

import json
import os
import stat
from contextlib import closing
import subprocess
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from ainrf.api.config import hash_api_key
from ainrf.auth.service import AuthService
from ainrf.cli import app
from ainrf.db import connect
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
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert second_payload == first_payload
    assert first_payload["state_root"] == str(state_root)
    assert first_payload["artifact_sha"] == artifact_sha
    assert first_payload["profile"] == "full"
    assert first_payload["fixture_version"] == 4
    assert first_payload["fault_profile"] == "none"
    assert first_payload["owner_user_id"] == "frontend-owner-user"
    assert set(first_payload["login_users"]) == {"owner", "editor", "viewer", "admin"}
    credentials_path = Path(first_payload["login_credentials_path"])
    assert credentials_path == state_root / "runtime" / "frontend-login-identities.json"
    assert stat.S_IMODE(credentials_path.stat().st_mode) == 0o600
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    assert credentials["schema_version"] == 1
    assert set(credentials["users"]) == {"owner", "editor", "viewer", "admin"}
    assert all(user["password"] for user in credentials["users"].values())
    assert all(user["password"] not in first.stdout for user in credentials["users"].values())
    assert first_payload["counts"] == {
        "attempts": 5,
        "papers": 8,
        "projects": 2,
        "tasks": 5,
        "workspaces": 2,
    }

    status = DomainCutoverController(state_root).status()
    assert status.state == "v2"
    assert status.artifact_sha == artifact_sha
    config = json.loads((state_root / "config.json").read_text(encoding="utf-8"))
    assert config == {"api_key_hashes": [hash_api_key(api_key)]}

    auth = AuthService(state_root=state_root)
    for label, expected_role in (
        ("owner", "member"),
        ("editor", "member"),
        ("viewer", "member"),
        ("admin", "admin"),
    ):
        identity = credentials["users"][label]
        login = auth.login(username=identity["username"], password=identity["password"])
        assert login["user"]["id"] == identity["user_id"]
        assert login["user"]["role"] == expected_role

    domain = DomainService(state_root, artifact_sha=artifact_sha)
    user: dict[str, object] = {"id": "frontend-owner-user", "role": "member"}
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
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        assert (
            conn.execute(
                "SELECT owner_user_id FROM projects WHERE project_id = 'project-frontend-dev'"
            ).fetchone()["owner_user_id"]
            == "frontend-owner-user"
        )
        assert {
            (str(row["user_id"]), str(row["role"]))
            for row in conn.execute(
                "SELECT user_id, role FROM project_members WHERE project_id = 'project-frontend-dev'"
            ).fetchall()
        } == {
            ("api-key-user", "editor"),
            ("frontend-editor-user", "editor"),
            ("frontend-viewer-user", "viewer"),
        }
        assert {
            str(row["owner_user_id"])
            for row in conn.execute("SELECT DISTINCT owner_user_id FROM tasks").fetchall()
        } == {"frontend-owner-user"}
        assert (
            conn.execute("SELECT owner_user_id FROM overview_snapshots").fetchone()["owner_user_id"]
            == "frontend-owner-user"
        )
    with closing(connect(state_root / "runtime" / "literature.sqlite3")) as conn:
        assert {
            str(row["user_id"])
            for row in conn.execute("SELECT DISTINCT user_id FROM literature_topics").fetchall()
        } == {"frontend-owner-user"}
        assert {
            str(row["user_id"])
            for row in conn.execute(
                "SELECT DISTINCT user_id FROM literature_user_paper_states"
            ).fetchall()
        } == {"frontend-owner-user"}
    with closing(connect(state_root / "runtime" / "auth.sqlite3")) as conn:
        active_grants = {
            str(row["user_id"])
            for row in conn.execute(
                """
                SELECT user_id FROM environment_access
                WHERE environment_id = 'environment-frontend-dev' AND status = 'active'
                """
            ).fetchall()
        }
        assert active_grants == {
            "api-key-user",
            "frontend-owner-user",
            "frontend-editor-user",
            "frontend-viewer-user",
            "frontend-admin-user",
        }


@pytest.mark.parametrize(
    ("profile", "expected_counts"),
    [
        (
            "empty",
            {"attempts": 0, "papers": 0, "projects": 0, "tasks": 0, "workspaces": 0},
        ),
        (
            "permissions",
            {"attempts": 5, "papers": 8, "projects": 5, "tasks": 5, "workspaces": 2},
        ),
        (
            "failures",
            {"attempts": 7, "papers": 8, "projects": 2, "tasks": 7, "workspaces": 2},
        ),
        (
            "large",
            {
                "attempts": 0,
                "papers": 250,
                "projects": 40,
                "tasks": 500,
                "workspaces": 120,
            },
        ),
    ],
)
def test_frontend_dev_profiles_seed_deterministic_bounded_states(
    tmp_path: Path,
    profile: str,
    expected_counts: dict[str, int],
) -> None:
    state_root = tmp_path / profile
    result = CliRunner().invoke(
        app,
        [
            "frontend-dev",
            "prepare",
            "--state-root",
            str(state_root),
            "--artifact-sha",
            "d" * 64,
            "--profile",
            profile,
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["profile"] == profile
    assert payload["counts"] == expected_counts
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM task_dispatch_outbox WHERE status IN ('pending', 'claimed')"
            ).fetchone()[0]
            == 0
        )
    with closing(connect(state_root / "runtime" / "literature.sqlite3")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM literature_work_items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM literature_outbox").fetchone()[0] == 0


def test_permissions_and_failures_profiles_expose_expected_projection_states(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    permissions_root = tmp_path / "permissions"
    failures_root = tmp_path / "failures"
    for state_root, profile in (
        (permissions_root, "permissions"),
        (failures_root, "failures"),
    ):
        result = runner.invoke(
            app,
            [
                "frontend-dev",
                "prepare",
                "--state-root",
                str(state_root),
                "--artifact-sha",
                "e" * 64,
                "--profile",
                profile,
            ],
        )
        assert result.exit_code == 0, result.output

    with closing(connect(permissions_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        members = conn.execute(
            """
            SELECT project_id, role, can_publish FROM project_members
            WHERE project_id LIKE 'project-permission-%'
            ORDER BY project_id
            """
        ).fetchall()
        assert [(row["role"], bool(row["can_publish"])) for row in members] == [
            ("editor", True),
            ("viewer", False),
        ]
        archived = conn.execute(
            "SELECT status FROM projects WHERE project_id = 'project-permission-archived'"
        ).fetchone()
        assert archived["status"] == "archived"

    with closing(connect(failures_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task_statuses = {
            str(row["status"]) for row in conn.execute("SELECT status FROM tasks").fetchall()
        }
        attempt_statuses = {
            str(row["status"])
            for row in conn.execute("SELECT status FROM agent_task_attempts").fetchall()
        }
        runtime_statuses = {
            str(row["status"])
            for row in conn.execute("SELECT status FROM agent_runtime_sessions").fetchall()
        }
        snapshot = conn.execute(
            "SELECT source_status, payload_json FROM overview_snapshots"
        ).fetchone()
        assert task_statuses == {
            "succeeded",
            "failed",
            "cancelled",
            "stopped",
            "launch_unknown",
            "stopped_by_project_archive",
            "stopped_permission_revoked",
        }
        assert attempt_statuses == task_statuses
        assert runtime_statuses == {
            "completed",
            "failed",
            "cancelled",
            "stopped",
            "launch_unknown",
        }
        assert snapshot["source_status"] == "partial"
        overview_payload = json.loads(snapshot["payload_json"])
        assert overview_payload["tasks_by_status"] == {"failed": 1, "succeeded": 1}
        assert overview_payload["display_cards"][1]["data"]["tasks"] == [
            {"task_id": "task-frontend-succeeded", "title": "Succeeded Task"}
        ]
        display_cards = overview_payload["display_cards"]
        assert {card["source_status"] for card in display_cards} >= {"failed", "stale"}
    with closing(connect(failures_root / "runtime" / "literature.sqlite3")) as conn:
        assert conn.execute("SELECT status FROM literature_checks").fetchone()["status"] == "failed"
        assert (
            conn.execute("SELECT status FROM literature_summaries").fetchone()["status"] == "failed"
        )


def test_frontend_dev_profile_change_requires_managed_reset(tmp_path: Path) -> None:
    state_root = tmp_path / "profile-change"
    runner = CliRunner()
    common = [
        "frontend-dev",
        "prepare",
        "--state-root",
        str(state_root),
        "--artifact-sha",
        "f" * 64,
    ]

    first = runner.invoke(app, [*common, "--profile", "full"])
    changed = runner.invoke(app, [*common, "--profile", "empty"])

    assert first.exit_code == 0, first.output
    assert changed.exit_code == 2
    assert "different profile" in changed.output


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
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
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
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "OPENSCIENCE_FRONTEND_DEV_STATE_ROOT": str(tmp_path / "state"),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert help_result.returncode == 0
    assert "outside\nL2 and browser E2E gates" in help_result.stdout
    assert env_result.returncode == 0
    assert f"env --profile full --state-root {tmp_path / 'state'}" in env_result.stdout

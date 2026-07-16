"""Deterministic worker contracts for marker-owned frontend fixtures."""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ainrf.cli import app
from ainrf.db import connect
from ainrf.development.frontend_fixture import prepare_frontend_dev_fixture
from ainrf.development.frontend_worker import FrontendFixtureWorker
from ainrf.domain import OverviewSnapshotService, TaskApplicationService
from ainrf.domain_control import DomainCutoverError
from ainrf.literature.tracking import LiteratureTrackingService


pytestmark = [pytest.mark.cli]


def _prepare(state_root: Path, artifact_sha: str) -> dict[str, object]:
    fixture = prepare_frontend_dev_fixture(
        state_root,
        artifact_sha=artifact_sha,
        api_key="fixture-worker-key",
        profile="full",
    )
    credentials = json.loads(Path(fixture.login_credentials_path).read_text(encoding="utf-8"))
    return credentials["users"]["owner"]


def test_frontend_fixture_worker_refuses_unmarked_or_mismatched_state(tmp_path: Path) -> None:
    with pytest.raises(DomainCutoverError, match="marker"):
        FrontendFixtureWorker(tmp_path / "unmarked", artifact_sha="a" * 64)

    state_root = tmp_path / "fixture"
    _prepare(state_root, "b" * 64)
    with pytest.raises(DomainCutoverError, match="artifact SHA"):
        FrontendFixtureWorker(state_root, artifact_sha="c" * 64)


def test_frontend_fixture_worker_completes_tasks_without_external_runtime(tmp_path: Path) -> None:
    state_root = tmp_path / "fixture"
    artifact_sha = "d" * 64
    owner = _prepare(state_root, artifact_sha)
    task = TaskApplicationService(state_root, artifact_sha=artifact_sha).create_task(
        {"id": owner["user_id"], "role": owner["auth_role"]},
        project_id="project-frontend-dev",
        workspace_id="workspace-frontend-primary",
        title="Fixture worker Task",
        prompt="Exercise the deterministic frontend worker.",
        researcher_type="vanilla",
        harness_engine="codex-app-server",
        idempotency_key="fixture-worker-task",
    )
    worker = FrontendFixtureWorker(state_root, artifact_sha=artifact_sha)

    result = asyncio.run(worker.run_once())
    worker.stop()

    assert result.outcome == "processed"
    assert result.task_outcome == "completed"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task_row = conn.execute(
            "SELECT status, latest_output_seq FROM tasks WHERE task_id = ?", (task["task_id"],)
        ).fetchone()
        attempt_row = conn.execute(
            "SELECT status, token_usage_json, cost_usd FROM agent_task_attempts WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        runtime_row = conn.execute(
            "SELECT status, engine_name FROM agent_runtime_sessions WHERE attempt_id = ?",
            (task["attempt_id"],),
        ).fetchone()
        outputs = conn.execute(
            "SELECT kind, content FROM task_outputs WHERE task_id = ? ORDER BY seq",
            (task["task_id"],),
        ).fetchall()
    assert task_row["status"] == "succeeded"
    assert task_row["latest_output_seq"] == 3
    assert attempt_row["status"] == "succeeded"
    assert json.loads(attempt_row["token_usage_json"])["source"] == "frontend-fixture"
    assert attempt_row["cost_usd"] == 0
    assert runtime_row["status"] == "completed"
    assert runtime_row["engine_name"] == "codex-app-server"
    assert any("without starting an external runtime" in row["content"] for row in outputs)


def test_frontend_fixture_worker_completes_literature_and_overview_jobs(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "fixture"
    artifact_sha = "e" * 64
    owner = _prepare(state_root, artifact_sha)
    owner_user_id = str(owner["user_id"])
    tracking = LiteratureTrackingService(state_root)
    tracking.initialize()
    check = tracking.create_check(
        user_id=owner_user_id,
        topic_ids=None,
        trigger="manual",
        idempotency_key="fixture-check",
    )
    summary = tracking.request_summary(
        owner_user_id,
        "paper-frontend-001",
        "en",
        idempotency_key="fixture-summary",
    )
    overview = OverviewSnapshotService(state_root, artifact_sha=artifact_sha)
    job = overview.request_refresh(
        owner_user_id,
        idempotency_key="fixture-overview-refresh",
    )
    worker = FrontendFixtureWorker(state_root, artifact_sha=artifact_sha)

    first = asyncio.run(worker.run_once())
    second = asyncio.run(worker.run_once())
    worker.stop()

    assert {first.literature_outcome, second.literature_outcome} == {
        "fetch_rss",
        "summarize",
    }
    assert tracking.get_check(owner_user_id, str(check["check_id"]))["status"] == "completed"
    completed_summary = tracking.get_summary(owner_user_id, "paper-frontend-001")
    assert completed_summary["summary_id"] == summary["summary_id"]
    assert completed_summary["status"] == "completed"
    assert completed_summary["text"].startswith("Deterministic fixture summary")
    completed_job = overview.get_job(owner_user_id, str(job["job_id"]))
    assert completed_job is not None
    assert completed_job["status"] == "succeeded"


def test_frontend_dev_worker_cli_runs_one_bounded_cycle(tmp_path: Path) -> None:
    state_root = tmp_path / "fixture"
    artifact_sha = "f" * 64
    _prepare(state_root, artifact_sha)

    result = CliRunner().invoke(
        app,
        [
            "frontend-dev",
            "worker",
            "--state-root",
            str(state_root),
            "--artifact-sha",
            artifact_sha,
            "--once",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "literature_outcome": "idle",
        "outcome": "idle",
        "task_outcome": "idle",
    }

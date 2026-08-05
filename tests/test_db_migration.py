from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainrf.db.migration import SchemaBaselineError, current_version, run_pending
from ainrf.db.retire_legacy import migrate, preflight, verify


pytestmark = [pytest.mark.unit]


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


@pytest.mark.parametrize(
    ("database", "version"),
    [("auth", 7), ("agentic_researcher", 33), ("literature", 7), ("terminal", 1)],
)
def test_fresh_install_uses_current_baseline(tmp_path: Path, database: str, version: int) -> None:
    path = tmp_path / f"{database}.sqlite3"
    with _connect(path) as connection:
        assert run_pending(connection, database) >= 1
        assert current_version(connection, database) == version
        assert run_pending(connection, database) == 0


def test_fresh_domain_baseline_contains_current_authority_only(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    with _connect(path) as connection:
        run_pending(connection, "agentic_researcher")
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"tasks", "task_turns", "turn_items", "runtime_executions"} <= tables
    assert not tables & {
        "agent_task_attempts",
        "agent_runtime_sessions",
        "task_dispatch_outbox",
        "task_outputs",
        "domain_cutover_state",
        "domain_migration_runs",
    }


def test_prebaseline_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "prebaseline.sqlite3"
    with _connect(path) as connection:
        connection.execute("CREATE TABLE legacy_table (id TEXT PRIMARY KEY)")
        connection.commit()
        with pytest.raises(SchemaBaselineError, match="pre-baseline schema"):
            run_pending(connection, "agentic_researcher")


def _make_retiring_state(state_root: Path, *, active_runtime: bool = False) -> Path:
    database = state_root / "runtime" / "agentic_researcher.sqlite3"
    database.parent.mkdir(parents=True)
    with _connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL);
            INSERT INTO _schema_version VALUES ('agentic_researcher', 32);
            CREATE TABLE domain_maintenance_state (
                singleton INTEGER PRIMARY KEY, is_active INTEGER NOT NULL
            );
            INSERT INTO domain_maintenance_state VALUES (1, 1);
            CREATE TABLE domain_cutover_state (
                singleton INTEGER PRIMARY KEY, state TEXT NOT NULL, first_v2_write_at TEXT
            );
            INSERT INTO domain_cutover_state VALUES (1, 'v2', '2026-08-05T00:00:00+00:00');
            CREATE TABLE agent_runtime_sessions (runtime_session_id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE agent_task_attempts (attempt_id TEXT PRIMARY KEY, task_id TEXT);
            CREATE TABLE task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY);
            CREATE TABLE task_outputs (output_id TEXT PRIMARY KEY);
            CREATE TABLE task_attempt_control_requests (control_request_id TEXT PRIMARY KEY);
            CREATE TABLE domain_cutover_events (event_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_issues (issue_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_record_results (result_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_resolutions (resolution_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_runs (run_id TEXT PRIMARY KEY);
            CREATE TABLE legacy_domain_records (
                legacy_record_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_path TEXT,
                source_record_id TEXT,
                source_payload_sha256 TEXT,
                reason TEXT
            );
            """
        )
        if active_runtime:
            connection.execute("INSERT INTO agent_runtime_sessions VALUES ('runtime-1', 'running')")
        connection.execute(
            "INSERT INTO legacy_domain_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-1",
                "run-1",
                "task",
                "{}",
                "2026-08-05T00:00:00+00:00",
                None,
                None,
                None,
                "audit",
            ),
        )
        connection.commit()
    return database


def test_retirement_migration_drops_legacy_tables_and_keeps_audit(tmp_path: Path) -> None:
    database = _make_retiring_state(tmp_path)
    report = migrate(tmp_path)
    assert report.ready
    assert verify(tmp_path).ready
    with _connect(database) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "legacy_domain_records" in tables
        assert "agent_task_attempts" not in tables
        assert (
            connection.execute("SELECT legacy_record_id FROM legacy_domain_records").fetchone()[0]
            == "legacy-1"
        )


def test_retirement_preflight_blocks_active_runtime(tmp_path: Path) -> None:
    _make_retiring_state(tmp_path, active_runtime=True)
    report = preflight(tmp_path)
    assert not report.ready
    assert "legacy runtime sessions are still active" in report.blockers[0]

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from ainrf.db.migration import SchemaBaselineError, current_version, run_pending
from ainrf.db.retire_legacy import migrate, preflight, verify


pytestmark = [pytest.mark.unit]


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _build_v33_artifact(path: Path) -> None:
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('agentic_researcher', 33)")
        connection.commit()


@pytest.mark.parametrize(
    ("database", "version"),
    [("auth", 7), ("agentic_researcher", 34), ("literature", 7), ("terminal", 1)],
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


def test_fresh_baseline_version_write_failure_rolls_back_all_schema(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    with _connect(path) as connection:
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        denied = False

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version":
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert denied
        assert not connection.in_transaction
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name != '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version

    with _connect(path) as reopened:
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name != '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == before_user_version


def test_fresh_baseline_honors_caller_transaction_success_and_failure(tmp_path: Path) -> None:
    success_path = tmp_path / "success.sqlite3"
    with _connect(success_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (1)")
        assert run_pending(connection, "agentic_researcher") == 2
        assert connection.in_transaction
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (2)")
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 1
        connection.commit()

    with _connect(success_path) as connection:
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 2
        assert current_version(connection, "agentic_researcher") == 34

    failure_path = tmp_path / "failure.sqlite3"
    with _connect(failure_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (3)")
        denied = False

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version":
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert denied
        assert connection.in_transaction
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'tasks'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (4)")
        connection.commit()

    with _connect(failure_path) as connection:
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 4
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'tasks'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )


def test_existing_v33_domain_migrates_cancellation_guards(tmp_path: Path) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    artifact_path = tmp_path / "v33-artifact.sqlite3"
    with _connect(fresh_path) as fresh:
        assert run_pending(fresh, "agentic_researcher") == 2
        assert current_version(fresh, "agentic_researcher") == 34
        assert fresh.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        fresh_schema = {
            (str(row["type"]), str(row["name"])): str(row["sql"])
            for row in fresh.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name IN ('turn_submissions', 'next_turn_transition_guard')"
            )
        }
    _build_v33_artifact(artifact_path)
    with _connect(artifact_path) as connection:
        assert run_pending(connection, "agentic_researcher") == 1
        assert current_version(connection, "agentic_researcher") == 34
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        artifact_schema = {
            (str(row["type"]), str(row["name"])): str(row["sql"])
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name IN ('turn_submissions', 'next_turn_transition_guard')"
            )
        }
    assert artifact_schema == fresh_schema
    assert (
        "status = 'delivery_unknown' AND finished_at IS NULL"
        in artifact_schema[("table", "turn_submissions")]
    )
    assert (
        "OLD.status = 'ready' AND NEW.status = 'cancelled'"
        in artifact_schema[("trigger", "next_turn_transition_guard")]
    )


def test_run_pending_rolls_back_when_nested_savepoint_release_is_denied(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    _build_v33_artifact(path)
    with _connect(path) as connection:
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_version = current_version(connection, "agentic_researcher")
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (1)")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (2)")

        def deny_release(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_SAVEPOINT and arg1 == "RELEASE"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_release)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert connection.in_transaction
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 2
        assert current_version(connection, "agentic_researcher") == before_version == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )
        assert run_pending(connection, "agentic_researcher") == 1
        assert current_version(connection, "agentic_researcher") == 34
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 2
        connection.commit()


def test_run_pending_rolls_back_when_schema_version_write_is_denied(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    _build_v33_artifact(path)
    with _connect(path) as connection:
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_version = current_version(connection, "agentic_researcher")
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert current_version(connection, "agentic_researcher") == before_version == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )


def test_migration_034_rolls_back_trigger_and_version_on_injected_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('agentic_researcher', 33)")
        connection.commit()
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

        def deny_trigger_creation(
            action: int,
            _arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_CREATE_TRIGGER
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_trigger_creation)
        with pytest.raises(sqlite3.DatabaseError):
            try:
                run_pending(connection, "agentic_researcher")
            except BaseException:
                connection.rollback()
                raise
        connection.set_authorizer(None)
        assert current_version(connection, "agentic_researcher") == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )


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


def test_retirement_migration_removes_retired_telemetry_payloads(tmp_path: Path) -> None:
    _make_retiring_state(tmp_path)
    runtime_root = tmp_path / "runtime"
    telemetry_path = runtime_root / "domain_telemetry.sqlite3"
    with _connect(telemetry_path) as connection:
        connection.executescript(
            """
            CREATE TABLE domain_telemetry_counter_totals (
                metric_name TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                value REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(metric_name, labels_json)
            );
            CREATE TABLE domain_telemetry_snapshots (
                singleton INTEGER PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            INSERT INTO domain_telemetry_counter_totals VALUES (
                'ainrf_domain_legacy_write_attempts_total', '{"source":"legacy_json"}',
                1, '2026-08-05T00:00:00+00:00'
            );
            INSERT INTO domain_telemetry_counter_totals VALUES (
                'ainrf_domain_idempotency_requests_total', '{"outcome":"accepted"}',
                2, '2026-08-05T00:00:00+00:00'
            );
            INSERT INTO domain_telemetry_snapshots VALUES (
                1, 2, '2026-08-05T00:00:00+00:00', '{"schema_version":2}'
            );
            """
        )
        connection.commit()
    anchor_path = runtime_root / "domain_telemetry_anchor.json"
    anchor_path.write_text('{"schema_version":2}\n', encoding="utf-8")

    assert migrate(tmp_path).ready

    with _connect(telemetry_path) as connection:
        metric_names = {
            str(row[0])
            for row in connection.execute("SELECT metric_name FROM domain_telemetry_counter_totals")
        }
        snapshot_count = int(
            connection.execute("SELECT COUNT(*) FROM domain_telemetry_snapshots").fetchone()[0]
        )
    assert metric_names == {"ainrf_domain_idempotency_requests_total"}
    assert snapshot_count == 0
    assert not anchor_path.exists()

    with _connect(telemetry_path) as connection:
        connection.execute(
            "INSERT INTO domain_telemetry_counter_totals VALUES (?, ?, ?, ?)",
            (
                "ainrf_domain_legacy_write_attempts_total",
                '{"source":"legacy_json"}',
                1,
                "2026-08-05T00:00:00+00:00",
            ),
        )
        connection.commit()
    report = verify(tmp_path)
    assert not report.ready
    assert "retired telemetry counter remains" in report.blockers


def test_retirement_preflight_blocks_active_runtime(tmp_path: Path) -> None:
    _make_retiring_state(tmp_path, active_runtime=True)
    report = preflight(tmp_path)
    assert not report.ready
    assert "legacy runtime sessions are still active" in report.blockers[0]

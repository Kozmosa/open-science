from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainrf.db.migration import (
    MigrationRegistry,
    current_version,
    ensure_schema_table,
    run_pending,
)

pytestmark = [pytest.mark.unit]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level="IMMEDIATE")
    conn.row_factory = sqlite3.Row
    return conn


class TestBaselineCreatesTables:
    """Fresh database: run migrations, verify all expected tables exist."""

    @pytest.mark.parametrize(
        "db_name,expected_tables",
        [
            ("auth", {"users", "refresh_tokens", "project_collaborators", "environment_access", "login_attempts"}),
            ("sessions", {"task_sessions", "task_attempts"}),
            ("agentic_researcher", {"tasks", "task_outputs"}),
            ("literature", {"literature_subscriptions", "literature_papers", "literature_subscription_papers"}),
            ("terminal", {"user_environment_bindings", "user_session_pairs"}),
        ],
    )
    def test_tables_created(self, tmp_path: Path, db_name: str, expected_tables: set[str]) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401 — register all migrations

        with _connect(db_file) as conn:
            run_pending(conn, db_name)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        # _schema_version is always created
        assert expected_tables <= tables

    @pytest.mark.parametrize(
        "db_name,expected_count",
        [
            ("auth", 4),
            ("sessions", 3),
            ("agentic_researcher", 5),
            ("literature", 3),
            ("terminal", 1),
        ],
    )
    def test_version_number(self, tmp_path: Path, db_name: str, expected_count: int) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401

        with _connect(db_file) as conn:
            applied = run_pending(conn, db_name)
        assert applied == expected_count

        with _connect(db_file) as conn:
            assert current_version(conn, db_name) == expected_count


class TestIdempotentRerun:
    """Running migrations twice: second run returns 0 pending, tables unchanged."""

    def test_rerun_returns_zero(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401

        with _connect(db_file) as conn:
            first = run_pending(conn, "auth")
        with _connect(db_file) as conn:
            second = run_pending(conn, "auth")
        assert first > 0
        assert second == 0

    def test_tables_unchanged(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401

        with _connect(db_file) as conn:
            run_pending(conn, "auth")
            tables_before = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        with _connect(db_file) as conn:
            run_pending(conn, "auth")
            tables_after = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert tables_before == tables_after


class TestUpgradeFromV0:
    """Simulate upgrading a database that only has baseline tables."""

    def test_auth_adds_must_change_password(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migrations.auth import migration_001_baseline

        # Create baseline only
        with _connect(db_file) as conn:
            migration_001_baseline(conn)
            conn.commit()
            # Confirm must_change_password does NOT exist yet
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
            assert "must_change_password" not in cols

        # Run all pending — should add the column
        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            from ainrf.db.migration import registry

            pending = registry.get_pending("auth", 1)
            assert len(pending) == 3  # migration_002 + migration_003 + migration_004
            run_pending(conn, "auth")
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
            assert "must_change_password" in cols

    def test_sessions_adds_owner_user_id(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migrations.sessions import migration_001_baseline

        with _connect(db_file) as conn:
            migration_001_baseline(conn)
            conn.commit()
            cols = [r[1] for r in conn.execute("PRAGMA table_info(task_sessions)")]
            assert "owner_user_id" not in cols

        with _connect(db_file) as conn:
            run_pending(conn, "sessions")
            cols = [r[1] for r in conn.execute("PRAGMA table_info(task_sessions)")]
            assert "owner_user_id" in cols


class TestMigrationRollbackOnFailure:
    """If a migration raises, the schema version must NOT advance."""

    def test_failure_does_not_advance_version(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        reg = MigrationRegistry()

        @reg.register("testdb")
        def migration_001_ok(conn: sqlite3.Connection) -> None:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS foo (id TEXT PRIMARY KEY)"
            )

        @reg.register("testdb")
        def migration_002_bad(conn: sqlite3.Connection) -> None:
            raise RuntimeError("boom")

        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            version_before = current_version(conn, "testdb")
            # Run first migration only
            pending = reg.get_pending("testdb", version_before)
            pending[0](conn)
            from ainrf.db.migration import set_version

            set_version(conn, "testdb", 1)
            conn.commit()

        with _connect(db_file) as conn:
            # Try running all — should fail on migration_002
            with pytest.raises(RuntimeError, match="boom"):
                run_pending(conn, "testdb", reg=reg)
            # Version should still be 1
            assert current_version(conn, "testdb") == 1
            # Table from migration_001 should exist
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "foo" in tables


class TestSchemaVersionTable:
    """Verify _schema_version table is created correctly."""

    def test_schema_table_created(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        import ainrf.db.migrations  # noqa: F401

        with _connect(db_file) as conn:
            run_pending(conn, "terminal")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "_schema_version" in tables

    def test_default_version_is_zero(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            assert current_version(conn, "nonexistent") == 0

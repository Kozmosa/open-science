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
            (
                "auth",
                {
                    "users",
                    "refresh_tokens",
                    "project_collaborators",
                    "environment_access",
                    "login_attempts",
                },
            ),
            ("sessions", {"task_sessions", "task_attempts"}),
            ("agentic_researcher", {"tasks", "task_outputs"}),
            (
                "literature",
                {
                    "literature_subscriptions",
                    "literature_papers",
                    "literature_subscription_papers",
                    "literature_topics",
                    "literature_catalog_papers",
                    "literature_paper_versions",
                    "literature_work_items",
                    "literature_outbox",
                    "literature_source_snapshots",
                },
            ),
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
            ("auth", 6),
            ("sessions", 3),
            ("agentic_researcher", 13),
            ("literature", 5),
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
            assert len(pending) == 5  # migration_002 through migration_006
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

    def test_literature_v3_data_becomes_topics_and_user_states(self, tmp_path: Path) -> None:
        db_file = tmp_path / "literature.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migrations.literature import (
            migration_001_baseline,
            migration_002_summary_cache_fields,
            migration_003_global_papers_and_scheduler_fields,
        )

        with _connect(db_file) as conn:
            migration_001_baseline(conn)
            migration_002_summary_cache_fields(conn)
            migration_003_global_papers_and_scheduler_fields(conn)
            conn.execute(
                """INSERT INTO literature_subscriptions (
                    subscription_id, user_id, label, keywords_json, arxiv_categories_json, created_at
                ) VALUES ('sub-ai', 'user-1', 'AI', '[\"agent\"]', '[\"cs.AI\"]', '2026-01-01T00:00:00+00:00')"""
            )
            conn.execute(
                """INSERT INTO literature_papers (
                    paper_id, title, authors_json, abstract, published_at, arxiv_category, created_at
                ) VALUES ('2401.00001', 'Agent paper', '[]', 'agent', '', 'cs.AI', '2026-01-01T00:00:00+00:00')"""
            )
            conn.execute(
                """INSERT INTO literature_subscription_papers (
                    subscription_id, paper_id, is_read, is_converted_to_task, created_at
                ) VALUES ('sub-ai', '2401.00001', 1, 0, '2026-01-01T00:00:00+00:00')"""
            )
            ensure_schema_table(conn)
            from ainrf.db.migration import set_version

            set_version(conn, "literature", 3)
            conn.commit()

        with _connect(db_file) as conn:
            assert run_pending(conn, "literature") == 2
            topic = conn.execute(
                "SELECT status, is_active FROM literature_topics WHERE topic_id = 'sub-ai'"
            ).fetchone()
            state = conn.execute(
                "SELECT is_read FROM literature_user_paper_states WHERE user_id = 'user-1' AND paper_id = 'arxiv:2401.00001'"
            ).fetchone()
        assert tuple(topic) == ("active", 1)
        assert state[0] == 1


class TestMigrationRollbackOnFailure:
    """If a migration raises, the schema version must NOT advance."""

    def test_failure_does_not_advance_version(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.sqlite3"
        reg = MigrationRegistry()

        @reg.register("testdb")
        def migration_001_ok(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE IF NOT EXISTS foo (id TEXT PRIMARY KEY)")

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


class TestEnvironmentGrantVersioning:
    def test_legacy_grants_upgrade_to_active_versioned_records(self, tmp_path: Path) -> None:
        db_file = tmp_path / "auth.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migration import set_version
        from ainrf.db.migrations.auth import migration_001_baseline

        granted_at = "2026-07-12T00:00:00+00:00"
        with _connect(db_file) as conn:
            migration_001_baseline(conn)
            conn.execute(
                """
                INSERT INTO environment_access (
                    environment_id, user_id, max_concurrent_tasks, granted_by_user_id, granted_at
                ) VALUES ('environment-1', 'user-1', 2, 'admin-1', ?)
                """,
                (granted_at,),
            )
            ensure_schema_table(conn)
            set_version(conn, "auth", 1)
            conn.commit()

        with _connect(db_file) as conn:
            assert run_pending(conn, "auth") == 5
            columns = {
                row[1]: row
                for row in conn.execute("PRAGMA table_info(environment_access)").fetchall()
            }
            assert {"grant_version", "status", "updated_at", "revoked_at"} <= columns.keys()
            assert columns["grant_version"][3] == 1
            assert columns["status"][3] == 1
            grant = conn.execute(
                """
                SELECT grant_version, status, updated_at, revoked_at
                FROM environment_access
                WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                """
            ).fetchone()
            assert tuple(grant) == (1, "active", granted_at, None)
            audit = conn.execute(
                """
                SELECT grant_version, event_type, actor_user_id
                FROM environment_access_audit_events
                WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                """
            ).fetchone()
            assert audit is not None
            assert tuple(audit) == (1, "granted", "admin-1")

            conn.execute(
                """
                UPDATE environment_access
                SET grant_version = grant_version + 1,
                    status = 'revoked',
                    updated_at = '2026-07-12T01:00:00+00:00',
                    revoked_at = '2026-07-12T01:00:00+00:00'
                WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                """
            )
            revoked = conn.execute(
                """
                SELECT grant_version, status, revoked_at
                FROM environment_access
                WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                """
            ).fetchone()
            active = conn.execute(
                """
                SELECT 1 FROM environment_access
                WHERE environment_id = 'environment-1' AND user_id = 'user-1' AND status = 'active'
                """
            ).fetchone()
            with pytest.raises(sqlite3.IntegrityError, match="grant_version must increase"):
                conn.execute(
                    """
                    UPDATE environment_access SET grant_version = 2
                    WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                    """
                )
            with pytest.raises(sqlite3.IntegrityError, match="status must be active or revoked"):
                conn.execute(
                    """
                    UPDATE environment_access SET status = 'disabled'
                    WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                    """
                )
            with pytest.raises(sqlite3.IntegrityError, match="retained for audit history"):
                conn.execute(
                    """
                    DELETE FROM environment_access
                    WHERE environment_id = 'environment-1' AND user_id = 'user-1'
                    """
                )
        assert tuple(revoked) == (2, "revoked", "2026-07-12T01:00:00+00:00")
        assert active is None

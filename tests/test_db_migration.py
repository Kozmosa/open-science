from __future__ import annotations

import json
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
                    "literature_research_task_intents",
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
            ("auth", 7),
            ("sessions", 3),
            ("agentic_researcher", 25),
            ("literature", 6),
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
            assert len(pending) == 6  # migration_002 through migration_007
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

    def test_overview_retry_schema_upgrades_populated_job_and_card_history(
        self, tmp_path: Path
    ) -> None:
        """The B10 retry migration must preserve its FK child during rebuild."""

        db_file = tmp_path / "agentic.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migration import registry, set_version

        now = "2026-07-12T00:00:00+00:00"
        with _connect(db_file) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            ensure_schema_table(conn)
            for migration in registry.get_pending("agentic_researcher", 0)[:20]:
                migration(conn)
            set_version(conn, "agentic_researcher", 20)
            conn.execute(
                """
                INSERT INTO overview_refresh_jobs (
                    job_id, owner_user_id, trigger, scheduled_for_date, status,
                    attempt_count, created_at, updated_at
                ) VALUES ('overview-job-1', 'owner-1', 'scheduled', '2026-07-12',
                    'succeeded', 1, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO overview_refresh_card_states (
                    owner_user_id, card_id, last_job_id, status, data_cutoff_at, updated_at
                ) VALUES ('owner-1', 'domain', 'overview-job-1', 'ok', ?, ?)
                """,
                (now, now),
            )
            conn.commit()

        with _connect(db_file) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            assert run_pending(conn, "agentic_researcher") == 5
            columns = {
                str(row["name"]) for row in conn.execute("PRAGMA table_info(overview_refresh_jobs)")
            }
            assert {"retry_count", "next_retry_at", "last_failure_at"} <= columns
            card = conn.execute(
                "SELECT last_job_id FROM overview_refresh_card_states WHERE owner_user_id = 'owner-1'"
            ).fetchone()
            assert card is not None and card["last_job_id"] == "overview-job-1"
            conn.execute(
                """
                UPDATE overview_refresh_jobs
                SET status = 'retry_wait', retry_count = 1, next_retry_at = ?
                WHERE job_id = 'overview-job-1'
                """,
                ("2026-07-12T00:01:00+00:00",),
            )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    def test_context_upgrade_never_invents_historic_fragment_provenance(
        self, tmp_path: Path
    ) -> None:
        """Versions created before B4 manifests remain explicitly unresolved.

        Earlier Context schemas stored live Project Fragments but no
        Version-to-Fragment relation.  An upgrade must preserve those records
        without presenting the current live Fragment as evidence that an old
        Version was reviewed with it.
        """

        db_file = tmp_path / "agentic.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migration import registry, set_version

        now = "2026-07-12T00:00:00+00:00"
        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            for migration in registry.get_pending("agentic_researcher", 0)[:20]:
                migration(conn)
            set_version(conn, "agentic_researcher", 20)
            conn.execute(
                """INSERT INTO projects (
                       project_id, owner_user_id, name, status, is_default, created_at, updated_at
                   ) VALUES ('project-legacy-context', 'owner-1', 'Legacy Context', 'active', 0, ?, ?)""",
                (now, now),
            )
            conn.execute(
                """INSERT INTO project_context_versions (
                       context_version_id, project_id, content, fingerprint, is_active,
                       created_by_user_id, created_at
                   ) VALUES ('context-version-legacy', 'project-legacy-context', 'Legacy brief',
                       'legacy-version-fingerprint', 1, 'owner-1', ?)""",
                (now,),
            )
            conn.execute(
                """INSERT INTO project_context_fragments (
                       fragment_id, project_id, source_type, content, created_at
                   ) VALUES ('fragment-current-live', 'project-legacy-context', 'workspace',
                       'A live fragment that was not historically pinned', ?)""",
                (now,),
            )
            conn.commit()

        with _connect(db_file) as conn:
            assert run_pending(conn, "agentic_researcher") == 5
            version = conn.execute(
                """SELECT fragment_manifest_json FROM project_context_versions
                   WHERE context_version_id = 'context-version-legacy'"""
            ).fetchone()
            provenance = conn.execute(
                """SELECT fragment_provenance_status, evidence_json
                   FROM project_context_version_provenance
                   WHERE context_version_id = 'context-version-legacy'"""
            ).fetchone()
            fragment = conn.execute(
                """SELECT 1 FROM project_context_fragments
                   WHERE fragment_id = 'fragment-current-live'"""
            ).fetchone()

        assert version is not None and version["fragment_manifest_json"] == "[]"
        assert provenance is not None
        assert provenance["fragment_provenance_status"] == "attention_needed"
        evidence = json.loads(str(provenance["evidence_json"]))
        assert evidence["kind"] == "legacy_fragment_provenance_unavailable"
        assert evidence["recorded_version_fingerprint"] == "legacy-version-fingerprint"
        assert fragment is not None

    def test_context_candidate_upgrade_renames_pending_and_guards_new_proposals(
        self, tmp_path: Path
    ) -> None:
        """The B4 status correction preserves legacy audit rows but seals new writes."""

        db_file = tmp_path / "agentic.sqlite3"
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migration import registry, set_version

        now = "2026-07-13T00:00:00+00:00"
        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            for migration in registry.get_pending("agentic_researcher", 0)[:23]:
                migration(conn)
            set_version(conn, "agentic_researcher", 23)
            conn.execute(
                """INSERT INTO projects (
                       project_id, owner_user_id, name, status, is_default, created_at, updated_at
                   ) VALUES ('project-candidate-legacy', 'owner-1', 'Candidate project',
                       'active', 0, ?, ?)""",
                (now, now),
            )
            conn.execute(
                """INSERT INTO project_context_candidates (
                       candidate_id, project_id, content, status, created_at
                   ) VALUES ('candidate-legacy', 'project-candidate-legacy', 'legacy finding',
                       'pending', ?)""",
                (now,),
            )
            conn.commit()

        with _connect(db_file) as conn:
            assert run_pending(conn, "agentic_researcher") == 2
            legacy = conn.execute(
                "SELECT status FROM project_context_candidates WHERE candidate_id = 'candidate-legacy'"
            ).fetchone()
            assert legacy is not None and legacy["status"] == "proposed"
            with pytest.raises(sqlite3.IntegrityError, match="candidate source"):
                conn.execute(
                    """INSERT INTO project_context_candidates (
                           candidate_id, project_id, content, status, created_at,
                           created_by_user_id
                       ) VALUES ('candidate-unprovenanced', 'project-candidate-legacy',
                           'unsafe finding', 'proposed', ?, 'owner-1')""",
                    (now,),
                )

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
            assert run_pending(conn, "literature") == 3
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


class TestMaintenanceBarrierRepair:
    """Historical schema markers must not hide missing cutover barrier DDL."""

    @staticmethod
    def _create_marked_v24_database(db_file: Path) -> None:
        import ainrf.db.migrations  # noqa: F401
        from ainrf.db.migration import registry, set_version

        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            for migration in registry.get_pending("agentic_researcher", 0)[:24]:
                migration(conn)
            set_version(conn, "agentic_researcher", 24)
            conn.commit()

    def test_legacy_schema_marker_recreates_missing_maintenance_barrier(
        self, state_root: Path
    ) -> None:
        from ainrf.domain_control import DomainMaintenanceService

        db_file = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._create_marked_v24_database(db_file)
        with _connect(db_file) as conn:
            conn.execute("DROP TABLE domain_write_participants")
            conn.execute("DROP TABLE domain_maintenance_mutations")
            conn.execute("DROP TABLE domain_maintenance_state")
            conn.commit()

        status = DomainMaintenanceService(state_root).status()

        assert status.maintenance_epoch == 0
        assert not status.is_active
        with _connect(db_file) as conn:
            assert current_version(conn, "agentic_researcher") == 25
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert {
                "domain_maintenance_state",
                "domain_maintenance_mutations",
                "domain_write_participants",
            } <= tables

    def test_repair_refuses_to_recreate_a_prepared_cutover_barrier(self, tmp_path: Path) -> None:
        db_file = tmp_path / "agentic.sqlite3"
        with _connect(db_file) as conn:
            ensure_schema_table(conn)
            from ainrf.db.migration import set_version

            set_version(conn, "agentic_researcher", 24)
            conn.execute(
                """
                CREATE TABLE domain_cutover_state (
                    singleton INTEGER PRIMARY KEY,
                    state TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO domain_cutover_state (singleton, state) VALUES (1, 'prepared')"
            )
            conn.commit()

        with _connect(db_file) as conn:
            with pytest.raises(RuntimeError, match="only before domain cutover"):
                run_pending(conn, "agentic_researcher")
            assert current_version(conn, "agentic_researcher") == 24

    def test_rejects_schema_versions_newer_than_this_binary(self, tmp_path: Path) -> None:
        db_file = tmp_path / "agentic.sqlite3"
        self._create_marked_v24_database(db_file)
        with _connect(db_file) as conn:
            from ainrf.db.migration import set_version

            set_version(conn, "agentic_researcher", 26)
            conn.commit()

        with _connect(db_file) as conn:
            with pytest.raises(
                RuntimeError, match="unsupported agentic_researcher schema version 26"
            ):
                run_pending(conn, "agentic_researcher")

    def test_active_maintenance_refuses_pending_sibling_database_migrations(
        self, state_root: Path
    ) -> None:
        """A restarting auth/Literature service cannot mutate sources mid-cutover."""

        from ainrf.domain_control import DomainMaintenanceService

        control_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        with _connect(control_path) as conn:
            run_pending(conn, "agentic_researcher")
        DomainMaintenanceService(state_root).enter(actor_id="operator", reason="cutover")

        auth_path = state_root / "runtime" / "auth.sqlite3"
        with _connect(auth_path) as conn:
            with pytest.raises(
                RuntimeError, match="maintenance is active; refusing auth migration"
            ):
                run_pending(conn, "auth")
            assert "_schema_version" not in {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }


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
            assert run_pending(conn, "auth") == 6
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

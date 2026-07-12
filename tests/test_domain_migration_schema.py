"""Schema coverage for durable, per-record domain import audit results."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect
from ainrf.db.migration import registry
from ainrf.db.migrations.agentic_researcher import migration_013_domain_migration_record_audit

pytestmark = [pytest.mark.unit]


def _apply_through_migration_012(conn: sqlite3.Connection) -> None:
    for migration in registry.get_pending("agentic_researcher", 0)[:12]:
        migration(conn)


def _insert_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO domain_migration_runs
            (run_id, mode, source_manifest_json, code_version, status, started_at)
        VALUES (?, 'apply', '{}', 'test', 'running', '2026-07-12T00:00:00+00:00')
        """,
        (run_id,),
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def test_record_results_have_a_terminal_status_and_unique_source_identity(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "domain.sqlite3")) as conn:
        _apply_through_migration_012(conn)
        migration_013_domain_migration_record_audit(conn)
        _insert_run(conn, "run-1")

        assert {
            "record_result_id",
            "run_id",
            "source_path",
            "record_type",
            "source_record_id",
            "source_payload_sha256",
            "status",
            "target_id",
            "detail",
            "created_at",
            "updated_at",
        } <= _columns(conn, "domain_migration_record_results")

        values = (
            "result-1",
            "run-1",
            "runtime/projects.json",
            "project",
            "project-1",
            "a" * 64,
            "imported",
            "project-1",
            "retained legacy project ID",
            "2026-07-12T00:00:00+00:00",
            "2026-07-12T00:00:00+00:00",
        )
        conn.execute(
            """
            INSERT INTO domain_migration_record_results (
                record_result_id, run_id, source_path, record_type, source_record_id,
                source_payload_sha256, status, target_id, detail, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_migration_record_results (
                    record_result_id, run_id, source_path, record_type, source_record_id,
                    source_payload_sha256, status, created_at, updated_at
                ) VALUES ('result-duplicate', 'run-1', 'runtime/projects.json', 'project',
                    'project-1', ?, 'skipped', '2026-07-12T00:00:00+00:00',
                    '2026-07-12T00:00:00+00:00')
                """,
                ("b" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_migration_record_results (
                    record_result_id, run_id, source_path, record_type, source_record_id,
                    source_payload_sha256, status, created_at, updated_at
                ) VALUES ('result-invalid', 'run-1', 'runtime/projects.json', 'project',
                    'project-2', ?, 'unknown', '2026-07-12T00:00:00+00:00',
                    '2026-07-12T00:00:00+00:00')
                """,
                ("c" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM domain_migration_runs WHERE run_id = 'run-1'")


def test_legacy_records_upgrade_without_inventing_source_metadata(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "domain.sqlite3")) as conn:
        _apply_through_migration_012(conn)
        _insert_run(conn, "run-legacy")
        conn.execute(
            """
            INSERT INTO legacy_domain_records
                (legacy_record_id, run_id, record_type, payload_json, created_at)
            VALUES ('legacy-1', 'run-legacy', 'session', '{"session_id":"old"}',
                '2026-07-12T00:00:00+00:00')
            """
        )

        migration_013_domain_migration_record_audit(conn)

        assert {
            "source_path",
            "source_record_id",
            "source_payload_sha256",
            "reason",
        } <= _columns(conn, "legacy_domain_records")
        legacy = conn.execute(
            """
            SELECT payload_json, source_path, source_record_id, source_payload_sha256, reason
            FROM legacy_domain_records WHERE legacy_record_id = 'legacy-1'
            """
        ).fetchone()
        assert legacy is not None
        assert tuple(legacy) == ('{"session_id":"old"}', None, None, None, None)

        conn.execute(
            """
            INSERT INTO legacy_domain_records (
                legacy_record_id, run_id, record_type, payload_json, created_at,
                source_path, source_record_id, source_payload_sha256, reason
            ) VALUES ('legacy-2', 'run-legacy', 'session', '{}',
                '2026-07-12T00:00:00+00:00', 'runtime/sessions.sqlite3', 'session-1', ?,
                'runtime session has no task mapping')
            """,
            ("d" * 64,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO legacy_domain_records (
                    legacy_record_id, run_id, record_type, payload_json, created_at,
                    source_path, source_record_id, source_payload_sha256, reason
                ) VALUES ('legacy-3', 'run-legacy', 'session', '{}',
                    '2026-07-12T00:00:00+00:00', 'runtime/sessions.sqlite3', 'session-1', ?,
                    'duplicate source identity')
                """,
                ("e" * 64,),
            )

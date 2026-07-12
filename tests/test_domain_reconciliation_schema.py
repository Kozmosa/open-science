"""Schema coverage for typed, auditable migration reconciliation."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect, run_pending

pytestmark = [pytest.mark.unit]


def _insert_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO domain_migration_runs (
            run_id, mode, source_manifest_json, code_version, status, started_at
        ) VALUES (?, 'apply', '{}', 'test', 'completed', '2026-07-12T00:00:00+00:00')
        """,
        (run_id,),
    )


def _insert_issue(conn: sqlite3.Connection, run_id: str, issue_id: str) -> None:
    conn.execute(
        """
        INSERT INTO domain_migration_issues (
            issue_id, run_id, category, record_type, record_id, severity, detail, created_at
        ) VALUES (?, ?, 'owner_unmapped', 'project', 'project-1', 'blocking',
            'Owner must be resolved explicitly', '2026-07-12T00:00:00+00:00')
        """,
        (issue_id, run_id),
    )


def test_reconciliation_schema_requires_typed_resolution_and_final_evidence(
    tmp_path: Path,
) -> None:
    with closing(connect(tmp_path / "domain.sqlite3")) as conn:
        assert run_pending(conn, "agentic_researcher") == 14
        _insert_run(conn, "run-1")
        _insert_run(conn, "run-2")
        _insert_issue(conn, "run-1", "issue-1")

        run_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(domain_migration_runs)")
        }
        assert {
            "final_manifest_json",
            "final_manifest_sha256",
            "restore_evidence_json",
            "restore_evidence_sha256",
            "restore_evidence_verified_at",
            "finalized_at",
            "reconciled_at",
        } <= run_columns
        issue_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(domain_migration_issues)")
        }
        assert "resolution_type" in issue_columns

        conn.execute(
            """
            INSERT INTO domain_migration_resolutions (
                resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                payload_json, created_at, updated_at
            ) VALUES (
                'resolution-1', 'run-1', 'issue-1', 'owner_mapping', 'operator-1',
                '{"owner_user_id":"user-1"}', '2026-07-12T00:00:00+00:00',
                '2026-07-12T00:00:00+00:00'
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_migration_resolutions (
                    resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                    created_at, updated_at
                ) VALUES (
                    'resolution-wrong-run', 'run-2', 'issue-1', 'owner_mapping', 'operator-1',
                    '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00'
                )
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                UPDATE domain_migration_issues
                SET resolution_type = 'owner_mapping', resolution_status = 'resolved'
                WHERE issue_id = 'issue-1'
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_migration_resolutions (
                    resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                    created_at, updated_at
                ) VALUES (
                    'resolution-ignore', 'run-1', 'issue-1', 'ignore', 'operator-1',
                    '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00'
                )
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_issues SET resolution_type = 'ignore' "
                "WHERE issue_id = 'issue-1'"
            )

        conn.execute(
            """
            INSERT INTO domain_migration_resolutions (
                resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                payload_json, created_at, updated_at, applied_at
            ) VALUES (
                'resolution-2', 'run-1', 'issue-1', 'owner_mapping', 'operator-1',
                '{"owner_user_id":"user-1"}', '2026-07-12T00:01:00+00:00',
                '2026-07-12T00:01:00+00:00', '2026-07-12T00:01:00+00:00'
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_migration_resolutions (
                    resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                    created_at, updated_at, applied_at
                ) VALUES (
                    'resolution-second-applied', 'run-1', 'issue-1', 'owner_mapping', 'operator-2',
                    '2026-07-12T00:02:00+00:00', '2026-07-12T00:02:00+00:00',
                    '2026-07-12T00:02:00+00:00'
                )
                """
            )
        conn.execute(
            """
            UPDATE domain_migration_issues
            SET resolution_type = 'owner_mapping', resolution_status = 'resolved',
                resolved_by_user_id = 'operator-1', resolved_at = '2026-07-12T00:01:00+00:00'
            WHERE issue_id = 'issue-1'
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_resolutions SET updated_at = '2026-07-12T00:03:00+00:00' "
                "WHERE resolution_id = 'resolution-2'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "DELETE FROM domain_migration_resolutions WHERE resolution_id = 'resolution-2'"
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_runs SET finalized_at = '2026-07-12T00:01:00+00:00' "
                "WHERE run_id = 'run-1'"
            )
        conn.execute(
            """
            UPDATE domain_migration_runs
            SET final_manifest_json = '{"files":[]}',
                final_manifest_sha256 = ?,
                restore_evidence_json = '{"restored":true}',
                restore_evidence_sha256 = ?,
                restore_evidence_verified_at = '2026-07-12T00:00:00+00:00',
                finalized_at = '2026-07-12T00:01:00+00:00',
                reconciled_at = '2026-07-12T00:02:00+00:00'
            WHERE run_id = 'run-1'
            """,
            ("a" * 64, "b" * 64),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_runs SET final_manifest_json = '{}' WHERE run_id = 'run-1'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_runs SET restore_evidence_verified_at = "
                "'2026-07-12T00:03:00+00:00' WHERE run_id = 'run-1'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE domain_migration_runs SET source_manifest_json = '{\"changed\":true}' "
                "WHERE run_id = 'run-1'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM domain_migration_issues WHERE issue_id = 'issue-1'")

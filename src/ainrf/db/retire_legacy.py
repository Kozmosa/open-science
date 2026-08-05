"""Explicit one-time migration from the pre-baseline domain schema.

This module is intentionally not imported by normal service startup.  The
operator runs it during a maintenance window after a verified backup and
isolated restore.  Fresh installs use :mod:`ainrf.db.migrations.current`
directly and never execute this historical conversion.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


CURRENT_SCHEMA_VERSION = 33
PREVIOUS_SCHEMA_VERSION = 32
LEGACY_TABLES = frozenset(
    {
        "agent_runtime_sessions",
        "agent_task_attempts",
        "domain_cutover_events",
        "domain_cutover_state",
        "domain_migration_issues",
        "domain_migration_record_results",
        "domain_migration_resolutions",
        "domain_migration_runs",
        "task_attempt_control_requests",
        "task_dispatch_outbox",
        "task_outputs",
    }
)
_ACTIVE_RUNTIME_STATUSES = ("starting", "running", "paused", "launch_unknown")


@dataclass(frozen=True, slots=True)
class LegacyRetirementReport:
    """Auditable result of preflight, migration, or post-validation."""

    ready: bool
    schema_version: int | None
    maintenance_active: bool
    active_runtime_count: int
    cutover_committed: bool
    legacy_tables: tuple[str, ...]
    integrity_check: str | None
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _database_path(state_root: Path) -> Path:
    return state_root / "runtime" / "agentic_researcher.sqlite3"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _report(conn: sqlite3.Connection, *, integrity_check: str | None = None) -> LegacyRetirementReport:
    tables = _table_names(conn)
    version_row = conn.execute(
        "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
    ).fetchone()
    schema_version = int(version_row["version"]) if version_row is not None else None
    maintenance_active = False
    if "domain_maintenance_state" in tables:
        row = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        maintenance_active = row is not None and bool(row["is_active"])
    active_runtime_count = 0
    if "agent_runtime_sessions" in tables:
        placeholders = ", ".join("?" for _ in _ACTIVE_RUNTIME_STATUSES)
        active_runtime_count = int(
            conn.execute(
                f"SELECT COUNT(*) AS count FROM agent_runtime_sessions "
                f"WHERE status IN ({placeholders})",
                _ACTIVE_RUNTIME_STATUSES,
            ).fetchone()["count"]
        )
    cutover_committed = False
    if "domain_cutover_state" in tables:
        row = conn.execute(
            "SELECT state, first_v2_write_at FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
        cutover_committed = (
            row is not None and str(row["state"]) == "v2" and row["first_v2_write_at"] is not None
        )
    blockers: list[str] = []
    if schema_version != PREVIOUS_SCHEMA_VERSION:
        blockers.append(f"expected schema version {PREVIOUS_SCHEMA_VERSION}")
    if not maintenance_active:
        blockers.append("maintenance mode is not active")
    if active_runtime_count:
        blockers.append(f"{active_runtime_count} legacy runtime sessions are still active")
    if "domain_cutover_state" in tables and not cutover_committed:
        blockers.append("domain cutover evidence is not committed")
    if schema_version == CURRENT_SCHEMA_VERSION:
        blockers.clear()
    return LegacyRetirementReport(
        ready=not blockers,
        schema_version=schema_version,
        maintenance_active=maintenance_active,
        active_runtime_count=active_runtime_count,
        cutover_committed=cutover_committed,
        legacy_tables=tuple(sorted(tables & LEGACY_TABLES)),
        integrity_check=integrity_check,
        blockers=tuple(blockers),
    )


def preflight(state_root: Path) -> LegacyRetirementReport:
    """Read the local state and report whether the one-time migration may run."""
    with _connect_read_only(_database_path(state_root)) as conn:
        return _report(conn)


def _rebuild_context_candidates_without_attempt_fk(conn: sqlite3.Connection) -> None:
    """Remove the retired Attempt provenance column from the live context table."""

    tables = _table_names(conn)
    if "project_context_candidates" not in tables:
        return
    objects = conn.execute(
        "SELECT type, name FROM sqlite_master "
        "WHERE sql IS NOT NULL AND type IN ('trigger', 'index') "
        "AND sql LIKE '%project_context_candidates%'"
    ).fetchall()
    for row in objects:
        name = str(row["name"])
        if name.startswith("sqlite_autoindex_"):
            continue
        conn.execute(f'DROP {str(row["type"]).upper()} IF EXISTS "{name}"')
    conn.execute("ALTER TABLE project_context_candidates RENAME TO project_context_candidates_retiring")
    conn.execute(
        """
        CREATE TABLE project_context_candidates (
            candidate_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'accepted', 'rejected')),
            created_at TEXT NOT NULL,
            created_by_user_id TEXT,
            source_metadata_json TEXT NOT NULL DEFAULT '{}',
            accepted_by_user_id TEXT,
            accepted_at TEXT,
            rejected_by_user_id TEXT,
            rejected_at TEXT,
            rejection_reason TEXT,
            source_task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
            source_message_start_seq INTEGER,
            source_message_end_seq INTEGER,
            source_output_start_seq INTEGER,
            source_output_end_seq INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO project_context_candidates (
            candidate_id, project_id, content, status, created_at, created_by_user_id,
            source_metadata_json, accepted_by_user_id, accepted_at, rejected_by_user_id,
            rejected_at, rejection_reason, source_task_id, source_message_start_seq,
            source_message_end_seq, source_output_start_seq, source_output_end_seq
        )
        SELECT candidate_id, project_id, content, status, created_at, created_by_user_id,
            source_metadata_json, accepted_by_user_id, accepted_at, rejected_by_user_id,
            rejected_at, rejection_reason, source_task_id, source_message_start_seq,
            source_message_end_seq, source_output_start_seq, source_output_end_seq
        FROM project_context_candidates_retiring
        """
    )
    conn.execute("DROP TABLE project_context_candidates_retiring")
    conn.executescript(
        """
        CREATE INDEX idx_context_candidates_project_status
            ON project_context_candidates(project_id, status, created_at);
        CREATE TRIGGER context_candidate_provenance_immutable
            BEFORE UPDATE OF project_id, content, created_at, created_by_user_id,
                source_metadata_json, source_task_id, source_message_start_seq,
                source_message_end_seq, source_output_start_seq, source_output_end_seq
            ON project_context_candidates
            BEGIN SELECT RAISE(ABORT, 'context candidate provenance is immutable'); END;
        CREATE TRIGGER context_candidate_delete_forbidden
            BEFORE DELETE ON project_context_candidates
            BEGIN SELECT RAISE(ABORT, 'context candidates are append-only'); END;
        CREATE TRIGGER context_candidate_source_required_insert
            BEFORE INSERT ON project_context_candidates
            WHEN NEW.created_by_user_id IS NULL OR trim(NEW.created_by_user_id) = ''
                OR NEW.source_task_id IS NULL OR trim(NEW.source_task_id) = ''
                OR (NEW.source_message_start_seq IS NULL AND NEW.source_output_start_seq IS NULL)
                OR ((NEW.source_message_start_seq IS NULL) != (NEW.source_message_end_seq IS NULL))
                OR ((NEW.source_output_start_seq IS NULL) != (NEW.source_output_end_seq IS NULL))
            BEGIN SELECT RAISE(ABORT, 'context candidate requires Task source provenance'); END;
        CREATE TRIGGER context_candidate_source_task_project_insert
            BEFORE INSERT ON project_context_candidates
            WHEN NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_id = NEW.source_task_id AND project_id = NEW.project_id
            )
            BEGIN SELECT RAISE(ABORT, 'context candidate source Task must belong to Project'); END;
        """
    )


def migrate(state_root: Path) -> LegacyRetirementReport:
    """Drop completed legacy runtime/cutover state after a passing preflight."""
    path = _database_path(state_root)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        report = _report(conn)
        if report.schema_version == CURRENT_SCHEMA_VERSION:
            return verify(state_root)
        if not report.ready:
            raise RuntimeError("legacy retirement preflight failed: " + "; ".join(report.blockers))
        if "legacy_domain_records" not in _table_names(conn):
            raise RuntimeError("legacy_domain_records audit table is missing")
        conn.execute("PRAGMA foreign_keys = OFF")
        _rebuild_context_candidates_without_attempt_fk(conn)
        conn.execute("ALTER TABLE legacy_domain_records RENAME TO legacy_domain_records_retiring")
        legacy_references = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE sql IS NOT NULL AND type IN ('trigger', 'view', 'index')"
        ).fetchall()
        for row in legacy_references:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
                (row["type"], row["name"]),
            ).fetchone()[0]
            if any(table in str(sql) for table in LEGACY_TABLES):
                conn.execute(f'DROP {str(row["type"]).upper()} IF EXISTS "{row["name"]}"')
        for table in sorted(LEGACY_TABLES):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            INSERT INTO legacy_domain_records (
                legacy_record_id, run_id, record_type, payload_json, created_at,
                source_path, source_record_id, source_payload_sha256, reason
            )
            SELECT legacy_record_id, run_id, record_type, payload_json, created_at,
                   source_path, source_record_id, source_payload_sha256, reason
              FROM legacy_domain_records_retiring
            """
        )
        conn.execute("DROP TABLE legacy_domain_records_retiring")
        conn.execute(
            "UPDATE _schema_version SET version = ? WHERE database = 'agentic_researcher'",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    return verify(state_root)


def verify(state_root: Path) -> LegacyRetirementReport:
    """Validate the post-migration baseline and absence of legacy tables."""
    with _connect_read_only(_database_path(state_root)) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        report = _report(conn, integrity_check=integrity)
    blockers = list(report.blockers)
    if report.schema_version == CURRENT_SCHEMA_VERSION:
        blockers.extend(
            f"legacy table remains: {table}" for table in report.legacy_tables
        )
    if integrity != "ok":
        blockers.append(f"integrity check returned {integrity}")
    return LegacyRetirementReport(
        ready=not blockers,
        schema_version=report.schema_version,
        maintenance_active=report.maintenance_active,
        active_runtime_count=report.active_runtime_count,
        cutover_committed=report.cutover_committed,
        legacy_tables=report.legacy_tables,
        integrity_check=integrity,
        blockers=tuple(blockers),
    )

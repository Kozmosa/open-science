from __future__ import annotations

import hashlib
import json
import sqlite3

from ainrf.db.migration import registry

_DATABASE = "agentic_researcher"

_DOMAIN_TASK_REFERENCE_GUARD_NAMES = (
    "domain_v2_task_reference_guard_insert",
    "domain_v2_task_reference_guard_update",
)


def _normalized_sql(value: str) -> str:
    """Normalize SQLite's persisted trigger text for integrity comparison."""

    return " ".join(value.strip().rstrip(";").split()).lower()


def _domain_task_reference_guard_definitions() -> tuple[tuple[str, str], ...]:
    """Return the final v2 Task reference guards in their canonical form.

    SQLite cannot add the complete Project/Workspace foreign-key graph to the
    historical ``tasks`` table with ``ALTER TABLE``.  These guards are the
    final-cutover equivalent: they keep every newly written or moved Task tied
    to an authoritative Project, active Project–Workspace link, and
    Workspace-derived Environment.
    """

    return (
        (
            "domain_v2_task_reference_guard_insert",
            """
            CREATE TRIGGER domain_v2_task_reference_guard_insert
            BEFORE INSERT ON tasks
            WHEN (SELECT constraints_ready FROM domain_cutover_state WHERE singleton = 1) = 1
              AND (
                NOT EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id)
                OR NOT EXISTS (
                    SELECT 1 FROM workspaces
                    WHERE workspace_id = NEW.workspace_id
                      AND environment_id = NEW.environment_id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM project_workspace_links
                    WHERE project_id = NEW.project_id
                      AND workspace_id = NEW.workspace_id
                      AND status = 'active'
                )
              )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'v2 task requires a domain project, active workspace link, and derived environment'
                );
            END
            """,
        ),
        (
            "domain_v2_task_reference_guard_update",
            """
            CREATE TRIGGER domain_v2_task_reference_guard_update
            BEFORE UPDATE OF project_id, workspace_id, environment_id ON tasks
            WHEN (SELECT constraints_ready FROM domain_cutover_state WHERE singleton = 1) = 1
              AND (
                NOT EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id)
                OR NOT EXISTS (
                    SELECT 1 FROM workspaces
                    WHERE workspace_id = NEW.workspace_id
                      AND environment_id = NEW.environment_id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM project_workspace_links
                    WHERE project_id = NEW.project_id
                      AND workspace_id = NEW.workspace_id
                      AND status = 'active'
                )
              )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'v2 task requires a domain project, active workspace link, and derived environment'
                );
            END
            """,
        ),
    )


def install_domain_task_reference_guards(conn: sqlite3.Connection) -> None:
    """Install the final-cutover Task reference guards transactionally.

    This helper intentionally uses individual ``execute`` calls rather than
    ``executescript`` so a cutover controller may install it while retaining
    its caller-owned ``BEGIN IMMEDIATE`` maintenance transaction.
    """

    for name in _DOMAIN_TASK_REFERENCE_GUARD_NAMES:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    for _name, definition in _domain_task_reference_guard_definitions():
        conn.execute(definition)


def domain_task_reference_guard_digest(conn: sqlite3.Connection) -> str:
    """Verify the installed equivalent FK guards and return their digest."""

    parts: list[str] = []
    for name, expected_definition in _domain_task_reference_guard_definitions():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,)
        ).fetchone()
        actual = row[0] if row is not None else None
        if not isinstance(actual, str) or _normalized_sql(actual) != _normalized_sql(
            expected_definition
        ):
            raise RuntimeError(f"domain Task reference guard is missing or invalid: {name}")
        parts.append(f"{name}:{_normalized_sql(actual)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            researcher_type TEXT NOT NULL,
            harness_engine TEXT NOT NULL,
            user_skills TEXT,
            user_mcp_servers TEXT,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            prompt TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            latest_output_seq INTEGER NOT NULL DEFAULT 0,
            owner_user_id TEXT NOT NULL,
            exit_code INTEGER,
            error_summary TEXT,
            token_usage_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_outputs (
            task_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (task_id, seq)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_environment ON tasks(environment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outputs_kind ON task_outputs(kind)")


@registry.register(_DATABASE)
def migration_002_latest_output_seq(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN latest_output_seq INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists


@registry.register(_DATABASE)
def migration_003_token_usage(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN token_usage_json TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


@registry.register(_DATABASE)
def migration_004_legacy_status_rename(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE tasks SET status = 'queued' WHERE status = 'pending'")
    conn.execute("UPDATE tasks SET status = 'cancelled' WHERE status = 'canceled'")


@registry.register(_DATABASE)
def migration_005_session_transcripts(conn: sqlite3.Connection) -> None:
    """DB-backed SessionStore mirror table for Claude SDK transcript persistence.

    Used by agent-sdk engine to survive container restarts / volume recreation.
    The SDK mirrors every transcript line via SessionStore.append() and resumes
    from the store via SessionStore.load() when the local JSONL is absent.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_transcripts (
            project_key TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            subpath     TEXT NOT NULL DEFAULT '',
            seq         INTEGER NOT NULL,
            entry_json  TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (project_key, session_id, subpath, seq)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_session_transcripts_lookup
        ON session_transcripts(project_key, session_id, subpath)
        """
    )


@registry.register(_DATABASE)
def migration_006_task_profile_overrides(conn: sqlite3.Connection) -> None:
    """Add per-task credential/profile override columns.

    When populated, these override tenant/container defaults via
    env-var injection at engine launch time.  All columns are optional;
    a NULL value means "fall back to the engine's default behaviour".
    """
    columns = [
        ("api_base_url", "TEXT"),
        ("api_key", "TEXT"),
        ("codex_base_url", "TEXT"),
        ("codex_api_key", "TEXT"),
        ("codex_model", "TEXT"),
        ("codex_app_server_command", "TEXT"),
        ("codex_approval_policy", "TEXT"),
    ]
    for col_name, col_type in columns:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists


@registry.register(_DATABASE)
def migration_007_domain_maintenance_barrier(conn: sqlite3.Connection) -> None:
    """Persist the migration write barrier before v2 domain tables exist."""
    _ensure_domain_maintenance_barrier_base(conn)


def _ensure_domain_maintenance_barrier_base(conn: sqlite3.Connection) -> None:
    """Create the original maintenance barrier without changing existing state.

    Migration 007 predates the v2 domain tables, so this helper deliberately
    has no dependency on cutover metadata.  Later migrations call it again to
    make an interrupted historical 007/008 upgrade idempotent.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_maintenance_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            maintenance_epoch INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
            actor_id TEXT,
            reason TEXT,
            entered_at TEXT,
            exited_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO domain_maintenance_state (singleton)
        VALUES (1)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_maintenance_mutations (
            mutation_id TEXT PRIMARY KEY,
            maintenance_epoch INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            source TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_domain_maintenance_mutations_epoch
        ON domain_maintenance_mutations(maintenance_epoch)
        """
    )


def _ensure_domain_write_participant_schema(conn: sqlite3.Connection) -> None:
    """Install the durable writer registry introduced by migration 011."""
    try:
        conn.execute("ALTER TABLE domain_maintenance_mutations ADD COLUMN participant_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_write_participants (
            participant_id TEXT PRIMARY KEY,
            participant_type TEXT NOT NULL,
            process_id INTEGER,
            observed_epoch INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'draining', 'drained', 'stopped')),
            in_flight_mutations INTEGER NOT NULL DEFAULT 0 CHECK (in_flight_mutations >= 0),
            unflushed_output_count INTEGER NOT NULL DEFAULT 0 CHECK (unflushed_output_count >= 0),
            details_json TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            drained_at TEXT,
            stopped_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_domain_write_participants_type
        ON domain_write_participants(participant_type, heartbeat_at);
        CREATE INDEX IF NOT EXISTS idx_domain_maintenance_mutations_participant
        ON domain_maintenance_mutations(participant_id);
        """
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
        is not None
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _require_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: frozenset[str],
) -> None:
    missing = required_columns - _table_columns(conn, table_name)
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(f"cannot repair incomplete {table_name} schema: missing {missing_names}")


@registry.register(_DATABASE)
def migration_008_domain_schema_expand(conn: sqlite3.Connection) -> None:
    """Add the v2 control-plane schema without switching any write path."""
    # Some historical builds recorded migration 007 before its DDL reached
    # disk.  Retain the original barrier prerequisite here so a 7 -> 8 upgrade
    # never assumes its predecessor's side effects.
    _ensure_domain_maintenance_barrier_base(conn)
    for name, definition in (
        ("project_context_version_id", "TEXT"),
        ("archived_at", "TEXT"),
        ("archive_reason", "TEXT"),
        ("stop_reason", "TEXT"),
        ("latest_attempt_id", "TEXT"),
        ("runtime_config_fingerprint", "TEXT"),
        ("source_fingerprint", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
            archived_at TEXT,
            archive_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_one_default_per_owner
        ON projects(owner_user_id) WHERE is_default = 1 AND status = 'active';

        CREATE TABLE IF NOT EXISTS environments (
            environment_id TEXT PRIMARY KEY,
            alias TEXT NOT NULL UNIQUE,
            owner_user_id TEXT,
            display_name TEXT NOT NULL,
            description TEXT,
            connection_json TEXT NOT NULL DEFAULT '{}',
            credential_ref TEXT,
            is_seed INTEGER NOT NULL DEFAULT 0 CHECK (is_seed IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            environment_id TEXT NOT NULL REFERENCES environments(environment_id) ON DELETE RESTRICT,
            canonical_path TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT,
            context_metadata_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unregistered')),
            legacy_project_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_user_id, environment_id, canonical_path)
        );

        CREATE TABLE IF NOT EXISTS project_workspace_links (
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, workspace_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_workspace_one_primary
        ON project_workspace_links(project_id) WHERE is_primary = 1 AND status = 'active';

        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('viewer', 'editor')),
            can_publish INTEGER NOT NULL DEFAULT 0 CHECK (can_publish IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS project_context_drafts (
            project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL DEFAULT '',
            updated_by_user_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_context_versions (
            context_version_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
            created_by_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_context_active_per_project
        ON project_context_versions(project_id) WHERE is_active = 1;
        CREATE TRIGGER IF NOT EXISTS prevent_context_version_content_update
        BEFORE UPDATE OF content ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;
        CREATE TABLE IF NOT EXISTS project_context_candidates (
            candidate_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_context_fragments (
            fragment_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            source_type TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS context_snapshots (
            context_snapshot_id TEXT PRIMARY KEY,
            context_version_id TEXT REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            fingerprint TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_relationships (
            source_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            target_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            relationship_type TEXT NOT NULL CHECK (relationship_type IN ('derived_from', 'depends_on', 'related_to')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_task_id, target_task_id, relationship_type)
        );
        CREATE TABLE IF NOT EXISTS agent_task_attempts (
            attempt_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            attempt_seq INTEGER NOT NULL,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            context_snapshot_id TEXT REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT,
            runtime_config_fingerprint TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(task_id, attempt_seq)
        );
        CREATE TABLE IF NOT EXISTS agent_runtime_sessions (
            runtime_session_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT,
            launch_key TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(launch_key)
        );
        CREATE TABLE IF NOT EXISTS domain_idempotency_requests (
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(scope, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS task_dispatch_outbox (
            dispatch_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            attempt_id TEXT NOT NULL REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'cancelled', 'dispatched')),
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_one_open_attempt
        ON task_dispatch_outbox(attempt_id) WHERE status IN ('pending', 'claimed');
        CREATE TABLE IF NOT EXISTS domain_audit_events (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_migration_runs (
            run_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            source_manifest_json TEXT NOT NULL,
            code_version TEXT NOT NULL,
            status TEXT NOT NULL,
            imported_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            attention_needed_count INTEGER NOT NULL DEFAULT 0,
            cutover_allowed INTEGER NOT NULL DEFAULT 0 CHECK (cutover_allowed IN (0, 1)),
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_migration_issues (
            issue_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES domain_migration_runs(run_id) ON DELETE RESTRICT,
            category TEXT NOT NULL,
            record_type TEXT NOT NULL,
            record_id TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('blocking', 'non_blocking')),
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS legacy_domain_records (
            legacy_record_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES domain_migration_runs(run_id) ON DELETE RESTRICT,
            record_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_cutover_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            contract_version INTEGER NOT NULL DEFAULT 2,
            schema_version INTEGER NOT NULL DEFAULT 1,
            cutover_epoch INTEGER NOT NULL DEFAULT 0,
            first_v2_write_at TEXT,
            cutover_run_id TEXT REFERENCES domain_migration_runs(run_id) ON DELETE RESTRICT,
            source_manifest_json TEXT,
            reconciled_at TEXT,
            blocking_issue_count INTEGER NOT NULL DEFAULT 0,
            constraints_ready INTEGER NOT NULL DEFAULT 0 CHECK (constraints_ready IN (0, 1)),
            cutover_ready INTEGER NOT NULL DEFAULT 0 CHECK (cutover_ready IN (0, 1))
        );
        INSERT OR IGNORE INTO domain_cutover_state(singleton) VALUES (1);
        CREATE TRIGGER IF NOT EXISTS primary_link_must_be_active_insert
        BEFORE INSERT ON project_workspace_links WHEN NEW.is_primary = 1 AND NEW.status != 'active'
        BEGIN SELECT RAISE(ABORT, 'primary link must be active'); END;
        CREATE TRIGGER IF NOT EXISTS primary_link_must_be_active_update
        BEFORE UPDATE OF is_primary, status ON project_workspace_links
        WHEN NEW.is_primary = 1 AND NEW.status != 'active'
        BEGIN SELECT RAISE(ABORT, 'primary link must be active'); END;
        """
    )


@registry.register(_DATABASE)
def migration_009_dispatch_claim_metadata(conn: sqlite3.Connection) -> None:
    for name, definition in (
        ("claim_token", "TEXT"),
        ("dispatcher_id", "TEXT"),
        ("claim_expires_at", "TEXT"),
        ("runtime_launch_key", "TEXT"),
        ("cancel_reason", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE task_dispatch_outbox ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_launch_key ON task_dispatch_outbox(runtime_launch_key) WHERE runtime_launch_key IS NOT NULL"
    )


@registry.register(_DATABASE)
def migration_010_overview_snapshots(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS overview_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(owner_user_id, snapshot_date)
        )
        """
    )


@registry.register(_DATABASE)
def migration_011_domain_write_participants(conn: sqlite3.Connection) -> None:
    """Track every process that can originate a domain write during maintenance."""
    _ensure_domain_maintenance_barrier_base(conn)
    _ensure_domain_write_participant_schema(conn)


@registry.register(_DATABASE)
def migration_012_harden_domain_control_plane(conn: sqlite3.Connection) -> None:
    """Add the durable metadata and guards required by the final v2 contract."""

    def add_columns(table: str, columns: tuple[tuple[str, str], ...]) -> None:
        for name, definition in columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError:
                pass

    add_columns(
        "environments",
        (
            ("connection_fingerprint", "TEXT"),
            ("disabled_at", "TEXT"),
            ("disabled_reason", "TEXT"),
        ),
    )
    add_columns(
        "workspaces",
        (
            ("workspace_context", "TEXT"),
            ("canonical_path_fingerprint", "TEXT"),
            ("unregistered_at", "TEXT"),
            ("unregistered_reason", "TEXT"),
            ("last_seen_at", "TEXT"),
        ),
    )
    add_columns(
        "project_context_candidates",
        (
            ("created_by_user_id", "TEXT"),
            ("source_metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("accepted_by_user_id", "TEXT"),
            ("accepted_at", "TEXT"),
            ("rejected_by_user_id", "TEXT"),
            ("rejected_at", "TEXT"),
            ("rejection_reason", "TEXT"),
        ),
    )
    add_columns(
        "project_context_fragments",
        (
            ("source_version", "TEXT"),
            ("source_fingerprint", "TEXT"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("byte_budget", "INTEGER"),
        ),
    )
    add_columns(
        "context_snapshots",
        (
            ("source_manifest_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("byte_budget", "INTEGER"),
            ("truncated", "INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1))"),
        ),
    )
    add_columns(
        "task_relationships",
        (("relationship_id", "TEXT"), ("metadata_json", "TEXT NOT NULL DEFAULT '{}'")),
    )
    conn.execute(
        """
        UPDATE task_relationships
        SET relationship_id = printf(
            '%d:%s%d:%s%d:%s',
            length(source_task_id), source_task_id,
            length(target_task_id), target_task_id,
            length(relationship_type), relationship_type
        )
        WHERE relationship_id IS NULL
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_relationship_stable_id "
        "ON task_relationships(relationship_id) WHERE relationship_id IS NOT NULL"
    )
    add_columns(
        "agent_task_attempts",
        (
            ("message_start_seq", "INTEGER"),
            ("message_end_seq", "INTEGER"),
            ("output_start_seq", "INTEGER"),
            ("output_end_seq", "INTEGER"),
            ("artifact_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("code_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("data_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("token_usage_json", "TEXT"),
            ("cost_usd", "REAL"),
            ("failure_reason", "TEXT"),
            ("stop_reason", "TEXT"),
        ),
    )
    add_columns(
        "agent_runtime_sessions",
        (
            ("engine_name", "TEXT"),
            ("engine_session_key", "TEXT"),
            ("runtime_metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("started_at", "TEXT"),
            ("finished_at", "TEXT"),
            ("last_probe_at", "TEXT"),
            ("adopted_at", "TEXT"),
            ("failure_reason", "TEXT"),
        ),
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_active_attempt "
        "ON agent_runtime_sessions(attempt_id) WHERE status IN ('starting', 'running', 'paused')"
    )
    add_columns(
        "task_dispatch_outbox",
        (
            ("claimed_at", "TEXT"),
            ("claim_heartbeat_at", "TEXT"),
            ("launch_state", "TEXT NOT NULL DEFAULT 'none'"),
            ("dispatch_attempt_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error", "TEXT"),
            ("next_attempt_at", "TEXT"),
            ("updated_at", "TEXT"),
        ),
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS task_dispatch_launch_state_valid_insert
        BEFORE INSERT ON task_dispatch_outbox
        WHEN NEW.launch_state NOT IN ('none', 'starting', 'launched', 'unknown')
        BEGIN SELECT RAISE(ABORT, 'invalid dispatch launch state'); END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS task_dispatch_launch_state_valid_update
        BEFORE UPDATE OF launch_state ON task_dispatch_outbox
        WHEN NEW.launch_state NOT IN ('none', 'starting', 'launched', 'unknown')
        BEGIN SELECT RAISE(ABORT, 'invalid dispatch launch state'); END
        """
    )

    # The original primary key did not include the calling user.  Rebuild this
    # additive control table before v2 writes begin so client idempotency keys
    # cannot collide across tenants.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_idempotency_requests_v2 (
            actor_user_id TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(actor_user_id, scope, idempotency_key)
        );
        INSERT OR IGNORE INTO domain_idempotency_requests_v2 (
            actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
        ) SELECT '', scope, idempotency_key, request_hash, response_json, created_at
          FROM domain_idempotency_requests;
        DROP TABLE domain_idempotency_requests;
        ALTER TABLE domain_idempotency_requests_v2 RENAME TO domain_idempotency_requests;
        """
    )

    add_columns(
        "domain_migration_runs",
        (
            ("phase", "TEXT NOT NULL DEFAULT 'initial'"),
            ("checkpoint_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("source_manifest_sha256", "TEXT"),
            ("artifact_sha", "TEXT"),
            ("heartbeat_at", "TEXT"),
            ("resume_metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
        ),
    )
    add_columns(
        "domain_migration_issues",
        (
            ("resolution_status", "TEXT NOT NULL DEFAULT 'open'"),
            ("resolution_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("resolved_by_user_id", "TEXT"),
            ("resolved_at", "TEXT"),
        ),
    )
    add_columns(
        "domain_cutover_state",
        (
            ("state", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("prepared_at", "TEXT"),
            ("prepared_by_user_id", "TEXT"),
            ("committed_at", "TEXT"),
            ("artifact_sha", "TEXT"),
            ("artifact_contract_min", "INTEGER"),
            ("artifact_contract_max", "INTEGER"),
            ("backup_manifest_sha256", "TEXT"),
            ("maintenance_epoch", "INTEGER"),
        ),
    )
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS domain_cutover_state_valid_update;
        CREATE TRIGGER domain_cutover_state_valid_update
        BEFORE UPDATE OF state ON domain_cutover_state
        WHEN NEW.state NOT IN ('legacy', 'prepared', 'v2')
          OR (OLD.state = 'legacy' AND NEW.state = 'v2')
          OR (OLD.state = 'v2' AND NEW.state != 'v2')
        BEGIN SELECT RAISE(ABORT, 'invalid domain cutover state transition'); END;
        """
    )
    install_domain_task_reference_guards(conn)


@registry.register(_DATABASE)
def migration_013_domain_migration_record_audit(conn: sqlite3.Connection) -> None:
    """Persist an auditable terminal result for every imported source record."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_migration_record_results (
            record_result_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL
                REFERENCES domain_migration_runs(run_id) ON DELETE RESTRICT,
            source_path TEXT NOT NULL,
            record_type TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            source_payload_sha256 TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('imported', 'skipped', 'attention_needed')),
            target_id TEXT,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, source_path, record_type, source_record_id)
        );
        CREATE INDEX IF NOT EXISTS idx_domain_migration_record_results_run_status
        ON domain_migration_record_results(run_id, status);
        CREATE INDEX IF NOT EXISTS idx_domain_migration_record_results_target
        ON domain_migration_record_results(target_id) WHERE target_id IS NOT NULL;
        """
    )

    # Keep old, already-archived records truthful: a missing source identity is
    # represented as NULL rather than an invented value.  New importer writes
    # supply these fields and are protected by the partial unique index below.
    for name, definition in (
        ("source_path", "TEXT"),
        ("source_record_id", "TEXT"),
        ("source_payload_sha256", "TEXT"),
        ("reason", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE legacy_domain_records ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_legacy_domain_records_source_identity
        ON legacy_domain_records(run_id, source_path, record_type, source_record_id)
        WHERE source_path IS NOT NULL AND source_record_id IS NOT NULL
        """
    )


@registry.register(_DATABASE)
def migration_014_domain_reconciliation_workflow(conn: sqlite3.Connection) -> None:
    """Persist final reconciliation evidence and explicit typed resolutions.

    A migration issue may only be remediated through one audited resolution
    with a deliberately small set of domain-specific types.  In particular,
    there is no catch-all or "ignore" resolution because blocking data-loss or
    ownership questions require an affirmative operator decision.
    """

    for name, definition in (
        ("final_manifest_json", "TEXT"),
        ("final_manifest_sha256", "TEXT"),
        ("restore_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("restore_evidence_sha256", "TEXT"),
        ("restore_evidence_verified_at", "TEXT"),
        ("finalized_at", "TEXT"),
        ("reconciled_at", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE domain_migration_runs ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    try:
        conn.execute(
            """
            ALTER TABLE domain_migration_issues
            ADD COLUMN resolution_type TEXT CHECK (
                resolution_type IS NULL OR resolution_type IN (
                    'owner_mapping',
                    'environment_mapping',
                    'primary_workspace',
                    'session_mapping'
                )
            )
            """
        )
    except sqlite3.OperationalError:
        pass

    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_migration_issues_run_issue
        ON domain_migration_issues(run_id, issue_id);

        CREATE TABLE IF NOT EXISTS domain_migration_resolutions (
            resolution_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL
                REFERENCES domain_migration_runs(run_id) ON DELETE RESTRICT,
            issue_id TEXT NOT NULL,
            resolution_type TEXT NOT NULL CHECK (
                resolution_type IN (
                    'owner_mapping',
                    'environment_mapping',
                    'primary_workspace',
                    'session_mapping'
                )
            ),
            actor_user_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            applied_at TEXT,
            FOREIGN KEY(run_id, issue_id)
                REFERENCES domain_migration_issues(run_id, issue_id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_domain_migration_resolutions_run
        ON domain_migration_resolutions(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_domain_migration_resolutions_type
        ON domain_migration_resolutions(resolution_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_migration_resolutions_one_applied_issue
        ON domain_migration_resolutions(issue_id) WHERE applied_at IS NOT NULL;

        CREATE TRIGGER IF NOT EXISTS domain_migration_resolution_append_only_update
        BEFORE UPDATE ON domain_migration_resolutions
        BEGIN SELECT RAISE(ABORT, 'domain migration resolutions are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS domain_migration_resolution_append_only_delete
        BEFORE DELETE ON domain_migration_resolutions
        BEGIN SELECT RAISE(ABORT, 'domain migration resolutions are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS domain_migration_issue_resolved_requires_resolution_insert
        BEFORE INSERT ON domain_migration_issues
        WHEN NEW.resolution_status = 'resolved'
        BEGIN SELECT RAISE(ABORT, 'resolved migration issue requires an applied typed resolution'); END;

        CREATE TRIGGER IF NOT EXISTS domain_migration_issue_resolved_requires_resolution_update
        BEFORE UPDATE OF resolution_status, resolution_type ON domain_migration_issues
        WHEN NEW.resolution_status = 'resolved'
          AND NOT EXISTS (
              SELECT 1 FROM domain_migration_resolutions AS resolution
              WHERE resolution.run_id = NEW.run_id
                AND resolution.issue_id = NEW.issue_id
                AND resolution.resolution_type = NEW.resolution_type
                AND resolution.applied_at IS NOT NULL
          )
        BEGIN SELECT RAISE(ABORT, 'resolved migration issue requires an applied typed resolution'); END;

        CREATE TRIGGER IF NOT EXISTS domain_migration_run_finalization_requires_evidence
        BEFORE UPDATE OF finalized_at ON domain_migration_runs
        WHEN NEW.finalized_at IS NOT NULL
          AND (
              NEW.final_manifest_json IS NULL
              OR NEW.final_manifest_sha256 IS NULL
              OR NEW.restore_evidence_sha256 IS NULL
              OR NEW.restore_evidence_verified_at IS NULL
          )
        BEGIN SELECT RAISE(ABORT, 'finalized migration run requires manifest and restore evidence'); END;

        CREATE TRIGGER IF NOT EXISTS domain_migration_run_finalization_immutable
        BEFORE UPDATE OF source_manifest_json, source_manifest_sha256,
                         final_manifest_json, final_manifest_sha256,
                         restore_evidence_json, restore_evidence_sha256,
                         restore_evidence_verified_at,
                         finalized_at ON domain_migration_runs
        WHEN OLD.finalized_at IS NOT NULL
          AND (
              NEW.source_manifest_json IS NOT OLD.source_manifest_json
              OR NEW.source_manifest_sha256 IS NOT OLD.source_manifest_sha256
              OR NEW.final_manifest_json IS NOT OLD.final_manifest_json
              OR NEW.final_manifest_sha256 IS NOT OLD.final_manifest_sha256
              OR NEW.restore_evidence_json IS NOT OLD.restore_evidence_json
              OR NEW.restore_evidence_sha256 IS NOT OLD.restore_evidence_sha256
              OR NEW.restore_evidence_verified_at IS NOT OLD.restore_evidence_verified_at
              OR NEW.finalized_at IS NOT OLD.finalized_at
          )
        BEGIN SELECT RAISE(ABORT, 'finalized migration evidence is immutable'); END;
        """
    )


@registry.register(_DATABASE)
def migration_015_project_context_closure(conn: sqlite3.Connection) -> None:
    """Finish the durable Project Context contract before v2 task cutover.

    The new task-level snapshot pointer prevents a later snapshot for the
    same Context Version from changing an existing Task's future Attempts.
    Preview rows make a human-reviewed Context change an explicit two-step
    operation instead of an implicit "use whatever is active now" write.
    """

    for table, columns in (
        (
            "tasks",
            (
                (
                    "project_context_snapshot_id",
                    "TEXT REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT",
                ),
            ),
        ),
        (
            "project_context_candidates",
            (
                ("source_task_id", "TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT"),
                (
                    "source_attempt_id",
                    "TEXT REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT",
                ),
                ("source_message_start_seq", "INTEGER"),
                ("source_message_end_seq", "INTEGER"),
                ("source_output_start_seq", "INTEGER"),
                ("source_output_end_seq", "INTEGER"),
            ),
        ),
        (
            "project_context_fragments",
            (
                ("created_by_user_id", "TEXT"),
                ("source_metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
            ),
        ),
    ):
        for name, definition in columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError:
                pass

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_project_context_snapshot
        ON tasks(project_context_snapshot_id)
        WHERE project_context_snapshot_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_context_candidates_project_status
        ON project_context_candidates(project_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_context_fragments_project_order
        ON project_context_fragments(project_id, sort_order, created_at, fragment_id);

        CREATE TABLE IF NOT EXISTS task_context_update_previews (
            preview_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            context_version_id TEXT NOT NULL
                REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            created_by_user_id TEXT NOT NULL,
            proposed_fingerprint TEXT NOT NULL,
            proposed_content TEXT NOT NULL,
            source_manifest_json TEXT NOT NULL,
            byte_budget INTEGER NOT NULL CHECK (byte_budget >= 0),
            truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            confirmed_snapshot_id TEXT
                REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT,
            confirmed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_task_context_previews_task_actor
        ON task_context_update_previews(task_id, created_by_user_id, created_at);

        CREATE TRIGGER IF NOT EXISTS project_context_version_metadata_immutable
        BEFORE UPDATE OF project_id, content, fingerprint, created_by_user_id, created_at
        ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;

        CREATE TRIGGER IF NOT EXISTS project_context_version_delete_forbidden
        BEFORE DELETE ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS context_snapshot_immutable
        BEFORE UPDATE ON context_snapshots
        BEGIN SELECT RAISE(ABORT, 'context snapshots are immutable'); END;

        CREATE TRIGGER IF NOT EXISTS context_snapshot_delete_forbidden
        BEFORE DELETE ON context_snapshots
        BEGIN SELECT RAISE(ABORT, 'context snapshots are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_provenance_immutable
        BEFORE UPDATE OF project_id, content, created_at, created_by_user_id,
                         source_metadata_json, source_task_id, source_attempt_id,
                         source_message_start_seq, source_message_end_seq,
                         source_output_start_seq, source_output_end_seq
        ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidate provenance is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_delete_forbidden
        BEFORE DELETE ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidates are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS context_fragment_immutable
        BEFORE UPDATE ON project_context_fragments
        BEGIN SELECT RAISE(ABORT, 'context fragments are immutable'); END;

        CREATE TRIGGER IF NOT EXISTS context_fragment_delete_forbidden
        BEFORE DELETE ON project_context_fragments
        BEGIN SELECT RAISE(ABORT, 'context fragments are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS attempt_context_snapshot_no_drift_after_start
        BEFORE UPDATE OF context_snapshot_id ON agent_task_attempts
        WHEN OLD.started_at IS NOT NULL
          OR OLD.status IN ('starting', 'running', 'paused', 'succeeded', 'failed', 'stopped')
        BEGIN SELECT RAISE(ABORT, 'started Attempts keep their Context snapshot'); END;
        """
    )


@registry.register(_DATABASE)
def migration_016_durable_dispatch_recovery(conn: sqlite3.Connection) -> None:
    """Make dispatch ownership and uncertain runtime launch states durable.

    ``task_dispatch_outbox`` originally used a small status CHECK that could
    not represent a launch whose external side effect was no longer knowable.
    Rebuild only that additive control table: Tasks, Attempts, and Runtime
    Sessions retain their stable IDs and RESTRICT relationships.
    """

    for name, definition in (
        ("authorization_environment_id", "TEXT"),
        ("authorization_grant_version", "INTEGER"),
        ("authorization_checked_at", "TEXT"),
        ("stop_requested_at", "TEXT"),
        ("stop_requested_reason", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE agent_task_attempts ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.executescript(
        """
        DROP TRIGGER IF EXISTS task_dispatch_launch_state_valid_insert;
        DROP TRIGGER IF EXISTS task_dispatch_launch_state_valid_update;

        CREATE TABLE task_dispatch_outbox_recovery (
            dispatch_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            attempt_id TEXT NOT NULL REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (
                status IN (
                    'pending', 'claimed', 'dispatched', 'launch_unknown',
                    'cancelled', 'completed', 'failed'
                )
            ),
            created_at TEXT NOT NULL,
            claim_token TEXT,
            dispatcher_id TEXT,
            claim_expires_at TEXT,
            runtime_launch_key TEXT,
            cancel_reason TEXT,
            claimed_at TEXT,
            claim_heartbeat_at TEXT,
            launch_state TEXT NOT NULL DEFAULT 'none' CHECK (
                launch_state IN ('none', 'starting', 'launched', 'unknown')
            ),
            launch_started_at TEXT,
            launch_unknown_at TEXT,
            dispatch_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (dispatch_attempt_count >= 0),
            last_error TEXT,
            next_attempt_at TEXT,
            authorization_environment_id TEXT,
            authorization_grant_version INTEGER,
            authorization_checked_at TEXT,
            updated_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT,
            cancelled_at TEXT
        );
        INSERT INTO task_dispatch_outbox_recovery (
            dispatch_id, task_id, attempt_id, status, created_at, claim_token,
            dispatcher_id, claim_expires_at, runtime_launch_key, cancel_reason,
            claimed_at, claim_heartbeat_at, launch_state, dispatch_attempt_count,
            last_error, next_attempt_at, updated_at
        ) SELECT
            dispatch_id, task_id, attempt_id, status, created_at, claim_token,
            dispatcher_id, claim_expires_at, runtime_launch_key, cancel_reason,
            claimed_at, claim_heartbeat_at, launch_state, dispatch_attempt_count,
            last_error, next_attempt_at, COALESCE(updated_at, created_at)
        FROM task_dispatch_outbox;
        DROP TABLE task_dispatch_outbox;
        ALTER TABLE task_dispatch_outbox_recovery RENAME TO task_dispatch_outbox;

        CREATE UNIQUE INDEX idx_dispatch_launch_key
        ON task_dispatch_outbox(runtime_launch_key) WHERE runtime_launch_key IS NOT NULL;
        CREATE UNIQUE INDEX idx_dispatch_one_open_attempt
        ON task_dispatch_outbox(attempt_id)
        WHERE status IN ('pending', 'claimed', 'dispatched', 'launch_unknown');
        CREATE INDEX idx_dispatch_claimable
        ON task_dispatch_outbox(status, next_attempt_at, claim_expires_at, created_at);
        CREATE INDEX idx_dispatch_project_task
        ON task_dispatch_outbox(task_id, attempt_id, status);

        CREATE TRIGGER task_dispatch_claim_requires_lease
        BEFORE UPDATE OF status ON task_dispatch_outbox
        WHEN NEW.status = 'claimed'
          AND (
              NEW.claim_token IS NULL
              OR NEW.dispatcher_id IS NULL
              OR NEW.claim_expires_at IS NULL
              OR NEW.runtime_launch_key IS NULL
          )
        BEGIN SELECT RAISE(ABORT, 'claimed dispatch requires token, dispatcher, lease, and launch key'); END;

        CREATE TRIGGER task_dispatch_unknown_requires_unknown_launch_state
        BEFORE UPDATE OF status, launch_state ON task_dispatch_outbox
        WHEN NEW.status = 'launch_unknown' AND NEW.launch_state != 'unknown'
        BEGIN SELECT RAISE(ABORT, 'launch_unknown dispatch requires unknown launch state'); END;

        CREATE TRIGGER task_dispatch_launch_state_valid_insert
        BEFORE INSERT ON task_dispatch_outbox
        WHEN NEW.launch_state NOT IN ('none', 'starting', 'launched', 'unknown')
        BEGIN SELECT RAISE(ABORT, 'invalid dispatch launch state'); END;
        CREATE TRIGGER task_dispatch_launch_state_valid_update
        BEFORE UPDATE OF launch_state ON task_dispatch_outbox
        WHEN NEW.launch_state NOT IN ('none', 'starting', 'launched', 'unknown')
        BEGIN SELECT RAISE(ABORT, 'invalid dispatch launch state'); END;
        """
    )


@registry.register(_DATABASE)
def migration_017_task_lifecycle_controls(conn: sqlite3.Connection) -> None:
    """Persist Attempt-control intents and protect archived parents.

    Lifecycle orchestration needs a durable record for requests that cannot
    be treated as an immediate process-side effect.  This migration leaves
    existing Attempt and dispatch state transitions alone: an Archive
    transaction must still be able to cancel rows it already owns.  It only
    rejects *new* Attempts or dispatches under an archived Task or Project.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_attempt_control_requests (
            control_request_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            attempt_id TEXT NOT NULL
                REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK (
                action IN ('continue', 'pause', 'resume', 'cancel', 'stop')
            ),
            status TEXT NOT NULL DEFAULT 'requested' CHECK (
                status IN ('requested', 'acknowledged', 'completed', 'failed', 'cancelled')
            ),
            actor_user_id TEXT NOT NULL,
            idempotency_key TEXT,
            request_hash TEXT,
            reason TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            acknowledged_at TEXT,
            completed_at TEXT,
            failure_reason TEXT,
            CHECK (
                (idempotency_key IS NULL AND request_hash IS NULL)
                OR (idempotency_key IS NOT NULL AND request_hash IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_attempt_control_request_idempotency
        ON task_attempt_control_requests(actor_user_id, task_id, action, idempotency_key)
        WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_attempt_control_request_attempt_status
        ON task_attempt_control_requests(attempt_id, status, created_at, control_request_id);
        CREATE INDEX IF NOT EXISTS idx_attempt_control_request_task_created
        ON task_attempt_control_requests(task_id, created_at, control_request_id);

        CREATE INDEX IF NOT EXISTS idx_tasks_project_lifecycle
        ON tasks(project_id, archived_at, status, updated_at, task_id);
        CREATE INDEX IF NOT EXISTS idx_attempts_task_lifecycle
        ON agent_task_attempts(task_id, status, attempt_seq, created_at);
        CREATE INDEX IF NOT EXISTS idx_dispatch_task_lifecycle
        ON task_dispatch_outbox(task_id, status, launch_state, created_at);

        CREATE TRIGGER IF NOT EXISTS task_attempt_control_request_matches_task
        BEFORE INSERT ON task_attempt_control_requests
        WHEN NOT EXISTS (
            SELECT 1 FROM agent_task_attempts
            WHERE attempt_id = NEW.attempt_id AND task_id = NEW.task_id
        )
        BEGIN SELECT RAISE(ABORT, 'attempt control request must match its Task'); END;

        CREATE TRIGGER IF NOT EXISTS task_attempt_control_request_identity_immutable
        BEFORE UPDATE OF task_id, attempt_id, action, actor_user_id,
                         idempotency_key, request_hash, reason, payload_json,
                         created_at ON task_attempt_control_requests
        BEGIN SELECT RAISE(ABORT, 'attempt control request identity is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS task_attempt_control_request_delete_forbidden
        BEFORE DELETE ON task_attempt_control_requests
        BEGIN SELECT RAISE(ABORT, 'attempt control requests are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS task_attempt_archived_parent_guard_insert
        BEFORE INSERT ON agent_task_attempts
        WHEN EXISTS (
            SELECT 1
            FROM tasks AS task
            LEFT JOIN projects AS project ON project.project_id = task.project_id
            WHERE task.task_id = NEW.task_id
              AND (
                  task.archived_at IS NOT NULL
                  OR task.status = 'archived'
                  OR project.status = 'archived'
              )
        )
        BEGIN SELECT RAISE(ABORT, 'archived Task or Project cannot create an Attempt'); END;

        CREATE TRIGGER IF NOT EXISTS task_dispatch_archived_parent_guard_insert
        BEFORE INSERT ON task_dispatch_outbox
        WHEN EXISTS (
            SELECT 1
            FROM tasks AS task
            LEFT JOIN projects AS project ON project.project_id = task.project_id
            WHERE task.task_id = NEW.task_id
              AND (
                  task.archived_at IS NOT NULL
                  OR task.status = 'archived'
                  OR project.status = 'archived'
              )
        )
        BEGIN SELECT RAISE(ABORT, 'archived Task or Project cannot create a dispatch'); END;
        """
    )


def _install_domain_cutover_state_guards(conn: sqlite3.Connection) -> None:
    """Install the one-way state machine for fresh and already-migrated DBs."""

    conn.executescript(
        """
        DROP TRIGGER IF EXISTS domain_cutover_state_valid_update;
        DROP TRIGGER IF EXISTS domain_cutover_first_v2_write_pair;
        DROP TRIGGER IF EXISTS domain_cutover_state_prepared_immutable;
        DROP TRIGGER IF EXISTS domain_cutover_state_v2_immutable;
        DROP TRIGGER IF EXISTS domain_cutover_state_delete_forbidden;
        DROP TRIGGER IF EXISTS domain_cutover_state_v2_delete_forbidden;

        CREATE TRIGGER domain_cutover_state_valid_update
        BEFORE UPDATE OF state ON domain_cutover_state
        WHEN NEW.state NOT IN ('legacy', 'prepared', 'v2')
          OR (OLD.state = 'legacy' AND NEW.state = 'v2')
          OR (OLD.state = 'v2' AND NEW.state != 'v2')
          OR (
              OLD.state = 'legacy' AND NEW.state = 'prepared'
              AND NOT (
                  NEW.cutover_epoch > OLD.cutover_epoch
                  AND NEW.cutover_run_id IS NOT NULL
                  AND NEW.source_manifest_json IS NOT NULL
                  AND NEW.reconciled_at IS NOT NULL
                  AND NEW.blocking_issue_count = 0
                  AND NEW.constraints_ready = 1
                  AND NEW.cutover_ready = 0
                  AND NEW.prepared_at IS NOT NULL
                  AND NEW.prepared_by_user_id IS NOT NULL
                  AND NEW.committed_at IS NULL
                  AND NEW.committed_by_user_id IS NULL
                  AND NEW.first_v2_write_at IS NULL
                  AND NEW.first_v2_write_actor_id IS NULL
                  AND NEW.artifact_sha IS NOT NULL
                  AND NEW.artifact_contract_min IS NOT NULL
                  AND NEW.artifact_contract_max IS NOT NULL
                  AND NEW.artifact_contract_min <= NEW.contract_version
                  AND NEW.contract_version <= NEW.artifact_contract_max
                  AND NEW.artifact_schema_min IS NOT NULL
                  AND NEW.artifact_schema_max IS NOT NULL
                  AND NEW.artifact_schema_min <= NEW.schema_version
                  AND NEW.schema_version <= NEW.artifact_schema_max
                  AND NEW.backup_manifest_sha256 IS NOT NULL
                  AND NEW.backup_tree_sha256 IS NOT NULL
                  AND NEW.backup_created_at IS NOT NULL
                  AND NEW.backup_version >= 3
                  AND NEW.maintenance_epoch IS NOT NULL
                  AND NEW.source_inventory_json IS NOT NULL
                  AND NEW.source_inventory_sha256 IS NOT NULL
                  AND NEW.restore_evidence_sha256 IS NOT NULL
                  AND NEW.preparation_digest IS NOT NULL
                  AND NEW.prepared_blocking_issue_count = 0
              )
          )
          OR (
              OLD.state = 'prepared' AND NEW.state = 'v2'
              AND NOT (
                  NEW.contract_version IS OLD.contract_version
                  AND NEW.schema_version IS OLD.schema_version
                  AND NEW.cutover_epoch IS OLD.cutover_epoch
                  AND NEW.cutover_run_id IS OLD.cutover_run_id
                  AND NEW.source_manifest_json IS OLD.source_manifest_json
                  AND NEW.reconciled_at IS OLD.reconciled_at
                  AND NEW.blocking_issue_count IS OLD.blocking_issue_count
                  AND NEW.constraints_ready = 1
                  AND OLD.cutover_ready = 0
                  AND NEW.cutover_ready = 1
                  AND NEW.prepared_at IS OLD.prepared_at
                  AND NEW.prepared_by_user_id IS OLD.prepared_by_user_id
                  AND OLD.committed_at IS NULL
                  AND NEW.committed_at IS NOT NULL
                  AND OLD.committed_by_user_id IS NULL
                  AND NEW.committed_by_user_id IS NOT NULL
                  AND NEW.first_v2_write_at IS NULL
                  AND NEW.first_v2_write_actor_id IS NULL
                  AND NEW.artifact_sha IS OLD.artifact_sha
                  AND NEW.artifact_contract_min IS OLD.artifact_contract_min
                  AND NEW.artifact_contract_max IS OLD.artifact_contract_max
                  AND NEW.artifact_schema_min IS OLD.artifact_schema_min
                  AND NEW.artifact_schema_max IS OLD.artifact_schema_max
                  AND NEW.backup_manifest_sha256 IS OLD.backup_manifest_sha256
                  AND NEW.backup_tree_sha256 IS OLD.backup_tree_sha256
                  AND NEW.backup_created_at IS OLD.backup_created_at
                  AND NEW.backup_version IS OLD.backup_version
                  AND NEW.maintenance_epoch IS OLD.maintenance_epoch
                  AND NEW.source_inventory_json IS OLD.source_inventory_json
                  AND NEW.source_inventory_sha256 IS OLD.source_inventory_sha256
                  AND NEW.restore_evidence_sha256 IS OLD.restore_evidence_sha256
                  AND NEW.preparation_digest IS OLD.preparation_digest
                  AND NEW.prepared_blocking_issue_count = 0
              )
          )
          OR (
              OLD.state = 'prepared' AND NEW.state = 'legacy'
              AND NOT (
                  NEW.contract_version IS OLD.contract_version
                  AND NEW.schema_version IS OLD.schema_version
                  AND NEW.cutover_epoch IS OLD.cutover_epoch
                  AND NEW.cutover_run_id IS NULL
                  AND NEW.source_manifest_json IS NULL
                  AND NEW.reconciled_at IS NULL
                  AND NEW.blocking_issue_count = 0
                  AND NEW.constraints_ready IS OLD.constraints_ready
                  AND NEW.cutover_ready = 0
                  AND NEW.prepared_at IS NULL
                  AND NEW.prepared_by_user_id IS NULL
                  AND NEW.committed_at IS NULL
                  AND NEW.committed_by_user_id IS NULL
                  AND NEW.first_v2_write_at IS NULL
                  AND NEW.first_v2_write_actor_id IS NULL
                  AND NEW.artifact_sha IS NULL
                  AND NEW.artifact_contract_min IS NULL
                  AND NEW.artifact_contract_max IS NULL
                  AND NEW.artifact_schema_min IS NULL
                  AND NEW.artifact_schema_max IS NULL
                  AND NEW.backup_manifest_sha256 IS NULL
                  AND NEW.backup_tree_sha256 IS NULL
                  AND NEW.backup_created_at IS NULL
                  AND NEW.backup_version IS NULL
                  AND NEW.maintenance_epoch IS NULL
                  AND NEW.source_inventory_json IS NULL
                  AND NEW.source_inventory_sha256 IS NULL
                  AND NEW.restore_evidence_sha256 IS NULL
                  AND NEW.preparation_digest IS NULL
                  AND NEW.prepared_blocking_issue_count = 0
              )
          )
        BEGIN SELECT RAISE(ABORT, 'invalid domain cutover state transition'); END;

        CREATE TRIGGER domain_cutover_state_prepared_immutable
        BEFORE UPDATE ON domain_cutover_state
        WHEN OLD.state = 'prepared' AND NEW.state = 'prepared'
          AND NOT (
              NEW.singleton IS OLD.singleton
              AND NEW.contract_version IS OLD.contract_version
              AND NEW.schema_version IS OLD.schema_version
              AND NEW.cutover_epoch IS OLD.cutover_epoch
              AND NEW.first_v2_write_at IS OLD.first_v2_write_at
              AND NEW.first_v2_write_actor_id IS OLD.first_v2_write_actor_id
              AND NEW.cutover_run_id IS OLD.cutover_run_id
              AND NEW.source_manifest_json IS OLD.source_manifest_json
              AND NEW.reconciled_at IS OLD.reconciled_at
              AND NEW.blocking_issue_count IS OLD.blocking_issue_count
              AND NEW.constraints_ready IS OLD.constraints_ready
              AND NEW.cutover_ready IS OLD.cutover_ready
              AND NEW.prepared_at IS OLD.prepared_at
              AND NEW.prepared_by_user_id IS OLD.prepared_by_user_id
              AND NEW.committed_at IS OLD.committed_at
              AND NEW.committed_by_user_id IS OLD.committed_by_user_id
              AND NEW.artifact_sha IS OLD.artifact_sha
              AND NEW.artifact_contract_min IS OLD.artifact_contract_min
              AND NEW.artifact_contract_max IS OLD.artifact_contract_max
              AND NEW.artifact_schema_min IS OLD.artifact_schema_min
              AND NEW.artifact_schema_max IS OLD.artifact_schema_max
              AND NEW.backup_manifest_sha256 IS OLD.backup_manifest_sha256
              AND NEW.backup_tree_sha256 IS OLD.backup_tree_sha256
              AND NEW.backup_created_at IS OLD.backup_created_at
              AND NEW.backup_version IS OLD.backup_version
              AND NEW.maintenance_epoch IS OLD.maintenance_epoch
              AND NEW.source_inventory_json IS OLD.source_inventory_json
              AND NEW.source_inventory_sha256 IS OLD.source_inventory_sha256
              AND NEW.restore_evidence_sha256 IS OLD.restore_evidence_sha256
              AND NEW.preparation_digest IS OLD.preparation_digest
              AND NEW.prepared_blocking_issue_count IS OLD.prepared_blocking_issue_count
          )
        BEGIN SELECT RAISE(ABORT, 'prepared domain cutover evidence is immutable'); END;

        CREATE TRIGGER domain_cutover_first_v2_write_pair
        BEFORE UPDATE OF first_v2_write_at, first_v2_write_actor_id ON domain_cutover_state
        WHEN (NEW.first_v2_write_at IS NULL) != (NEW.first_v2_write_actor_id IS NULL)
          OR (
              NEW.state != 'v2'
              AND (NEW.first_v2_write_at IS NOT NULL OR NEW.first_v2_write_actor_id IS NOT NULL)
          )
        BEGIN SELECT RAISE(ABORT, 'first v2 write metadata requires committed v2 state'); END;

        CREATE TRIGGER domain_cutover_state_v2_immutable
        BEFORE UPDATE ON domain_cutover_state
        WHEN OLD.state = 'v2'
          AND NOT (
              NEW.singleton IS OLD.singleton
              AND NEW.state IS OLD.state
              AND NEW.contract_version IS OLD.contract_version
              AND NEW.schema_version IS OLD.schema_version
              AND NEW.cutover_epoch IS OLD.cutover_epoch
              AND NEW.cutover_run_id IS OLD.cutover_run_id
              AND NEW.source_manifest_json IS OLD.source_manifest_json
              AND NEW.reconciled_at IS OLD.reconciled_at
              AND NEW.blocking_issue_count IS OLD.blocking_issue_count
              AND NEW.constraints_ready IS OLD.constraints_ready
              AND NEW.cutover_ready IS OLD.cutover_ready
              AND NEW.prepared_at IS OLD.prepared_at
              AND NEW.prepared_by_user_id IS OLD.prepared_by_user_id
              AND NEW.committed_at IS OLD.committed_at
              AND NEW.committed_by_user_id IS OLD.committed_by_user_id
              AND NEW.artifact_sha IS OLD.artifact_sha
              AND NEW.artifact_contract_min IS OLD.artifact_contract_min
              AND NEW.artifact_contract_max IS OLD.artifact_contract_max
              AND NEW.artifact_schema_min IS OLD.artifact_schema_min
              AND NEW.artifact_schema_max IS OLD.artifact_schema_max
              AND NEW.backup_manifest_sha256 IS OLD.backup_manifest_sha256
              AND NEW.backup_tree_sha256 IS OLD.backup_tree_sha256
              AND NEW.backup_created_at IS OLD.backup_created_at
              AND NEW.backup_version IS OLD.backup_version
              AND NEW.maintenance_epoch IS OLD.maintenance_epoch
              AND NEW.source_inventory_json IS OLD.source_inventory_json
              AND NEW.source_inventory_sha256 IS OLD.source_inventory_sha256
              AND NEW.restore_evidence_sha256 IS OLD.restore_evidence_sha256
              AND NEW.preparation_digest IS OLD.preparation_digest
              AND NEW.prepared_blocking_issue_count IS OLD.prepared_blocking_issue_count
              AND (
                  (
                      NEW.first_v2_write_at IS OLD.first_v2_write_at
                      AND NEW.first_v2_write_actor_id IS OLD.first_v2_write_actor_id
                  )
                  OR (
                      OLD.first_v2_write_at IS NULL
                      AND OLD.first_v2_write_actor_id IS NULL
                      AND NEW.first_v2_write_at IS NOT NULL
                      AND NEW.first_v2_write_actor_id IS NOT NULL
                  )
              )
          )
        BEGIN SELECT RAISE(ABORT, 'invalid domain cutover state transition: committed state is immutable'); END;

        CREATE TRIGGER domain_cutover_state_delete_forbidden
        BEFORE DELETE ON domain_cutover_state
        BEGIN SELECT RAISE(ABORT, 'domain cutover state cannot be deleted'); END;
        """
    )


@registry.register(_DATABASE)
def migration_018_domain_cutover_controller(conn: sqlite3.Connection) -> None:
    """Persist the transactional fuse used to prepare and commit domain v2.

    A completed shadow import is not itself permission to enable v2 writes.
    The controller records the exact migration, backup, artifact, schema, and
    maintenance facts in one row before it can transition to ``v2``.  Once v2
    is committed that row is immutable except for recording the actor and time
    of the first v2 write; rolling back requires a separate full restore.
    """

    for name, definition in (
        ("first_v2_write_actor_id", "TEXT"),
        ("committed_by_user_id", "TEXT"),
        ("backup_tree_sha256", "TEXT"),
        ("backup_created_at", "TEXT"),
        ("backup_version", "INTEGER"),
        ("artifact_schema_min", "INTEGER"),
        ("artifact_schema_max", "INTEGER"),
        ("source_inventory_json", "TEXT"),
        ("source_inventory_sha256", "TEXT"),
        ("restore_evidence_sha256", "TEXT"),
        ("preparation_digest", "TEXT"),
        ("prepared_blocking_issue_count", "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE domain_cutover_state ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_cutover_events (
            event_id TEXT PRIMARY KEY,
            cutover_epoch INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN ('prepared', 'committed', 'aborted', 'first_v2_write')
            ),
            actor_user_id TEXT NOT NULL,
            migration_run_id TEXT,
            preparation_digest TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_domain_cutover_events_epoch
        ON domain_cutover_events(cutover_epoch, created_at, event_id);
        CREATE INDEX IF NOT EXISTS idx_domain_cutover_events_run
        ON domain_cutover_events(migration_run_id, created_at, event_id)
        WHERE migration_run_id IS NOT NULL;

        CREATE TRIGGER IF NOT EXISTS domain_cutover_events_append_only_update
        BEFORE UPDATE ON domain_cutover_events
        BEGIN SELECT RAISE(ABORT, 'domain cutover events are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS domain_cutover_events_append_only_delete
        BEFORE DELETE ON domain_cutover_events
        BEGIN SELECT RAISE(ABORT, 'domain cutover events are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS domain_cutover_first_v2_write_pair
        BEFORE UPDATE OF first_v2_write_at, first_v2_write_actor_id ON domain_cutover_state
        WHEN (NEW.first_v2_write_at IS NULL) != (NEW.first_v2_write_actor_id IS NULL)
          OR (
              NEW.state != 'v2'
              AND (NEW.first_v2_write_at IS NOT NULL OR NEW.first_v2_write_actor_id IS NOT NULL)
          )
        BEGIN SELECT RAISE(ABORT, 'first v2 write metadata requires committed v2 state'); END;

        CREATE TRIGGER IF NOT EXISTS domain_cutover_state_v2_immutable
        BEFORE UPDATE ON domain_cutover_state
        WHEN OLD.state = 'v2'
          AND NOT (
              NEW.singleton IS OLD.singleton
              AND NEW.state IS OLD.state
              AND NEW.contract_version IS OLD.contract_version
              AND NEW.schema_version IS OLD.schema_version
              AND NEW.cutover_epoch IS OLD.cutover_epoch
              AND NEW.cutover_run_id IS OLD.cutover_run_id
              AND NEW.source_manifest_json IS OLD.source_manifest_json
              AND NEW.reconciled_at IS OLD.reconciled_at
              AND NEW.blocking_issue_count IS OLD.blocking_issue_count
              AND NEW.constraints_ready IS OLD.constraints_ready
              AND NEW.cutover_ready IS OLD.cutover_ready
              AND NEW.prepared_at IS OLD.prepared_at
              AND NEW.prepared_by_user_id IS OLD.prepared_by_user_id
              AND NEW.committed_at IS OLD.committed_at
              AND NEW.committed_by_user_id IS OLD.committed_by_user_id
              AND NEW.artifact_sha IS OLD.artifact_sha
              AND NEW.artifact_contract_min IS OLD.artifact_contract_min
              AND NEW.artifact_contract_max IS OLD.artifact_contract_max
              AND NEW.artifact_schema_min IS OLD.artifact_schema_min
              AND NEW.artifact_schema_max IS OLD.artifact_schema_max
              AND NEW.backup_manifest_sha256 IS OLD.backup_manifest_sha256
              AND NEW.backup_tree_sha256 IS OLD.backup_tree_sha256
              AND NEW.backup_created_at IS OLD.backup_created_at
              AND NEW.backup_version IS OLD.backup_version
              AND NEW.maintenance_epoch IS OLD.maintenance_epoch
              AND NEW.source_inventory_json IS OLD.source_inventory_json
              AND NEW.source_inventory_sha256 IS OLD.source_inventory_sha256
              AND NEW.restore_evidence_sha256 IS OLD.restore_evidence_sha256
              AND NEW.preparation_digest IS OLD.preparation_digest
              AND NEW.prepared_blocking_issue_count IS OLD.prepared_blocking_issue_count
              AND (
                  (
                      NEW.first_v2_write_at IS OLD.first_v2_write_at
                      AND NEW.first_v2_write_actor_id IS OLD.first_v2_write_actor_id
                  )
                  OR (
                      OLD.first_v2_write_at IS NULL
                      AND OLD.first_v2_write_actor_id IS NULL
                      AND NEW.first_v2_write_at IS NOT NULL
                      AND NEW.first_v2_write_actor_id IS NOT NULL
                  )
              )
          )
        BEGIN SELECT RAISE(ABORT, 'invalid domain cutover state transition: committed state is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS domain_cutover_state_v2_delete_forbidden
        BEFORE DELETE ON domain_cutover_state
        WHEN OLD.state = 'v2'
        BEGIN SELECT RAISE(ABORT, 'committed domain cutover state cannot be deleted'); END;
        """
    )
    _install_domain_cutover_state_guards(conn)


@registry.register(_DATABASE)
def migration_019_harden_domain_cutover_state_machine(conn: sqlite3.Connection) -> None:
    """Apply B7 transition guards to databases that already ran migration 018."""

    _install_domain_cutover_state_guards(conn)


@registry.register(_DATABASE)
def migration_020_overview_refresh_jobs(conn: sqlite3.Connection) -> None:
    """Add the durable, user-scoped Today overview work model.

    ``overview_snapshots`` predates the durable dispatcher model.  Keep its
    existing rows readable while extending it with card provenance, then make
    every scheduled and manual refresh flow through a leased job row.  The
    partial active-job index is the SQLite arbitration point for repeated
    clicks, API retries, and concurrently running planners.
    """

    for name, definition in (
        ("data_cutoff_at", "TEXT"),
        ("source_status", "TEXT"),
        ("attention_required", "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE overview_snapshots ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS overview_refresh_jobs (
            job_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'catchup')),
            scheduled_for_date TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'running', 'succeeded', 'partial', 'failed'
            )),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            lease_owner TEXT,
            lease_token TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            snapshot_id TEXT,
            source_status TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (
                (trigger = 'manual' AND scheduled_for_date IS NULL)
                OR (trigger IN ('scheduled', 'catchup') AND scheduled_for_date IS NOT NULL)
            ),
            CHECK (
                (status = 'running' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
                 AND lease_expires_at IS NOT NULL)
                OR status != 'running'
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_overview_refresh_jobs_schedule_slot
        ON overview_refresh_jobs(owner_user_id, scheduled_for_date)
        WHERE scheduled_for_date IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_overview_refresh_jobs_active_owner
        ON overview_refresh_jobs(owner_user_id)
        WHERE status IN ('queued', 'running');
        CREATE INDEX IF NOT EXISTS idx_overview_refresh_jobs_claim
        ON overview_refresh_jobs(status, created_at, job_id);
        CREATE INDEX IF NOT EXISTS idx_overview_refresh_jobs_owner_updated
        ON overview_refresh_jobs(owner_user_id, updated_at DESC, job_id DESC);
        CREATE INDEX IF NOT EXISTS idx_overview_refresh_jobs_lease_expiry
        ON overview_refresh_jobs(status, lease_expires_at)
        WHERE status = 'running';

        CREATE TABLE IF NOT EXISTS overview_refresh_card_states (
            owner_user_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            last_job_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'ok', 'partial', 'stale', 'unavailable', 'failed'
            )),
            data_json TEXT,
            data_cutoff_at TEXT NOT NULL,
            last_success_data_json TEXT,
            last_success_at TEXT,
            last_success_cutoff_at TEXT,
            error_summary TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, card_id),
            FOREIGN KEY (last_job_id) REFERENCES overview_refresh_jobs(job_id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_overview_refresh_card_states_owner_updated
        ON overview_refresh_card_states(owner_user_id, updated_at DESC, card_id);

        CREATE TABLE IF NOT EXISTS overview_planner_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            planner_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running', 'drained', 'stopped')),
            heartbeat_at TEXT NOT NULL,
            last_schedule_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )


@registry.register(_DATABASE)
def migration_021_freeze_context_version_fragments(conn: sqlite3.Connection) -> None:
    """Add an immutable manifest slot without inventing legacy provenance.

    Prior schema revisions attached Fragments to a Project, not to a Context
    Version.  They therefore cannot prove which set belonged to any historic
    Version.  This migration creates the slot and protects it; migration 023
    records every pre-existing Version as explicit ``attention_needed`` rather
    than copying the current Project Fragment rows into its past.
    """

    try:
        conn.execute(
            "ALTER TABLE project_context_versions "
            "ADD COLUMN fragment_manifest_json TEXT NOT NULL DEFAULT '[]'"
        )
    except sqlite3.OperationalError:
        pass

    # Reinstall the immutable trigger to add the new manifest column.  Existing
    # rows intentionally retain the canonical empty placeholder until the
    # following provenance migration marks them as unresolved.
    conn.execute("DROP TRIGGER IF EXISTS project_context_version_metadata_immutable")
    conn.executescript(
        """
        CREATE TRIGGER project_context_version_metadata_immutable
        BEFORE UPDATE OF project_id, content, fingerprint, fragment_manifest_json,
                         created_by_user_id, created_at
        ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;
        """
    )


def _create_overview_refresh_jobs_with_retry_schema(conn: sqlite3.Connection) -> None:
    """Create the retry-capable Overview job table and its durable indexes."""

    conn.executescript(
        """
        CREATE TABLE overview_refresh_jobs (
            job_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'catchup')),
            scheduled_for_date TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'retry_wait', 'running', 'succeeded', 'partial', 'failed'
            )),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            next_retry_at TEXT,
            last_failure_at TEXT,
            lease_owner TEXT,
            lease_token TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            snapshot_id TEXT,
            source_status TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (
                (trigger = 'manual' AND scheduled_for_date IS NULL)
                OR (trigger IN ('scheduled', 'catchup') AND scheduled_for_date IS NOT NULL)
            ),
            CHECK (
                (status = 'running' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
                 AND lease_expires_at IS NOT NULL)
                OR status != 'running'
            ),
            CHECK (
                (status = 'retry_wait' AND next_retry_at IS NOT NULL)
                OR status != 'retry_wait'
            )
        );
        CREATE UNIQUE INDEX idx_overview_refresh_jobs_schedule_slot
        ON overview_refresh_jobs(owner_user_id, scheduled_for_date)
        WHERE scheduled_for_date IS NOT NULL;
        CREATE UNIQUE INDEX idx_overview_refresh_jobs_active_owner
        ON overview_refresh_jobs(owner_user_id)
        WHERE status IN ('queued', 'retry_wait', 'running');
        CREATE INDEX idx_overview_refresh_jobs_claim
        ON overview_refresh_jobs(status, next_retry_at, created_at, job_id);
        CREATE INDEX idx_overview_refresh_jobs_owner_updated
        ON overview_refresh_jobs(owner_user_id, updated_at DESC, job_id DESC);
        CREATE INDEX idx_overview_refresh_jobs_lease_expiry
        ON overview_refresh_jobs(status, lease_expires_at)
        WHERE status = 'running';
        """
    )


def _create_overview_refresh_card_states(conn: sqlite3.Connection) -> None:
    """Recreate the child table after the retry-schema parent rebuild."""

    conn.executescript(
        """
        CREATE TABLE overview_refresh_card_states (
            owner_user_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            last_job_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'ok', 'partial', 'stale', 'unavailable', 'failed'
            )),
            data_json TEXT,
            data_cutoff_at TEXT NOT NULL,
            last_success_data_json TEXT,
            last_success_at TEXT,
            last_success_cutoff_at TEXT,
            error_summary TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, card_id),
            FOREIGN KEY (last_job_id) REFERENCES overview_refresh_jobs(job_id)
                ON DELETE RESTRICT
        );
        CREATE INDEX idx_overview_refresh_card_states_owner_updated
        ON overview_refresh_card_states(owner_user_id, updated_at DESC, card_id);
        """
    )


@registry.register(_DATABASE)
def migration_022_overview_refresh_retry_backoff(conn: sqlite3.Connection) -> None:
    """Add bounded retry state without letting a failed daily slot disappear.

    SQLite cannot alter a table-level ``CHECK`` to admit ``retry_wait``.  The
    parent and its FK child are rebuilt inside the migration transaction with
    deferred FK enforcement, then copied exactly.  This keeps completed
    snapshot/card history intact while allowing a scheduled slot to retain its
    latest successful data and retry before becoming terminally failed.
    """

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'overview_refresh_jobs'"
    ).fetchone()
    if row is None:
        # Defensive only: fresh schemas always receive migration 020 first.
        _create_overview_refresh_jobs_with_retry_schema(conn)
        _create_overview_refresh_card_states(conn)
        return
    table_sql = str(row["sql"] or "").lower()
    if "retry_wait" in table_sql:
        # A partially upgraded development database may already have a
        # compatible status constraint; retain its rows and add only columns.
        for name, definition in (
            ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("next_retry_at", "TEXT"),
            ("last_failure_at", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE overview_refresh_jobs ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError:
                pass
        return

    # `foreign_keys` is enabled on every project connection.  Deferring it for
    # this transaction permits the parent/child swap while preserving all
    # existing FK values for the newly recreated child table.
    conn.execute("PRAGMA defer_foreign_keys = ON")
    conn.execute("ALTER TABLE overview_refresh_jobs RENAME TO overview_refresh_jobs_legacy")
    for index_name in (
        "idx_overview_refresh_jobs_schedule_slot",
        "idx_overview_refresh_jobs_active_owner",
        "idx_overview_refresh_jobs_claim",
        "idx_overview_refresh_jobs_owner_updated",
        "idx_overview_refresh_jobs_lease_expiry",
    ):
        conn.execute(f"DROP INDEX IF EXISTS {index_name}")
    _create_overview_refresh_jobs_with_retry_schema(conn)
    conn.execute(
        """
        INSERT INTO overview_refresh_jobs (
            job_id, owner_user_id, trigger, scheduled_for_date, status, attempt_count,
            retry_count, next_retry_at, last_failure_at, lease_owner, lease_token,
            lease_expires_at, heartbeat_at, snapshot_id, source_status, error_summary,
            created_at, started_at, finished_at, updated_at
        )
        SELECT
            job_id, owner_user_id, trigger, scheduled_for_date, status, attempt_count,
            0, NULL, NULL, lease_owner, lease_token, lease_expires_at, heartbeat_at,
            snapshot_id, source_status, error_summary, created_at, started_at,
            finished_at, updated_at
        FROM overview_refresh_jobs_legacy
        """
    )

    conn.execute(
        "ALTER TABLE overview_refresh_card_states RENAME TO overview_refresh_card_states_legacy"
    )
    conn.execute("DROP INDEX IF EXISTS idx_overview_refresh_card_states_owner_updated")
    _create_overview_refresh_card_states(conn)
    conn.execute(
        """
        INSERT INTO overview_refresh_card_states (
            owner_user_id, card_id, last_job_id, status, data_json, data_cutoff_at,
            last_success_data_json, last_success_at, last_success_cutoff_at,
            error_summary, updated_at
        )
        SELECT
            owner_user_id, card_id, last_job_id, status, data_json, data_cutoff_at,
            last_success_data_json, last_success_at, last_success_cutoff_at,
            error_summary, updated_at
        FROM overview_refresh_card_states_legacy
        """
    )
    conn.execute("DROP TABLE overview_refresh_card_states_legacy")
    conn.execute("DROP TABLE overview_refresh_jobs_legacy")


@registry.register(_DATABASE)
def migration_023_context_version_fragment_provenance(conn: sqlite3.Connection) -> None:
    """Mark historic Context Version Fragment associations as unresolved.

    A pre-manifest schema had only live Project-level Fragments.  Rebuilding a
    historic Version from the rows visible during upgrade would falsely claim
    those rows were reviewed with that Version.  Preserve every existing
    Version and Snapshot, but record immutable attention-needed provenance and
    clear the untrustworthy manifest.  New publishes insert a verified record;
    an unresolved historic Version is never silently assembled for a new Task.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_context_version_provenance (
            context_version_id TEXT PRIMARY KEY
                REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            fragment_provenance_status TEXT NOT NULL
                CHECK (fragment_provenance_status IN ('verified', 'attention_needed')),
            evidence_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_context_version_provenance_status
        ON project_context_version_provenance(fragment_provenance_status, recorded_at);

        CREATE TRIGGER IF NOT EXISTS context_version_provenance_append_only_update
        BEFORE UPDATE ON project_context_version_provenance
        BEGIN SELECT RAISE(ABORT, 'context version provenance is append-only'); END;

        CREATE TRIGGER IF NOT EXISTS context_version_provenance_append_only_delete
        BEFORE DELETE ON project_context_version_provenance
        BEGIN SELECT RAISE(ABORT, 'context version provenance is append-only'); END;
        """
    )

    # A prior development build of migration 021 copied current live Fragments
    # into every historic Version.  Temporarily lift only the Version metadata
    # trigger so this corrective migration can remove that fabricated claim.
    conn.execute("DROP TRIGGER IF EXISTS project_context_version_metadata_immutable")
    unresolved_rows = conn.execute(
        """
        SELECT version.context_version_id, version.fingerprint, version.fragment_manifest_json
        FROM project_context_versions AS version
        LEFT JOIN project_context_version_provenance AS provenance
          ON provenance.context_version_id = version.context_version_id
        WHERE provenance.context_version_id IS NULL
        """
    ).fetchall()
    for row in unresolved_rows:
        raw_manifest = (
            str(row["fragment_manifest_json"])
            if isinstance(row["fragment_manifest_json"], str)
            else "[]"
        )
        evidence = json.dumps(
            {
                "kind": "legacy_fragment_provenance_unavailable",
                "migration": "023_context_version_fragment_provenance",
                "reason": (
                    "The source schema did not persist a Version-to-Fragment association; "
                    "current Project Fragments are not evidence of historic review."
                ),
                "recorded_version_fingerprint": str(row["fingerprint"]),
                "discarded_manifest_sha256": hashlib.sha256(
                    raw_manifest.encode("utf-8")
                ).hexdigest(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        conn.execute(
            """
            INSERT INTO project_context_version_provenance (
                context_version_id, fragment_provenance_status, evidence_json, recorded_at
            ) VALUES (?, 'attention_needed', ?, strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
            """,
            (str(row["context_version_id"]), evidence),
        )
        conn.execute(
            """
            UPDATE project_context_versions
            SET fragment_manifest_json = '[]'
            WHERE context_version_id = ?
            """,
            (str(row["context_version_id"]),),
        )

    conn.executescript(
        """
        CREATE TRIGGER project_context_version_metadata_immutable
        BEFORE UPDATE OF project_id, content, fingerprint, fragment_manifest_json,
                         created_by_user_id, created_at
        ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;
        """
    )


@registry.register(_DATABASE)
def migration_024_context_candidate_source_guard(conn: sqlite3.Connection) -> None:
    """Name pending Candidates ``proposed`` and guard new source provenance.

    The earlier expand phase used ``pending`` as an implementation label.  The
    public domain contract is ``proposed → accepted|rejected``.  SQLite cannot
    alter a table-level status ``CHECK`` in place, so rebuild just this
    append-only table and retain every historical row as a proposed Candidate.
    Historic rows may lack source fields; the insert guards apply only to new
    writes, keeping imported audit records readable without legitimizing a new
    unprovenanced Candidate.
    """

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'project_context_candidates'"
    ).fetchone()
    table_sql = str(row["sql"] or "").lower() if row is not None else ""
    if "'proposed'" not in table_sql:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute(
            "ALTER TABLE project_context_candidates RENAME TO project_context_candidates_legacy"
        )
        conn.execute("DROP INDEX IF EXISTS idx_context_candidates_project_status")
        conn.executescript(
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
                source_attempt_id TEXT
                    REFERENCES agent_task_attempts(attempt_id) ON DELETE RESTRICT,
                source_message_start_seq INTEGER,
                source_message_end_seq INTEGER,
                source_output_start_seq INTEGER,
                source_output_end_seq INTEGER
            );
            """
        )
        conn.execute(
            """
            INSERT INTO project_context_candidates (
                candidate_id, project_id, content, status, created_at, created_by_user_id,
                source_metadata_json, accepted_by_user_id, accepted_at, rejected_by_user_id,
                rejected_at, rejection_reason, source_task_id, source_attempt_id,
                source_message_start_seq, source_message_end_seq,
                source_output_start_seq, source_output_end_seq
            )
            SELECT
                candidate_id, project_id, content,
                CASE WHEN status = 'pending' THEN 'proposed' ELSE status END,
                created_at, created_by_user_id, COALESCE(source_metadata_json, '{}'),
                accepted_by_user_id, accepted_at, rejected_by_user_id, rejected_at,
                rejection_reason, source_task_id, source_attempt_id,
                source_message_start_seq, source_message_end_seq,
                source_output_start_seq, source_output_end_seq
            FROM project_context_candidates_legacy
            """
        )
        conn.execute("DROP TABLE project_context_candidates_legacy")

    # Renaming/dropping the old table drops its append-only triggers.  Install
    # the complete final constraint set regardless of whether a development
    # database was already rebuilt by a prior interrupted migration.
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_context_candidates_project_status
        ON project_context_candidates(project_id, status, created_at);

        CREATE TRIGGER IF NOT EXISTS context_candidate_provenance_immutable
        BEFORE UPDATE OF project_id, content, created_at, created_by_user_id,
                         source_metadata_json, source_task_id, source_attempt_id,
                         source_message_start_seq, source_message_end_seq,
                         source_output_start_seq, source_output_end_seq
        ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidate provenance is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_delete_forbidden
        BEFORE DELETE ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidates are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_source_required_insert
        BEFORE INSERT ON project_context_candidates
        WHEN NEW.created_by_user_id IS NULL
          OR trim(NEW.created_by_user_id) = ''
          OR NEW.source_task_id IS NULL
          OR trim(NEW.source_task_id) = ''
          OR (NEW.source_message_start_seq IS NULL
              AND NEW.source_output_start_seq IS NULL)
          OR ((NEW.source_message_start_seq IS NULL)
              != (NEW.source_message_end_seq IS NULL))
          OR ((NEW.source_output_start_seq IS NULL)
              != (NEW.source_output_end_seq IS NULL))
          OR (NEW.source_message_start_seq IS NOT NULL
              AND (NEW.source_message_start_seq < 0
                   OR NEW.source_message_end_seq < NEW.source_message_start_seq))
          OR (NEW.source_output_start_seq IS NOT NULL
              AND (NEW.source_output_start_seq < 0
                   OR NEW.source_output_end_seq < NEW.source_output_start_seq))
        BEGIN SELECT RAISE(ABORT, 'context candidate requires Task source provenance'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_source_task_project_insert
        BEFORE INSERT ON project_context_candidates
        WHEN NOT EXISTS (
            SELECT 1 FROM tasks
            WHERE task_id = NEW.source_task_id AND project_id = NEW.project_id
        )
        BEGIN SELECT RAISE(ABORT, 'context candidate source Task must belong to Project'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_source_attempt_insert
        BEFORE INSERT ON project_context_candidates
        WHEN NEW.source_attempt_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM agent_task_attempts
              WHERE attempt_id = NEW.source_attempt_id AND task_id = NEW.source_task_id
          )
        BEGIN SELECT RAISE(ABORT, 'context candidate source Attempt must belong to Task'); END;

        CREATE TRIGGER IF NOT EXISTS context_candidate_source_range_insert
        BEFORE INSERT ON project_context_candidates
        WHEN (NEW.source_message_start_seq IS NOT NULL
              AND (
                  SELECT COUNT(*) FROM task_outputs
                  WHERE task_id = NEW.source_task_id
                    AND seq BETWEEN NEW.source_message_start_seq AND NEW.source_message_end_seq
              ) != NEW.source_message_end_seq - NEW.source_message_start_seq + 1)
          OR (NEW.source_output_start_seq IS NOT NULL
              AND (
                  SELECT COUNT(*) FROM task_outputs
                  WHERE task_id = NEW.source_task_id
                    AND seq BETWEEN NEW.source_output_start_seq AND NEW.source_output_end_seq
              ) != NEW.source_output_end_seq - NEW.source_output_start_seq + 1)
        BEGIN SELECT RAISE(ABORT, 'context candidate source range is not persisted'); END;
        """
    )


@registry.register(_DATABASE)
def migration_025_repair_legacy_maintenance_barrier(conn: sqlite3.Connection) -> None:
    """Repair a legacy control plane whose version marker outran barrier DDL.

    A historical 007/008 split could persist an ordinal schema version while
    leaving one or more maintenance tables absent.  Treat that as a narrowly
    defined *legacy-only* repair: a prepared or committed cutover is evidence
    that the control plane has already crossed a point where recreating a
    write fence would be unsafe.  Likewise, never repair through active
    mutations or live writer participants.  The DDL is additive and preserves
    an existing maintenance epoch and all stopped participant audit records.
    """

    state_table = "domain_maintenance_state"
    mutation_table = "domain_maintenance_mutations"
    participant_table = "domain_write_participants"
    state_exists = _table_exists(conn, state_table)
    mutations_exist = _table_exists(conn, mutation_table)
    participants_exist = _table_exists(conn, participant_table)

    if state_exists:
        _require_table_columns(
            conn,
            state_table,
            frozenset(
                {
                    "singleton",
                    "maintenance_epoch",
                    "is_active",
                    "actor_id",
                    "reason",
                    "entered_at",
                    "exited_at",
                }
            ),
        )
        state_row = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
    else:
        state_row = None

    if mutations_exist:
        _require_table_columns(
            conn,
            mutation_table,
            frozenset({"mutation_id", "maintenance_epoch", "started_at", "source"}),
        )
        mutation_columns = _table_columns(conn, mutation_table)
    else:
        mutation_columns = set()

    if participants_exist:
        _require_table_columns(
            conn,
            participant_table,
            frozenset(
                {
                    "participant_id",
                    "participant_type",
                    "process_id",
                    "observed_epoch",
                    "status",
                    "in_flight_mutations",
                    "unflushed_output_count",
                    "details_json",
                    "registered_at",
                    "heartbeat_at",
                    "drained_at",
                    "stopped_at",
                }
            ),
        )

    repair_needed = (
        not state_exists
        or state_row is None
        or not mutations_exist
        or "participant_id" not in mutation_columns
        or not participants_exist
    )
    if not repair_needed:
        return

    if not _table_exists(conn, "domain_cutover_state"):
        raise RuntimeError("cannot repair maintenance barrier without domain cutover state")
    cutover = conn.execute("SELECT state FROM domain_cutover_state WHERE singleton = 1").fetchone()
    if cutover is None or str(cutover["state"]) != "legacy":
        raise RuntimeError("maintenance barrier repair is allowed only before domain cutover")
    if state_row is not None and bool(state_row["is_active"]):
        raise RuntimeError("cannot repair maintenance barrier while maintenance is active")
    if mutations_exist:
        active_mutations = conn.execute(
            "SELECT COUNT(*) FROM domain_maintenance_mutations"
        ).fetchone()
        if active_mutations is None or int(active_mutations[0]) != 0:
            raise RuntimeError("cannot repair maintenance barrier with in-flight mutations")
    if participants_exist:
        active_participants = conn.execute(
            "SELECT COUNT(*) FROM domain_write_participants WHERE status != 'stopped'"
        ).fetchone()
        if active_participants is None or int(active_participants[0]) != 0:
            raise RuntimeError("cannot repair maintenance barrier with live writer participants")

    _ensure_domain_maintenance_barrier_base(conn)
    _ensure_domain_write_participant_schema(conn)


@registry.register(_DATABASE)
def migration_026_overview_refresh_idempotency(conn: sqlite3.Connection) -> None:
    """Persist caller keys even when multiple requests share one active job."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS overview_refresh_idempotency_requests (
            owner_user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES overview_refresh_jobs(job_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, idempotency_key)
        );

        CREATE INDEX IF NOT EXISTS idx_overview_refresh_idempotency_job
        ON overview_refresh_idempotency_requests(job_id);
        """
    )

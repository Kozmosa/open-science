from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "agentic_researcher"


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


@registry.register(_DATABASE)
def migration_008_domain_schema_expand(conn: sqlite3.Connection) -> None:
    """Add the v2 control-plane schema without switching any write path."""
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

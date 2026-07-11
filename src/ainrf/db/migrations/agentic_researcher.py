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

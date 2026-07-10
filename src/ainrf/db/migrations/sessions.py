from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "sessions"


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            task_count INTEGER NOT NULL DEFAULT 0,
            total_duration_ms INTEGER NOT NULL DEFAULT 0,
            total_cost_usd REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_attempts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            task_id TEXT,
            parent_attempt_id TEXT,
            attempt_seq INTEGER NOT NULL,
            intervention_reason TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            token_usage_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_session ON task_attempts(session_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON task_sessions(project_id, status)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON task_sessions(created_at)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_parent ON task_attempts(parent_attempt_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_status ON task_attempts(status)")


@registry.register(_DATABASE)
def migration_002_owner_user_id(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE task_sessions ADD COLUMN owner_user_id TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


@registry.register(_DATABASE)
def migration_003_performance_indexes(conn: sqlite3.Connection) -> None:
    """Indexes for multi-tenant filtering and attempt-seq lookups."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_owner ON task_sessions(owner_user_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_session_seq "
        "ON task_attempts(session_id, attempt_seq)"
    )

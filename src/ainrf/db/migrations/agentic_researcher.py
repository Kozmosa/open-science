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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_environment ON tasks(environment_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outputs_kind ON task_outputs(kind)")


@registry.register(_DATABASE)
def migration_002_latest_output_seq(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN latest_output_seq INTEGER NOT NULL DEFAULT 0"
        )
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

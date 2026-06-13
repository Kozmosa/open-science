from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "auth"


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            activated_at TEXT,
            last_login_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_collaborators (
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            added_by_user_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS environment_access (
            environment_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            max_concurrent_tasks INTEGER,
            granted_by_user_id TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY (environment_id, user_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_user ON project_collaborators(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_env_access_user ON environment_access(user_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, attempted_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip_address, attempted_at)"
    )


@registry.register(_DATABASE)
def migration_002_must_change_password(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # column already exists


@registry.register(_DATABASE)
def migration_003_admin_role_fix(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE users SET role = 'admin' WHERE username = 'admin' AND role != 'admin'"
    )


@registry.register(_DATABASE)
def migration_004_login_attempts_cleanup_index(conn: sqlite3.Connection) -> None:
    """Index on attempted_at so periodic cleanup DELETE is a range scan, not a full table scan."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_attempted_at "
        "ON login_attempts(attempted_at)"
    )

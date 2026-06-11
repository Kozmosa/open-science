from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "terminal"


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_environment_bindings (
            binding_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            remote_login_user TEXT NOT NULL,
            default_shell TEXT,
            default_workdir TEXT,
            mux_kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, environment_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_session_pairs (
            binding_id TEXT PRIMARY KEY,
            personal_session_name TEXT NOT NULL,
            agent_session_name TEXT,
            personal_status TEXT NOT NULL,
            agent_status TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            personal_started_at TEXT,
            personal_closed_at TEXT,
            last_verified_at TEXT,
            last_personal_attach_at TEXT,
            last_agent_attach_at TEXT,
            detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(binding_id) REFERENCES user_environment_bindings(binding_id)
        )
        """
    )

from __future__ import annotations

import sqlite3
from collections.abc import Callable

MigrationFn = Callable[[sqlite3.Connection], None]


class MigrationRegistry:
    """Per-database ordered migration list."""

    def __init__(self) -> None:
        self._migrations: dict[str, list[MigrationFn]] = {}

    def register(self, database_name: str) -> Callable[[MigrationFn], MigrationFn]:
        """Decorator to register a migration for a database.

        Migrations are ordered by their function name convention
        (``migration_NNN_description``). Register them in any order;
        they are sorted by name before execution.
        """

        def decorator(fn: MigrationFn) -> MigrationFn:
            self._migrations.setdefault(database_name, []).append(fn)
            self._migrations[database_name].sort(key=lambda f: f.__name__)
            return fn

        return decorator

    def get_pending(self, database_name: str, current_version: int) -> list[MigrationFn]:
        migrations = self._migrations.get(database_name, [])
        return migrations[current_version:]


# Module-level singleton
registry = MigrationRegistry()


def ensure_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_version (
            database TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def current_version(conn: sqlite3.Connection, database_name: str) -> int:
    row = conn.execute(
        "SELECT version FROM _schema_version WHERE database = ?", (database_name,)
    ).fetchone()
    return row[0] if row else 0


def set_version(conn: sqlite3.Connection, database_name: str, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO _schema_version (database, version) VALUES (?, ?)",
        (database_name, version),
    )


def run_pending(
    conn: sqlite3.Connection,
    database_name: str,
    reg: MigrationRegistry | None = None,
) -> int:
    """Run all pending migrations for *database_name*.

    Returns the number of migrations applied.  Each migration runs
    inside the caller's transaction; if any migration raises the
    caller is responsible for rolling back.
    """
    r = reg or registry
    ensure_schema_table(conn)
    version = current_version(conn, database_name)
    pending = r.get_pending(database_name, version)
    for i, migration in enumerate(pending):
        migration(conn)
        set_version(conn, database_name, version + i + 1)
    conn.commit()
    return len(pending)

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

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


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
        is not None
    )


def _database_path(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if str(row[1]) != "main" or not isinstance(row[2], str) or not row[2]:
            continue
        try:
            return Path(row[2]).resolve()
        except (OSError, ValueError):
            return None
    return None


def _maintenance_is_active(conn: sqlite3.Connection, database_name: str) -> bool:
    """Read the shared maintenance flag without creating or migrating state.

    Constructors for auth, Literature, session, and control-plane services may
    all call ``run_pending`` before their process registers as a participant.
    A persisted maintenance epoch must therefore reject pending migration DDL
    instead of silently mutating a source snapshot during a restart.
    """

    if database_name == "agentic_researcher":
        control = conn
        close_control = False
    else:
        database_path = _database_path(conn)
        if database_path is None:
            return False
        control_path = database_path.parent / "agentic_researcher.sqlite3"
        if not control_path.is_file():
            return False
        # Immutable reads do not replay a live WAL.  When one exists, use a
        # normal read-only connection to observe the actual maintenance flag;
        # it cannot write the database or WAL, and its transient shared-memory
        # cache is not an authoritative source member.  Without a WAL, use
        # immutable mode so this guard does not create a sidecar at all.
        uri_suffix = (
            "?mode=ro"
            if control_path.with_name(f"{control_path.name}-wal").exists()
            else "?mode=ro&immutable=1"
        )
        try:
            control = sqlite3.connect(
                f"{control_path.as_uri()}{uri_suffix}",
                uri=True,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise RuntimeError("cannot inspect domain maintenance state before migration") from exc
        close_control = True

    try:
        if not _has_table(control, "domain_maintenance_state"):
            return False
        row = control.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        return row is not None and bool(row[0])
    finally:
        if close_control:
            control.close()


def _current_version_without_creating(conn: sqlite3.Connection, database_name: str) -> int:
    if not _has_table(conn, "_schema_version"):
        return 0
    return current_version(conn, database_name)


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
    migration_count = len(r.get_pending(database_name, 0))
    if _maintenance_is_active(conn, database_name):
        persisted_version = _current_version_without_creating(conn, database_name)
        if persisted_version < migration_count:
            raise RuntimeError(
                f"domain maintenance is active; refusing {database_name} migration "
                f"from version {persisted_version} to {migration_count}"
            )
    ensure_schema_table(conn)
    version = current_version(conn, database_name)
    if version < 0 or version > migration_count:
        raise RuntimeError(
            f"unsupported {database_name} schema version {version}; "
            f"this binary supports versions 0 through {migration_count}"
        )
    pending = r.get_pending(database_name, version)
    for i, migration in enumerate(pending):
        migration(conn)
        set_version(conn, database_name, version + i + 1)
    conn.commit()
    return len(pending)

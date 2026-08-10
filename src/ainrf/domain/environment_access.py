"""Shared read-only checks for durable Environment execution grants."""

from __future__ import annotations

import sqlite3
import stat
from contextlib import closing
from pathlib import Path


_SQLITE_HEADER = b"SQLite format 3\x00"
_ENVIRONMENT_ACCESS_COLUMNS = frozenset({"environment_id", "user_id", "status"})


def _sqlite_authority_signature(path: Path) -> tuple[int, int, int, int, int] | None:
    """Validate the main file without suppressing an adjacent WAL."""

    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            return None
        with path.open("rb") as stream:
            if stream.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
                return None
        after = path.lstat()
    except OSError:
        return None
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    return after_signature if before_signature == after_signature else None


def has_active_environment_execution_grant(
    auth_db_path: Path,
    *,
    environment_id: str,
    user_id: str,
) -> bool:
    """Return whether *user_id* has an explicit active grant for an Environment.

    The auth database is a separate durable authority and is intentionally
    opened read-only.  A missing database, unavailable file, missing table, or
    any other read error is an authorization failure rather than a runtime
    exception.  Environment ownership and administrative visibility are not
    execution grants and therefore are not considered here.
    """

    try:
        main_signature = _sqlite_authority_signature(auth_db_path)
        if main_signature is None:
            return False
        auth_uri = f"{auth_db_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
            table = conn.execute(
                "SELECT type FROM sqlite_master WHERE name = 'environment_access'"
            ).fetchone()
            if table is None or table[0] != "table":
                return False
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(environment_access)")}
            if not _ENVIRONMENT_ACCESS_COLUMNS.issubset(columns):
                return False
            row = conn.execute(
                """
                SELECT 1 FROM environment_access
                WHERE environment_id = ? AND user_id = ? AND status = 'active'
                """,
                (environment_id, user_id),
            ).fetchone()
            # Main-file replacement can race the header probe.  A second
            # signature check rejects that ordinary path-swap window; a
            # cross-file main+WAL snapshot still cannot be made atomic here.
            if _sqlite_authority_signature(auth_db_path) != main_signature:
                return False
    except (OSError, sqlite3.Error):
        return False
    return row is not None

"""Shared SQLite connection factory.

Every service that opens a SQLite database should use :func:`connect` so that
all connections share the same PRAGMA baseline: WAL journal mode, busy timeout
for concurrent-write resilience, foreign-key enforcement, and consistent
row-factory behaviour.

Usage::

    from ainrf.db.connection import connect

    with closing(connect(db_path)) as conn:
        conn.execute("SELECT ...")
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Milliseconds SQLite will wait when a write conflict is detected before
# raising ``OperationalError: database is locked``.  5000 ms is a pragmatic
# choice for a single-writer WAL workload: it covers the typical write
# transaction time (~1-50 ms) with plenty of headroom.  For 20-50 concurrent
# clients, the average wait is near-zero; this exists to absorb transient
# spikes, not to paper over systemic lock contention.
BUSY_TIMEOUT_MS = 5000

# Default SQLite page-cache size in KiB.  -2000 means 2 MiB per connection,
# which is a reasonable floor for multi-tenant workloads without blowing
# memory.  Individual services can override via the *pragmas* parameter.
DEFAULT_CACHE_SIZE_KB = -2000


def connect(
    db_path: str,
    *,
    isolation_level: str = "IMMEDIATE",
    busy_timeout_ms: int = BUSY_TIMEOUT_MS,
    cache_size_kb: int = DEFAULT_CACHE_SIZE_KB,
    row_factory: type[sqlite3.Row] | None = sqlite3.Row,
    foreign_keys: bool = True,
    extra_pragmas: dict[str, object] | None = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with a consistent PRAGMA baseline.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file.
    isolation_level:
        Transaction isolation.  ``"IMMEDIATE"`` (the default) acquires the
        write lock at ``BEGIN`` rather than deferring to the first write,
        which avoids ``SQLITE_BUSY`` on lock upgrade.
    busy_timeout_ms:
        How long (ms) SQLite will wait for a locked database before raising
        ``OperationalError``.  The default 5000 ms covers transient write
        contention under moderate concurrency.
    cache_size_kb:
        Negative value → KiB of cache; positive value → pages.  Default is
        ``-2000`` (2 MiB per connection).
    row_factory:
        Defaults to ``sqlite3.Row`` so rows can be accessed by column name.
        Pass ``None`` to keep the stdlib default (tuple rows).
    foreign_keys:
        When ``True`` (the default), enables ``PRAGMA foreign_keys = ON`` so
        that ``FOREIGN KEY`` constraints are actually enforced.
    extra_pragmas:
        Additional ``PRAGMA key = value`` pairs applied after the baseline.

    Returns
    -------
    An open ``sqlite3.Connection``.
    """
    conn = sqlite3.connect(db_path, isolation_level=isolation_level)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute(f"PRAGMA cache_size = {int(cache_size_kb)}")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    if row_factory is not None:
        conn.row_factory = row_factory
    if extra_pragmas:
        for key, val in extra_pragmas.items():
            conn.execute(f"PRAGMA {key} = {val}")
    return conn


def atomic_write_json(path: Path, payload: object) -> None:
    """Atomically write *payload* as JSON to *path*.

    Writes to a temporary file first, then renames (POSIX atomic) to the
    target path.  This prevents corruption if the process crashes mid-write.
    """
    import json
    import os

    tmp = Path(str(path) + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)  # atomic on POSIX

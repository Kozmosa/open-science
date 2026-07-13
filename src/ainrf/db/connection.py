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
from os import PathLike
from pathlib import Path
from typing import Literal, cast

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
    db_path: str | PathLike[str],
    *,
    isolation_level: Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None = "IMMEDIATE",
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

    Writes to a unique temporary file in the same directory first, then renames
    (POSIX atomic) to the target path.  This prevents corruption if the process
    crashes mid-write and avoids temp-file collisions under concurrent writers.
    """
    import json
    import os
    import tempfile

    path = Path(path)
    _reject_sealed_legacy_source_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(suffix=".tmp", prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp_str, path)
    except Exception:
        try:
            os.unlink(tmp_str)
        except FileNotFoundError:
            pass
        raise


def _reject_sealed_legacy_source_write(path: Path) -> None:
    """Block atomic replacement of a legacy JSON source after v2 cutover.

    ``chmod 0444`` alone does not stop the old registry implementation: it
    writes a temporary sibling and atomically renames it over the target while
    the shared runtime directory remains writable for the v2 SQLite files.
    The cutover seal journal is intentionally dependency-free here so this
    low-level helper does not import the domain-control package and create a
    database import cycle.  Invalid or unrelated journals do not affect normal
    JSON persistence; a valid finalized journal blocks exactly the listed
    source paths.  The journal itself is always exempt so the controller can
    atomically create, finalize, and remove it.
    """

    import json

    try:
        resolved = path.resolve()
    except OSError:
        return
    state_root: Path | None = None
    for ancestor in (resolved.parent, *resolved.parents):
        if ancestor.name in {"runtime", "session-states"}:
            state_root = ancestor.parent
            break
    if state_root is None:
        return
    journal = state_root / "runtime" / "domain-legacy-source-seal.json"
    if resolved == journal:
        return
    try:
        relative_path = resolved.relative_to(state_root).as_posix()
    except ValueError:
        return
    try:
        raw_payload = json.loads(journal.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw_payload, dict):
        return
    payload = cast(dict[str, object], raw_payload)
    if not _is_valid_finalized_legacy_seal(payload, state_root):
        return
    files = payload.get("files")
    if not isinstance(files, list):
        return
    sealed_paths: set[str] = set()
    for raw_item in files:
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, object], raw_item)
        sealed_path = item.get("relative_path")
        if isinstance(sealed_path, str):
            sealed_paths.add(sealed_path)
    if relative_path in sealed_paths:
        raise PermissionError(
            f"legacy source is sealed by a committed domain cutover: {relative_path}"
        )


def _is_valid_finalized_legacy_seal(payload: object, state_root: Path) -> bool:
    """Validate only the dependency-free shape needed by the JSON write gate."""

    if not isinstance(payload, dict):
        return False
    seal = cast(dict[str, object], payload)
    if (
        seal.get("version") != 1
        or seal.get("phase") != "sealed"
        or seal.get("state_root") != state_root.name
        or not _is_sha256(seal.get("inventory_sha256"))
    ):
        return False
    files = seal.get("files")
    if not isinstance(files, list):
        return False
    paths: set[str] = set()
    for raw_item in files:
        if not isinstance(raw_item, dict):
            return False
        item = cast(dict[str, object], raw_item)
        relative_path = item.get("relative_path")
        original_mode = item.get("original_mode")
        sealed_mode = item.get("sealed_mode")
        if not isinstance(relative_path, str) or not relative_path:
            return False
        candidate = Path(relative_path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or not isinstance(original_mode, int)
            or not isinstance(sealed_mode, int)
            or not 0 <= original_mode <= 0o7777
            or not 0 <= sealed_mode <= 0o7777
            or sealed_mode & 0o222
            or relative_path in paths
        ):
            return False
        paths.add(relative_path)
    return True


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )

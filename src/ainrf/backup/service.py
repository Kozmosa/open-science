"""Backup and restore service for OpenScience persistent state.

Creates self-describing tar.gz archives containing SQLite database dumps,
JSON config, and optionally workspace/tenant data.  Every archive carries a
``manifest.json`` with version, timestamps, and per-file SHA-256 checksums so
that integrity can be verified independently of the restore path.

SQLite databases are backed up via ``sqlite3.Connection.backup()`` which
produces a consistent snapshot even while the server is running.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, cast
from uuid import uuid4

_LOG = logging.getLogger(__name__)

_BACKUP_VERSION = 3

# Known SQLite databases relative to <state_root>/runtime/.  These names keep
# the original manifest layout stable, while v3 also discovers any future
# ``*.sqlite3`` file below ``runtime/``.
_SQLITE_DATABASES: tuple[str, ...] = (
    "auth.sqlite3",
    "sessions.sqlite3",
    "agentic_researcher.sqlite3",
    "literature.sqlite3",
    "terminal_state.sqlite3",
    "task_harness.sqlite3",  # legacy
)

# Top-level config files relative to <state_root>/
_TOPLEVEL_CONFIGS: tuple[str, ...] = (
    "config.json",
    "search-settings.json",
    "admin_initial_password.txt",
)

# Runtime JSON files relative to <state_root>/runtime/.  Their historical
# ``config/<name>`` archive paths remain stable; other runtime JSON is stored
# under ``config/runtime/<relative-path>`` so it can never collide with a
# top-level config member.
_RUNTIME_CONFIGS: tuple[str, ...] = (
    "projects.json",
    "task_edges.json",
    "workspaces.json",
)

# The pre-v3 restore fallback.  New v3 archives discover every non-reserved
# state subdirectory, but version-2 archives did not inventory those members.
_STATE_DIRS: tuple[str, ...] = (
    "session-states",
    "detections",
)

_RESERVED_STATE_ROOTS = frozenset({"runtime", "workspaces", "tenants"})
_ARCHIVE_RESERVED_ROOTS = frozenset({"databases", "config", "workspaces", "tenants"})

# SQLite's online backup API gives a transactional snapshot while writers are
# active.  A read-only mount can still reject that direct path when SQLite
# needs WAL shared-memory bookkeeping, so the fallback takes a stable raw
# copy in private writable storage.  Neither path is allowed to wait forever:
# callers get a hard failure instead of an archive with an unverifiable source
# race.
_SQLITE_SNAPSHOT_DEADLINE_SECONDS = 5.0
_SQLITE_SNAPSHOT_RETRY_INTERVAL_SECONDS = 0.025
_SQLITE_SNAPSHOT_PAGE_COUNT = 128


# ── helpers ───────────────────────────────────────────────────────


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_stream(stream: IO[bytes]) -> str:
    """Return the SHA-256 of a readable binary tar member stream."""
    h = hashlib.sha256()
    while True:
        chunk = stream.read(1 << 16)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


class _SQLiteSnapshotDeadlineExceeded(TimeoutError):
    """The source never yielded a bounded, trustworthy SQLite snapshot."""


def _dump_sqlite_safe(source: Path, dest: Path) -> None:
    """Create a consistent snapshot without writing to the source volume.

    Prefer SQLite's online backup API against a ``mode=ro`` source.  It holds
    a real SQLite read snapshot and is consequently safe while a WAL writer is
    active; source-byte fingerprints are neither needed nor meaningful for
    that transactionally consistent path.  Some read-only mounts cannot open
    WAL shared memory directly, so only that failed direct attempt falls back
    to a private staged copy.  The fallback retries until its complete main /
    WAL / rollback-journal member set is stable, then fails closed at the
    shared deadline rather than archiving a raced raw copy.
    """

    dest.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _SQLITE_SNAPSHOT_DEADLINE_SECONDS
    direct_error: Exception | None = None
    try:
        _dump_sqlite_online(source, dest, deadline=deadline)
    except (OSError, sqlite3.Error, _SQLiteSnapshotDeadlineExceeded) as exc:
        # ``mode=ro`` is intentionally strict: if SQLite cannot use the
        # source's WAL shared-memory state without a write, take the existing
        # copy-based route instead.  The fallback retains the same deadline,
        # so a lock storm never turns into an unbounded backup operation.
        direct_error = exc
        _remove_sqlite_sidecars(dest)
        dest.unlink(missing_ok=True)
        _LOG.debug(
            "direct SQLite snapshot unavailable for %s; trying stable staged copy (%s)",
            source.name,
            type(exc).__name__,
        )

    if direct_error is None:
        _remove_sqlite_sidecars(dest)
        return

    try:
        _dump_sqlite_staged_with_retry(source, dest, deadline=deadline)
    except _SQLiteSnapshotDeadlineExceeded as exc:
        raise ValueError(
            f"SQLite source did not stabilize before snapshot deadline: {source.name}"
        ) from exc
    except (OSError, sqlite3.Error) as exc:
        # A runtime filename alone is safe operator context; avoid leaking an
        # absolute state-root path while making an invalid ``*.sqlite3``
        # member actionable.  A complete v3 backup must not silently omit it.
        raise ValueError(
            f"Cannot create a read-only SQLite snapshot for {source.name}: {type(exc).__name__}"
        ) from exc
    finally:
        _remove_sqlite_sidecars(dest)


def _dump_sqlite_online(source: Path, dest: Path, *, deadline: float) -> None:
    """Use SQLite's read-only online-backup API and atomically publish it."""

    _raise_if_sqlite_snapshot_expired(deadline)
    candidate = _sqlite_snapshot_candidate(dest)
    source_conn: sqlite3.Connection | None = None
    destination_conn: sqlite3.Connection | None = None
    try:
        source_uri = f"{source.resolve().as_uri()}?mode=ro"
        source_conn = sqlite3.connect(source_uri, uri=True, timeout=_sqlite_timeout(deadline))
        source_conn.execute("PRAGMA query_only = ON")
        destination_conn = sqlite3.connect(candidate)
        _backup_sqlite_connection(source_conn, destination_conn, deadline=deadline)
        destination_conn.close()
        destination_conn = None
        source_conn.close()
        source_conn = None
        os.replace(candidate, dest)
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()
        candidate.unlink(missing_ok=True)


def _dump_sqlite_staged_with_retry(source: Path, dest: Path, *, deadline: float) -> None:
    """Create a snapshot from a complete raw-copy observation that stayed stable."""

    while True:
        _raise_if_sqlite_snapshot_expired(deadline)
        snapshot_root = dest.parent / f".{dest.name}.source-{uuid4().hex}"
        candidate = _sqlite_snapshot_candidate(dest)
        source_conn: sqlite3.Connection | None = None
        destination_conn: sqlite3.Connection | None = None
        try:
            source_members = _sqlite_source_members(source)
            before = _sqlite_source_fingerprint(source_members)
            snapshot_root.mkdir()
            for member in source_members:
                _raise_if_sqlite_snapshot_expired(deadline)
                shutil.copyfile(member, snapshot_root / member.name)
            if before != _sqlite_source_fingerprint(_sqlite_source_members(source)):
                _wait_for_sqlite_snapshot_retry(deadline)
                continue

            # The staged copy can safely perform WAL recovery/checkpoint work.
            # It is query-only at the SQL layer, and the original source mount
            # remains untouched throughout this operation.
            source_conn = sqlite3.connect(snapshot_root / source.name)
            source_conn.execute("PRAGMA query_only = ON")
            destination_conn = sqlite3.connect(candidate)
            _backup_sqlite_connection(source_conn, destination_conn, deadline=deadline)
            destination_conn.close()
            destination_conn = None
            source_conn.close()
            source_conn = None
            os.replace(candidate, dest)
            return
        finally:
            if destination_conn is not None:
                destination_conn.close()
            if source_conn is not None:
                source_conn.close()
            candidate.unlink(missing_ok=True)
            shutil.rmtree(snapshot_root, ignore_errors=True)


def _sqlite_snapshot_candidate(dest: Path) -> Path:
    """Return a private destination that is atomically promoted on success."""

    return dest.parent / f".{dest.name}.snapshot-{uuid4().hex}"


def _backup_sqlite_connection(
    source_conn: sqlite3.Connection,
    destination_conn: sqlite3.Connection,
    *,
    deadline: float,
) -> None:
    """Copy a fixed SQLite read transaction without exceeding *deadline*."""

    def progress(_status: int, _remaining: int, _total: int) -> None:
        _raise_if_sqlite_snapshot_expired(deadline)

    source_conn.backup(
        destination_conn,
        pages=_SQLITE_SNAPSHOT_PAGE_COUNT,
        progress=progress,
        sleep=min(_SQLITE_SNAPSHOT_RETRY_INTERVAL_SECONDS, _sqlite_timeout(deadline)),
    )
    _raise_if_sqlite_snapshot_expired(deadline)


def _raise_if_sqlite_snapshot_expired(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise _SQLiteSnapshotDeadlineExceeded()


def _sqlite_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _SQLiteSnapshotDeadlineExceeded()
    return min(1.0, remaining)


def _wait_for_sqlite_snapshot_retry(deadline: float) -> None:
    _raise_if_sqlite_snapshot_expired(deadline)
    time.sleep(min(_SQLITE_SNAPSHOT_RETRY_INTERVAL_SECONDS, _sqlite_timeout(deadline)))


def _remove_sqlite_sidecars(path: Path) -> None:
    """Ensure the staged archive contains one logical SQLite member only."""

    for suffix in ("-wal", "-shm", "-journal"):
        path.with_name(f"{path.name}{suffix}").unlink(missing_ok=True)


def _sqlite_source_members(source: Path) -> tuple[Path, ...]:
    """Return database bytes that must be copied atomically for a raw fallback.

    SQLite's ``-shm`` file is a disposable shared-memory index/lock file, not
    persistent database state.  Deliberately omit it: copying it turns normal
    reader/writer lock churn into a false source race, while the writable
    private staging directory can safely rebuild it from main + WAL.
    """

    members = tuple(
        path
        for path in (
            source,
            *(source.with_name(f"{source.name}{suffix}") for suffix in ("-wal", "-journal")),
        )
        if path.is_file()
    )
    if not members or members[0] != source:
        raise ValueError(f"SQLite source is missing: {source.name}")
    return members


def _sqlite_source_fingerprint(
    members: tuple[Path, ...],
) -> tuple[tuple[str, int, int, int, str], ...]:
    """Fingerprint every raw SQLite member before/after a read-only copy."""

    return tuple(
        (
            member.name,
            member.stat().st_ino,
            member.stat().st_mtime_ns,
            member.stat().st_size,
            _sha256_of(member),
        )
        for member in members
    )


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ── manifest ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FileMeta:
    size: int
    sha256: str
    source_path: str = ""
    schema_version: int | None = None
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None


@dataclass(slots=True)
class BackupManifest:
    version: int = _BACKUP_VERSION
    created_at: str = ""
    databases: dict[str, FileMeta] = field(default_factory=dict)
    config_files: dict[str, FileMeta] = field(default_factory=dict)
    # Version 3 inventories every regular archive member, including nested
    # state, workspace, and tenant files.  The old database/config maps are
    # retained so existing callers and version-2 archives remain compatible.
    files: dict[str, FileMeta] = field(default_factory=dict)
    tree_sha256: str | None = None
    includes_workspaces: bool = False
    includes_tenants: bool = False

    # -- serialisation --------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> BackupManifest:
        d = json.loads(text)
        for key in ("databases", "config_files", "files"):
            if key in d and isinstance(d[key], dict):
                d[key] = {k: FileMeta(**v) for k, v in d[key].items()}
        return cls(**d)


StagedRestoreValidator = Callable[[Path, BackupManifest], None]
"""A read/validate hook invoked before a staged restore is promoted."""


_RESTORE_PROMOTION_JOURNAL_VERSION = 1
_RESTORE_GENERATION_ATTESTATION_VERSION = 1
_RESTORE_GENERATION_ATTESTATION_NAME = ".openscience-restore-generation.json"
_ACTIVE_GENERATION_PROMOTION_JOURNAL_VERSION = 1
_HIGH_RISK_RESTORE_REPORT_VERSION = 1
_HIGH_RISK_RESTORE_REPORT_NAME = ".openscience-restore-high-risk-report.json"
_HIGH_RISK_REPORT_PATH_LIMIT = 256
_HIGH_RISK_REPORT_GIT_REPOSITORY_LIMIT = 32
_HIGH_RISK_REPORT_GIT_PATH_LIMIT = 128
_ACTIVE_GENERATION_OPERATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class RestoreGenerationAttestation:
    """Evidence that a state root was created by the verified restore path."""

    generation_id: str
    manifest_digest: str
    restored_at: str


@dataclass(frozen=True, slots=True)
class ActiveGenerationPromotion:
    """Result of atomically selecting an already-verified state generation."""

    active_pointer: Path
    generation_root: Path
    previous_generation_root: Path | None
    operation_id: str | None
    recovered: bool = False


def _manifest_digest(manifest: BackupManifest) -> str:
    """Return the stable journal binding for one already-verified archive."""

    encoded = json.dumps(asdict(manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fsync_directory(path: Path) -> None:
    """Durably publish a directory entry update before continuing promotion."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_promotion_journal(
    journal_path: Path,
    payload: dict[str, object],
    *,
    exclusive: bool = False,
) -> None:
    """Persist one promotion journal revision before the next rename.

    The initial revision uses ``O_EXCL`` so two restore attempts cannot replace
    each other's safety record.  Later revisions use a fsynced sibling file
    and ``os.replace``; a crash can leave either complete revision, both of
    which the recovery path understands.
    """

    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        descriptor = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(journal_path.parent)
        return

    temporary = journal_path.parent / f".{journal_path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, journal_path)
        _fsync_directory(journal_path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_all(descriptor: int, content: bytes) -> None:
    """Write every byte to a low-level journal descriptor."""

    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("could not write restore promotion journal")
        offset += written


def _remove_promotion_journal(journal_path: Path) -> None:
    journal_path.unlink(missing_ok=True)
    if journal_path.parent.is_dir():
        _fsync_directory(journal_path.parent)


def _journal_pair_paths(payload: dict[str, object]) -> tuple[tuple[Path, Path], ...]:
    """Parse only safe sibling candidate/target pairs from durable JSON."""

    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("restore promotion journal has no candidate/target pairs")
    parsed: list[tuple[Path, Path]] = []
    for entry in pairs:
        if not isinstance(entry, dict):
            raise ValueError("restore promotion journal has an invalid pair")
        pair = cast(dict[str, object], entry)
        raw_candidate = pair.get("candidate")
        raw_target = pair.get("target")
        if not isinstance(raw_candidate, str) or not isinstance(raw_target, str):
            raise ValueError("restore promotion journal pair paths are invalid")
        candidate = Path(raw_candidate)
        target = Path(raw_target)
        if (
            not candidate.is_absolute()
            or not target.is_absolute()
            or candidate.parent != target.parent
            or not candidate.name.startswith(f".{target.name}.restore-")
        ):
            raise ValueError("restore promotion journal pair is outside its staged sibling root")
        parsed.append((candidate, target))
    return tuple(parsed)


def _journal_process_is_alive(payload: dict[str, object]) -> bool:
    """Avoid rolling back a promotion that is still executing on this host."""

    hostname = payload.get("hostname")
    process_id = payload.get("process_id")
    if not isinstance(hostname, str) or hostname != socket.gethostname():
        # A journal from another host cannot be distinguished from a live
        # network-volume promotion, so recovery must fail closed.
        return True
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
        return True
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _recover_pending_restore_promotion(
    journal_path: Path,
    *,
    expected_manifest_digest: str,
) -> str | None:
    """Recover a crashed staged-root promotion without touching active state.

    ``"completed"`` means every candidate had already been atomically renamed
    before the process died, so the verified generation remains published and
    only the stale journal is removed.  ``"rolled_back"`` moves any partially
    published roots back to their private candidates and removes them.  Any
    malformed or ambiguous state is left intact and fails closed.
    """

    if not journal_path.exists():
        return None
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "restore promotion journal is unreadable; manual recovery is required"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("restore promotion journal is invalid; manual recovery is required")
    if payload.get("version") != _RESTORE_PROMOTION_JOURNAL_VERSION:
        raise ValueError(
            "restore promotion journal version is unsupported; manual recovery is required"
        )
    if payload.get("manifest_digest") != expected_manifest_digest:
        raise ValueError("restore promotion journal archive does not match this restore request")
    if _journal_process_is_alive(payload):
        raise ValueError("restore promotion is already in progress; refusing concurrent recovery")
    pairs = _journal_pair_paths(payload)

    moved: list[tuple[Path, Path]] = []
    staged: list[tuple[Path, Path]] = []
    for candidate, target in pairs:
        candidate_exists = candidate.exists()
        target_exists = target.exists()
        if candidate_exists and not target_exists:
            staged.append((candidate, target))
        elif target_exists and not candidate_exists:
            moved.append((candidate, target))
        else:
            raise ValueError("restore promotion state is ambiguous; manual recovery is required")

    if len(moved) == len(pairs):
        _remove_promotion_journal(journal_path)
        return "completed"

    for candidate, target in reversed(moved):
        os.replace(target, candidate)
        _fsync_directory(target.parent)
    for candidate, _target in pairs:
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
    _remove_promotion_journal(journal_path)
    return "rolled_back"


def _write_restore_generation_attestation(
    generation_root: Path,
    manifest: BackupManifest,
) -> RestoreGenerationAttestation:
    """Seal a restored root after all archive and domain checks have passed.

    The attestation is deliberately written only after reconciliation and all
    caller validators succeeded.  Selecting a generation through the active
    pointer controller therefore cannot accidentally expose an arbitrary
    directory that merely happens to look like an OpenScience state root.
    """

    attestation = RestoreGenerationAttestation(
        generation_id=uuid4().hex,
        manifest_digest=_manifest_digest(manifest),
        restored_at=datetime.now(timezone.utc).isoformat(),
    )
    payload = {
        "version": _RESTORE_GENERATION_ATTESTATION_VERSION,
        "generation_id": attestation.generation_id,
        "manifest_digest": attestation.manifest_digest,
        "restored_at": attestation.restored_at,
    }
    marker_path = generation_root / _RESTORE_GENERATION_ATTESTATION_NAME
    temporary = generation_root / f".{marker_path.name}.{uuid4().hex}.tmp"
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, marker_path)
        _fsync_directory(generation_root)
    finally:
        temporary.unlink(missing_ok=True)
    return attestation


def _read_restore_generation_attestation(generation_root: Path) -> RestoreGenerationAttestation:
    """Read the narrow, durable evidence required for active promotion."""

    marker_path = generation_root / _RESTORE_GENERATION_ATTESTATION_NAME
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "state generation is not a verified restore or its attestation is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("state generation attestation is invalid")
    if payload.get("version") != _RESTORE_GENERATION_ATTESTATION_VERSION:
        raise ValueError("state generation attestation version is unsupported")
    generation_id = payload.get("generation_id")
    manifest_digest = payload.get("manifest_digest")
    restored_at = payload.get("restored_at")
    if (
        not isinstance(generation_id, str)
        or not generation_id
        or not isinstance(manifest_digest, str)
        or len(manifest_digest) != 64
        or any(character not in "0123456789abcdef" for character in manifest_digest)
        or not isinstance(restored_at, str)
        or not restored_at
    ):
        raise ValueError("state generation attestation is incomplete")
    return RestoreGenerationAttestation(
        generation_id=generation_id,
        manifest_digest=manifest_digest,
        restored_at=restored_at,
    )


def _absolute_lexical_path(path: Path) -> Path:
    """Canonicalize a pointer parent without resolving the pointer itself.

    The final component is intentionally left lexical: resolving it would
    dereference the active symlink that this controller must replace.  Its
    parent is canonicalized, however, so a journal written through a symlinked
    directory or a ``..`` spelling is recoverable through every equivalent
    spelling of the same pointer path.
    """

    raw = Path(os.path.abspath(os.fspath(path)))
    if not raw.name:
        raise ValueError("active generation pointer must name a symlink")
    return raw.parent.resolve(strict=False) / raw.name


def _active_generation_promotion_journal_path(active_pointer: Path) -> Path:
    pointer = _absolute_lexical_path(active_pointer)
    return pointer.parent / f".{pointer.name}.active-generation-promotion.json"


def _read_active_generation_pointer(active_pointer: Path) -> Path | None:
    """Return the current state generation, rejecting non-pointer targets."""

    pointer = _absolute_lexical_path(active_pointer)
    if pointer.is_symlink():
        target = (pointer.parent / os.readlink(pointer)).resolve()
        if not target.is_dir():
            raise ValueError(
                "active generation pointer is dangling or does not reference a directory"
            )
        return target
    if pointer.exists():
        raise ValueError(
            "active generation path must be a symlink, never a directory or regular file"
        )
    return None


def _validated_active_generation_operation_id(value: object) -> str:
    """Accept only a single safe journal operation identifier."""

    if not isinstance(value, str) or not _ACTIVE_GENERATION_OPERATION_ID_PATTERN.fullmatch(value):
        raise ValueError("active generation promotion journal has an invalid operation id")
    return value


def _active_generation_promotion_payload(
    *,
    active_pointer: Path,
    generation_root: Path,
    previous_generation_root: Path | None,
    attestation: RestoreGenerationAttestation,
    operation_id: str,
) -> dict[str, object]:
    pointer = _absolute_lexical_path(active_pointer)
    safe_operation_id = _validated_active_generation_operation_id(operation_id)
    temporary_pointer = pointer.parent / (
        f".{pointer.name}.active-generation-{safe_operation_id}.tmp"
    )
    return {
        "version": _ACTIVE_GENERATION_PROMOTION_JOURNAL_VERSION,
        "operation_id": safe_operation_id,
        "hostname": socket.gethostname(),
        "process_id": os.getpid(),
        "active_pointer": str(pointer),
        "temporary_pointer": str(temporary_pointer),
        "generation_root": str(generation_root),
        "previous_generation_root": (
            str(previous_generation_root) if previous_generation_root is not None else None
        ),
        "manifest_digest": attestation.manifest_digest,
        "generation_id": attestation.generation_id,
        "intent": "promote",
        "phase": "prepared",
        "created_at": _ts(),
    }


def _active_generation_journal_paths(
    payload: dict[str, object],
    *,
    active_pointer: Path,
) -> tuple[Path, Path, Path | None]:
    """Parse journal paths only when they remain local to the pointer root."""

    pointer = _absolute_lexical_path(active_pointer)
    operation_id = _validated_active_generation_operation_id(payload.get("operation_id"))
    raw_pointer = payload.get("active_pointer")
    raw_temporary = payload.get("temporary_pointer")
    raw_generation = payload.get("generation_root")
    raw_previous = payload.get("previous_generation_root")
    if (
        raw_pointer != str(pointer)
        or not isinstance(raw_temporary, str)
        or not isinstance(raw_generation, str)
        or (raw_previous is not None and not isinstance(raw_previous, str))
    ):
        raise ValueError("active generation promotion journal paths are invalid")
    temporary_pointer = Path(raw_temporary)
    generation_root = Path(raw_generation)
    previous_generation_root = Path(raw_previous) if raw_previous is not None else None
    expected_temporary = pointer.parent / (f".{pointer.name}.active-generation-{operation_id}.tmp")
    if (
        not temporary_pointer.is_absolute()
        or temporary_pointer != expected_temporary
        or not generation_root.is_absolute()
        or (previous_generation_root is not None and not previous_generation_root.is_absolute())
    ):
        raise ValueError("active generation promotion journal escapes its pointer root")
    return temporary_pointer, generation_root, previous_generation_root


def _remove_generation_pointer_candidate(
    temporary_pointer: Path,
    *,
    generation_root: Path,
) -> None:
    """Remove only the private symlink that this promotion created."""

    if not temporary_pointer.exists() and not temporary_pointer.is_symlink():
        return
    if not temporary_pointer.is_symlink():
        raise ValueError("active generation promotion temporary path is not a symlink")
    target = (temporary_pointer.parent / os.readlink(temporary_pointer)).resolve()
    if target != generation_root:
        raise ValueError("active generation promotion temporary pointer changed unexpectedly")
    temporary_pointer.unlink()
    _fsync_directory(temporary_pointer.parent)


def _read_active_generation_promotion_journal(
    journal_path: Path,
    *,
    active_pointer: Path,
) -> tuple[dict[str, object], Path, Path, Path | None]:
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "active generation promotion journal is unreadable; manual recovery is required"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            "active generation promotion journal is invalid; manual recovery is required"
        )
    if payload.get("version") != _ACTIVE_GENERATION_PROMOTION_JOURNAL_VERSION:
        raise ValueError(
            "active generation promotion journal version is unsupported; manual recovery is required"
        )
    if _journal_process_is_alive(payload):
        raise ValueError(
            "active generation promotion is already in progress; refusing concurrent recovery"
        )
    temporary_pointer, generation_root, previous_generation_root = _active_generation_journal_paths(
        payload,
        active_pointer=active_pointer,
    )
    if not generation_root.is_dir():
        raise ValueError(
            "active generation promotion target no longer exists; manual recovery is required"
        )
    if previous_generation_root is not None and not previous_generation_root.is_dir():
        raise ValueError(
            "active generation promotion previous target no longer exists; manual recovery is required"
        )
    attestation = _read_restore_generation_attestation(generation_root)
    if (
        payload.get("manifest_digest") != attestation.manifest_digest
        or payload.get("generation_id") != attestation.generation_id
    ):
        raise ValueError("active generation promotion attestation does not match its journal")
    return payload, temporary_pointer, generation_root, previous_generation_root


def _pointer_matches_generation(
    active_pointer: Path,
    generation_root: Path | None,
) -> bool:
    current = _read_active_generation_pointer(active_pointer)
    return current == generation_root


def _optional_journal_operation_id(payload: dict[str, object]) -> str | None:
    return _validated_active_generation_operation_id(payload.get("operation_id"))


def _restore_active_generation_pointer(
    active_pointer: Path,
    *,
    previous_generation_root: Path | None,
    operation_id: str,
) -> None:
    """Atomically restore the previous selection while a journal remains live."""

    pointer = _absolute_lexical_path(active_pointer)
    safe_operation_id = _validated_active_generation_operation_id(operation_id)
    if previous_generation_root is None:
        if pointer.is_symlink():
            pointer.unlink()
            _fsync_directory(pointer.parent)
        return
    if not previous_generation_root.is_dir():
        raise ValueError("active generation rollback target no longer exists")
    rollback_pointer = pointer.parent / (
        f".{pointer.name}.active-generation-rollback-{safe_operation_id}.tmp"
    )
    if rollback_pointer.exists() or rollback_pointer.is_symlink():
        raise ValueError("active generation rollback temporary pointer already exists")
    os.symlink(str(previous_generation_root), rollback_pointer)
    _fsync_directory(pointer.parent)
    try:
        os.replace(rollback_pointer, pointer)
        _fsync_directory(pointer.parent)
    finally:
        rollback_pointer.unlink(missing_ok=True)


def _rollback_active_generation_promotion(
    journal_path: Path,
    payload: dict[str, object],
    *,
    active_pointer: Path,
    temporary_pointer: Path,
    generation_root: Path,
    previous_generation_root: Path | None,
) -> None:
    """Return to the old pointer before reporting a synchronous failure."""

    payload["intent"] = "rollback"
    payload["phase"] = "rolling_back"
    _write_promotion_journal(journal_path, payload)
    if _pointer_matches_generation(active_pointer, generation_root):
        operation_id = _validated_active_generation_operation_id(payload.get("operation_id"))
        _restore_active_generation_pointer(
            active_pointer,
            previous_generation_root=previous_generation_root,
            operation_id=operation_id,
        )
    elif not _pointer_matches_generation(active_pointer, previous_generation_root):
        raise ValueError("active generation pointer changed unexpectedly during rollback")
    _remove_generation_pointer_candidate(temporary_pointer, generation_root=generation_root)
    payload["phase"] = "rolled_back"
    _write_promotion_journal(journal_path, payload)
    _remove_promotion_journal(journal_path)


def recover_active_generation_promotion(active_pointer: Path) -> ActiveGenerationPromotion | None:
    """Finish or roll back a stale atomic active-generation pointer switch.

    A promotion only changes one symlink, so the old generation directory is
    never renamed or deleted.  The journal distinguishes a completed pointer
    replacement from a pre-replacement temporary link, and preserves a
    deliberate rollback intent if a synchronous promotion error occurred.
    """

    pointer = _absolute_lexical_path(active_pointer)
    journal_path = _active_generation_promotion_journal_path(pointer)
    if not journal_path.exists():
        return None
    payload, temporary_pointer, generation_root, previous_generation_root = (
        _read_active_generation_promotion_journal(journal_path, active_pointer=pointer)
    )
    intent = payload.get("intent")
    if intent not in {"promote", "rollback"}:
        raise ValueError("active generation promotion journal has an invalid intent")

    if intent == "rollback":
        if _pointer_matches_generation(pointer, generation_root):
            operation_id = _validated_active_generation_operation_id(payload.get("operation_id"))
            _restore_active_generation_pointer(
                pointer,
                previous_generation_root=previous_generation_root,
                operation_id=operation_id,
            )
        elif not _pointer_matches_generation(pointer, previous_generation_root):
            raise ValueError(
                "active generation pointer changed unexpectedly; manual recovery is required"
            )
        _remove_generation_pointer_candidate(temporary_pointer, generation_root=generation_root)
        _remove_promotion_journal(journal_path)
        return ActiveGenerationPromotion(
            active_pointer=pointer,
            generation_root=previous_generation_root or generation_root,
            previous_generation_root=previous_generation_root,
            operation_id=_optional_journal_operation_id(payload),
            recovered=True,
        )

    if _pointer_matches_generation(pointer, generation_root):
        _remove_generation_pointer_candidate(temporary_pointer, generation_root=generation_root)
        _remove_promotion_journal(journal_path)
        return ActiveGenerationPromotion(
            active_pointer=pointer,
            generation_root=generation_root,
            previous_generation_root=previous_generation_root,
            operation_id=_optional_journal_operation_id(payload),
            recovered=True,
        )
    if not _pointer_matches_generation(pointer, previous_generation_root):
        raise ValueError(
            "active generation pointer changed unexpectedly; manual recovery is required"
        )
    _remove_generation_pointer_candidate(temporary_pointer, generation_root=generation_root)
    _remove_promotion_journal(journal_path)
    return ActiveGenerationPromotion(
        active_pointer=pointer,
        generation_root=previous_generation_root or generation_root,
        previous_generation_root=previous_generation_root,
        operation_id=_optional_journal_operation_id(payload),
        recovered=True,
    )


def _bounded_regular_file_paths(root: Path) -> tuple[int, list[str]]:
    """Inventory a high-risk restore tree without exporting private roots."""

    count = 0
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        count += 1
        if len(paths) < _HIGH_RISK_REPORT_PATH_LIMIT:
            paths.append(path.relative_to(root).as_posix())
    return count, paths


def _git_restore_report(root: Path) -> list[dict[str, object]]:
    """Capture bounded Git status facts without modifying restored files."""

    repositories: list[dict[str, object]] = []
    git_markers = sorted(path for path in root.rglob(".git") if path.is_dir() or path.is_file())
    for marker in git_markers[:_HIGH_RISK_REPORT_GIT_REPOSITORY_LIMIT]:
        repository = marker.parent
        relative_repository = repository.relative_to(root).as_posix()
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-C",
                    str(repository),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env={
                    **os.environ,
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_OPTIONAL_LOCKS": "0",
                    "GIT_TERMINAL_PROMPT": "0",
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            repositories.append(
                {
                    "relative_path": relative_repository,
                    "status": "unavailable",
                    "changed_path_count": None,
                    "changed_paths": [],
                }
            )
            continue
        if completed.returncode != 0:
            repositories.append(
                {
                    "relative_path": relative_repository,
                    "status": "unavailable",
                    "changed_path_count": None,
                    "changed_paths": [],
                }
            )
            continue
        changed = completed.stdout.splitlines()
        repositories.append(
            {
                "relative_path": relative_repository,
                "status": "clean" if not changed else "dirty",
                "changed_path_count": len(changed),
                "changed_paths": [line[3:] for line in changed[:_HIGH_RISK_REPORT_GIT_PATH_LIMIT]],
                "changed_paths_truncated": len(changed) > _HIGH_RISK_REPORT_GIT_PATH_LIMIT,
            }
        )
    return repositories


def _write_high_risk_restore_report(
    candidate_root: Path,
    *,
    workspace_root: Path | None,
    tenant_root: Path | None,
    control_plane_v2: bool,
) -> None:
    """Write an operator-review report for explicitly selected file restores.

    Workspace and tenant data remain opt-in and are never merged into an
    existing target.  Every restored regular file is conservatively listed as
    a potential orphan artifact for the operator to reconcile; Git inspection
    is read-only and only records a bounded porcelain snapshot.
    """

    selected: list[tuple[str, Path]] = []
    if workspace_root is not None:
        selected.append(("workspaces", workspace_root))
    if tenant_root is not None:
        selected.append(("tenants", tenant_root))
    if not selected and not control_plane_v2:
        return

    trees: list[dict[str, object]] = []
    for kind, root in selected:
        file_count, paths = _bounded_regular_file_paths(root)
        trees.append(
            {
                "kind": kind,
                "file_count": file_count,
                "restored_paths": paths,
                "restored_paths_truncated": file_count > len(paths),
                "orphan_artifacts": {
                    "status": "operator_review_required",
                    "count": file_count,
                    "paths": paths,
                    "paths_truncated": file_count > len(paths),
                },
                "git_repositories": _git_restore_report(root),
                "git_repositories_truncated": len(
                    [path for path in root.rglob(".git") if path.is_dir() or path.is_file()]
                )
                > _HIGH_RISK_REPORT_GIT_REPOSITORY_LIMIT,
            }
        )
    payload: dict[str, object] = {
        "version": _HIGH_RISK_RESTORE_REPORT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operator_action_required": True,
        "automatic_git_changes_applied": False,
        "trees": trees,
    }
    if control_plane_v2:
        # A control-plane-only restore deliberately leaves the live Workspace
        # and tenant trees untouched.  It can still make their files and Git
        # worktrees inconsistent with restored domain references, so retain a
        # durable, privacy-safe report even when no external tree was selected
        # for materialization.  We never discover host roots by convention.
        payload["control_plane_restore"] = {
            "domain_mode": "v2",
            "workspace_tenant_data_restored": bool(selected),
            "orphan_artifacts": {
                "status": "operator_review_required",
                "count": None,
                "paths": [],
                "paths_truncated": False,
            },
            "git_change_report": {
                "status": (
                    "captured_for_explicit_restored_trees"
                    if selected
                    else "not_collected_without_explicit_restore_tree"
                ),
                "repositories": [],
            },
        }
    report_path = candidate_root / _HIGH_RISK_RESTORE_REPORT_NAME
    temporary = candidate_root / f".{report_path.name}.{uuid4().hex}.tmp"
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, report_path)
        _fsync_directory(candidate_root)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_targets_overlap(left: Path, right: Path) -> bool:
    """Return whether two already-canonical restore destinations intersect."""

    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _validate_restore_target_roots(
    state_root: Path,
    workspace_root: Path | None,
    tenant_root: Path | None,
) -> None:
    """Reject nested restore targets before candidate creation can make one live.

    Each root is promoted independently through a sibling candidate.  A
    nested target would make ``copytree`` create another target's parent
    during staging, defeating the all-or-nothing promotion/rollback contract.
    """

    roots: list[tuple[str, Path]] = [("target_state_root", state_root)]
    if workspace_root is not None:
        roots.append(("target_workspace_root", workspace_root))
    if tenant_root is not None:
        roots.append(("target_tenant_root", tenant_root))
    for index, (left_name, left_root) in enumerate(roots):
        for right_name, right_root in roots[index + 1 :]:
            if _restore_targets_overlap(left_root, right_root):
                raise ValueError(f"{left_name} and {right_name} must not overlap")


def _file_meta(
    path: Path,
    *,
    source_path: str,
    schema_version: int | None = None,
    ownership_source: Path | None = None,
) -> FileMeta:
    """Return manifest metadata for a staged regular file.

    Backup bytes may come from a SQLite snapshot or a temporary staging tree,
    both of which are created by the backup process.  Their uid/gid would not
    describe the original state when the source belongs to a tenant.  Hash and
    size intentionally describe the staged bytes; POSIX ownership and mode
    describe the original source and are later written into the tar member.
    """

    stat = path.stat()
    ownership_stat = (ownership_source or path).stat()
    return FileMeta(
        size=stat.st_size,
        sha256=_sha256_of(path),
        source_path=source_path,
        schema_version=schema_version,
        mode=ownership_stat.st_mode & 0o7777,
        uid=ownership_stat.st_uid,
        gid=ownership_stat.st_gid,
    )


def _has_valid_posix_mode(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0o7777


def _has_valid_posix_id(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _tree_sha256(files: dict[str, FileMeta]) -> str:
    """Hash a manifest's stable member identity, independent of tar metadata."""
    digest = hashlib.sha256()
    for relative_path, meta in sorted(files.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(meta.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(meta.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_relative_path(path: str) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _runtime_sqlite_sources(runtime_root: Path) -> tuple[tuple[str, Path], ...]:
    """Return every runtime SQLite source under a safe relative member name."""

    if not runtime_root.is_dir():
        return ()
    sources = [
        (path.relative_to(runtime_root).as_posix(), path)
        for path in runtime_root.rglob("*.sqlite3")
        if path.is_file()
    ]
    return tuple(sorted(sources, key=lambda item: item[0]))


def _config_sources(state_root: Path, runtime_root: Path) -> tuple[tuple[str, Path], ...]:
    """Discover every current JSON control-plane source without collisions.

    Existing member names stay compatible.  Future runtime JSON is represented
    by its state-relative path (``runtime/...``), while future top-level JSON
    retains its filename.  A collision is rejected before archiving rather than
    silently dropping one of two distinct sources.
    """

    sources: dict[str, Path] = {}

    def add(member_name: str, source: Path) -> None:
        existing = sources.get(member_name)
        if existing is not None and existing != source:
            raise ValueError(f"Backup config member collision: {member_name}")
        sources[member_name] = source

    for name in _TOPLEVEL_CONFIGS:
        source = state_root / name
        if source.is_file():
            add(name, source)
    if state_root.is_dir():
        for source in state_root.glob("*.json"):
            if source.is_file():
                add(source.name, source)

    if runtime_root.is_dir():
        for source in runtime_root.rglob("*.json"):
            if not source.is_file():
                continue
            runtime_relative = source.relative_to(runtime_root).as_posix()
            member_name = (
                runtime_relative
                if runtime_relative in _RUNTIME_CONFIGS
                else f"runtime/{runtime_relative}"
            )
            add(member_name, source)

    return tuple(sorted(sources.items(), key=lambda item: item[0]))


def _state_directories(state_root: Path) -> tuple[Path, ...]:
    """Discover all state subdirectories except explicit high-risk roots."""

    if not state_root.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in state_root.iterdir()
                if path.is_dir() and path.name not in _RESERVED_STATE_ROOTS
            ),
            key=lambda path: path.name,
        )
    )


def _state_directory_names_from_manifest(manifest: BackupManifest) -> tuple[str, ...]:
    """Return v3 state roots represented by manifest members."""

    roots = {
        Path(relative_path).parts[0]
        for relative_path in manifest.files
        if Path(relative_path).parts and Path(relative_path).parts[0] not in _ARCHIVE_RESERVED_ROOTS
    }
    return tuple(sorted(roots))


def _config_restore_path(candidate_root: Path, config_name: str) -> Path:
    """Map a v2/v3 config manifest key to its staged state-root destination."""

    if config_name in _RUNTIME_CONFIGS:
        return candidate_root / "runtime" / config_name
    return candidate_root / config_name


def _database_schema_version(path: Path, database_name: str) -> int | None:
    """Read the registered schema version when the database has one.

    A missing migration table is valid for pre-migration databases and is
    represented as ``None`` in the manifest rather than failing a backup.
    """
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            row = conn.execute(
                "SELECT version FROM _schema_version WHERE database = ?", (database_name,)
            ).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def _database_name_from_filename(filename: str) -> str:
    return filename.removesuffix(".sqlite3")


def _validate_sqlite_database(path: Path) -> None:
    """Reject a staged restore whose SQLite integrity checks do not pass."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            detail = integrity[0] if integrity is not None else "no result"
            raise ValueError(f"{path.name}: SQLite integrity_check failed: {detail}")
        foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_rows:
            raise ValueError(f"{path.name}: SQLite foreign_key_check failed: {foreign_key_rows[0]}")


def _validate_database_schema_version(path: Path, meta: FileMeta) -> None:
    """Ensure the restored snapshot still has the schema version in its manifest."""
    if meta.schema_version is None:
        return
    actual = _database_schema_version(path, _database_name_from_filename(path.name))
    if actual != meta.schema_version:
        raise ValueError(
            f"{path.name}: schema version mismatch "
            f"(manifest={meta.schema_version}, restored={actual})"
        )


def _is_supported_member_path(relative_path: str) -> bool:
    """Return whether a v3 manifest member belongs to a restorable root.

    Version 3 treats the manifest as the complete inventory, so future runtime
    SQLite/JSON and state-directory members must be accepted without reducing
    the archive-path boundary to an unrestricted file restore.
    """

    if not _is_relative_path(relative_path):
        return False
    parts = Path(relative_path).parts
    if len(parts) < 2:
        return False
    root = parts[0]
    if root == "databases":
        return Path(*parts[1:]).suffix == ".sqlite3"
    if root == "config":
        suffix = Path(*parts[1:])
        if len(parts) == 2 and parts[1] in (*_TOPLEVEL_CONFIGS, *_RUNTIME_CONFIGS):
            return True
        if len(parts) == 2 and suffix.suffix == ".json":
            return True
        return parts[1] == "runtime" and suffix.suffix == ".json"
    if root in {"workspaces", "tenants"}:
        return True
    return root not in _ARCHIVE_RESERVED_ROOTS


def _staged_domain_reconciliation_target(candidate_root: Path) -> tuple[str | None, str | None]:
    """Read the restored domain fuse and latest run without mutating it.

    Legacy S0 archives legitimately predate the domain tables.  Those still
    receive the SQLite and member-level verifier, while a candidate containing
    migration state gets the full reconciliation pass below.
    """

    database_path = candidate_root / "runtime" / "agentic_researcher.sqlite3"
    if not database_path.is_file():
        return None, None
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "domain_migration_runs" not in tables:
            return None, None

        run_row = conn.execute(
            "SELECT run_id FROM domain_migration_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        latest_run_id = str(run_row[0]) if run_row is not None else None
        if "domain_cutover_state" not in tables:
            return "legacy", latest_run_id

        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(domain_cutover_state)")}
        if "state" not in columns:
            return "legacy", latest_run_id
        if "cutover_run_id" not in columns:
            raise ValueError("domain cutover state is missing cutover_run_id")
        row = conn.execute(
            "SELECT state, cutover_run_id FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise ValueError("domain cutover state is missing its singleton row")
        state = str(row[0])
        if state not in {"legacy", "prepared", "v2"}:
            raise ValueError(f"invalid restored domain cutover state: {state}")
        bound_run_id = row[1]
        if bound_run_id is not None and not isinstance(bound_run_id, str):
            raise ValueError("domain cutover state has an invalid cutover_run_id")
        if state in {"prepared", "v2"} and not bound_run_id:
            raise ValueError(f"{state} domain cutover is missing its migration run")
        return state, bound_run_id or latest_run_id


def validate_staged_domain_restore(candidate_root: Path, manifest: BackupManifest) -> None:
    """Run the domain reconciliation gate without mutating the candidate root.

    ``DomainReconciliationService.reconcile`` writes its report heartbeat and
    cutover eligibility.  Promotion must retain the exact verified archive
    generation, so reconciliation runs against a disposable copy of the
    candidate.  Legacy archives without a migration run remain supported; a
    prepared or committed v2 candidate must have a clean, cutover-ready report.
    """

    del manifest  # The service signature matches StagedRestoreValidator.
    state, run_id = _staged_domain_reconciliation_target(candidate_root)
    if run_id is None:
        return

    with tempfile.TemporaryDirectory(prefix="ainrf-restore-reconciliation-") as temporary:
        reconciliation_root = Path(temporary) / "state"
        shutil.copytree(candidate_root, reconciliation_root)
        from ainrf.domain_migration import DomainReconciliationService

        try:
            report = DomainReconciliationService(reconciliation_root).reconcile(run_id)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise ValueError("domain reconciliation rejected staged restore") from exc

    if state in {"prepared", "v2"} and (report.blocking_issues or not report.cutover_allowed):
        detail = ", ".join(report.blocking_issues) or "cutover is not ready"
        raise ValueError(f"domain reconciliation rejected staged restore: {detail}")


def _restored_member_path(
    relative_path: str,
    *,
    candidate_root: Path,
    candidate_workspace_root: Path | None,
    candidate_tenant_root: Path | None,
) -> Path | None:
    """Map a verified v3 archive member to its staged restore location."""

    parts = Path(relative_path).parts
    if not _is_supported_member_path(relative_path):
        raise ValueError(f"unsupported manifest member path: {relative_path}")
    root = parts[0]
    suffix = Path(*parts[1:])
    if root == "databases":
        return candidate_root / "runtime" / suffix
    if root == "config":
        return _config_restore_path(candidate_root, suffix.as_posix())
    if root == "workspaces":
        return candidate_workspace_root / suffix if candidate_workspace_root is not None else None
    if root == "tenants":
        return candidate_tenant_root / suffix if candidate_tenant_root is not None else None
    return candidate_root / root / suffix


def _apply_and_verify_restored_file_metadata(
    path: Path,
    *,
    member_name: str,
    meta: FileMeta,
) -> None:
    """Restore v3 ownership/mode and prove the promoted bytes still match."""

    if not path.is_file():
        raise ValueError(f"{member_name}: restored file is missing")
    if path.stat().st_size != meta.size:
        raise ValueError(f"{member_name}: restored size mismatch")
    if _sha256_of(path) != meta.sha256:
        raise ValueError(f"{member_name}: restored checksum mismatch")
    if not _has_valid_posix_mode(meta.mode):
        raise ValueError(f"{member_name}: manifest mode is missing or invalid")
    if not _has_valid_posix_id(meta.uid) or not _has_valid_posix_id(meta.gid):
        raise ValueError(f"{member_name}: manifest ownership is missing or invalid")

    assert meta.mode is not None
    assert meta.uid is not None
    assert meta.gid is not None
    current = path.stat()
    if current.st_uid != meta.uid or current.st_gid != meta.gid:
        try:
            os.chown(path, meta.uid, meta.gid)
        except OSError as exc:
            raise ValueError(f"{member_name}: cannot restore ownership") from exc
    try:
        # chown may clear set-id bits, so ownership always precedes chmod.
        os.chmod(path, meta.mode)
    except OSError as exc:
        raise ValueError(f"{member_name}: cannot restore mode") from exc

    restored = path.stat()
    if (restored.st_mode & 0o7777) != meta.mode:
        raise ValueError(f"{member_name}: restored mode mismatch")
    if restored.st_uid != meta.uid:
        raise ValueError(f"{member_name}: restored uid mismatch")
    if restored.st_gid != meta.gid:
        raise ValueError(f"{member_name}: restored gid mismatch")


def _apply_and_verify_restored_member_metadata(
    manifest: BackupManifest,
    *,
    candidate_root: Path,
    candidate_workspace_root: Path | None,
    candidate_tenant_root: Path | None,
) -> None:
    """Apply manifest v3 POSIX metadata to every selected restored member."""

    if manifest.version < 3:
        return
    for member_name, meta in manifest.files.items():
        restored_path = _restored_member_path(
            member_name,
            candidate_root=candidate_root,
            candidate_workspace_root=candidate_workspace_root,
            candidate_tenant_root=candidate_tenant_root,
        )
        # Workspace/tenant trees are deliberately high-risk opt-ins.  They are
        # still verified inside the archive, but are not materialized or
        # metadata-mutated unless the caller selected an explicit target root.
        if restored_path is None:
            continue
        _apply_and_verify_restored_file_metadata(
            restored_path,
            member_name=member_name,
            meta=meta,
        )


# ── service ───────────────────────────────────────────────────────


class BackupService:
    """Create, verify, and restore OpenScience data backups."""

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"

    # ── create ────────────────────────────────────────────────────

    def create_backup(
        self,
        output_path: Path | None = None,
        *,
        include_workspaces: bool = False,
        include_tenants: bool = False,
        workspace_root: Path | None = None,
        tenant_root: Path | None = None,
    ) -> Path:
        """Create a ``.tar.gz`` backup archive and return its path."""
        ts = _ts()
        default_name = f"ainrf-backup-{ts}.tar.gz"
        if output_path is None:
            archive = Path.cwd() / default_name
        elif output_path.suffix in (".gz", ".tgz"):
            archive = output_path
        else:
            archive = output_path / default_name

        manifest = BackupManifest(created_at=datetime.now(timezone.utc).isoformat())

        with tempfile.TemporaryDirectory(prefix="ainrf-backup-") as tmp:
            stage = Path(tmp) / "stage"
            stage.mkdir()
            source_members: dict[str, Path] = {}

            # 1. Every runtime SQLite database.  Existing top-level names
            # retain their archive paths; nested/future databases preserve
            # their path below ``databases/`` and restore below ``runtime/``.
            db_dir = stage / "databases"
            db_dir.mkdir()
            for name, src in _runtime_sqlite_sources(self._runtime_root):
                dst = db_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                _dump_sqlite_safe(src, dst)
                schema_version = _database_schema_version(
                    dst, _database_name_from_filename(Path(name).name)
                )
                # The read-only schema probe can itself create transient WAL
                # bookkeeping files on some SQLite builds.
                for suffix in ("-wal", "-shm", "-journal"):
                    dst.with_name(f"{dst.name}{suffix}").unlink(missing_ok=True)
                manifest.databases[name] = _file_meta(
                    dst,
                    source_path=f"runtime/{name}",
                    schema_version=schema_version,
                    ownership_source=src,
                )
                source_members[f"databases/{name}"] = src
                _LOG.info("backed up database %s (%d bytes)", name, dst.stat().st_size)

            # 2. Every current JSON control-plane source, plus the legacy
            # non-JSON top-level config files.  Runtime JSON not present in
            # the original fixed list is staged under ``config/runtime/...``.
            cfg_dir = stage / "config"
            cfg_dir.mkdir()
            for name, src in _config_sources(self._state_root, self._runtime_root):
                dst = cfg_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                manifest.config_files[name] = _file_meta(
                    dst,
                    source_path=src.relative_to(self._state_root).as_posix(),
                    ownership_source=src,
                )
                source_members[f"config/{name}"] = src
                _LOG.info("backed up config %s", name)

            # 3. Every state subdirectory.  Runtime is covered above and
            # workspace/tenant files remain explicit high-risk opt-ins.
            for src in _state_directories(self._state_root):
                destination = stage / src.name
                shutil.copytree(src, destination)
                for item in destination.rglob("*"):
                    if item.is_file():
                        relative_path = item.relative_to(stage).as_posix()
                        source_members[relative_path] = src / item.relative_to(destination)
                _LOG.info("backed up state dir %s", src.name)

            # 4. Optional: workspaces
            if include_workspaces and workspace_root and workspace_root.is_dir():
                destination = stage / "workspaces"
                shutil.copytree(workspace_root, destination)
                for item in destination.rglob("*"):
                    if item.is_file():
                        relative_path = item.relative_to(stage).as_posix()
                        source_members[relative_path] = workspace_root / item.relative_to(
                            destination
                        )
                _LOG.info("backed up workspaces")

            # 5. Optional: tenant homes
            if include_tenants and tenant_root and tenant_root.is_dir():
                destination = stage / "tenants"
                shutil.copytree(tenant_root, destination)
                for item in destination.rglob("*"):
                    if item.is_file():
                        relative_path = item.relative_to(stage).as_posix()
                        source_members[relative_path] = tenant_root / item.relative_to(destination)
                _LOG.info("backed up tenants")

            # Version 3 inventories every regular archive member, not merely
            # the databases and top-level config files.  That makes state-dir,
            # workspace, and tenant tampering detectable before restore.
            for item in sorted(path for path in stage.rglob("*") if path.is_file()):
                relative_path = item.relative_to(stage).as_posix()
                if relative_path.startswith("databases/"):
                    database_name = relative_path.removeprefix("databases/")
                    meta = manifest.databases.get(database_name)
                    if meta is None:
                        raise RuntimeError(f"Unexpected staged database member: {relative_path}")
                elif relative_path.startswith("config/"):
                    config_name = relative_path.removeprefix("config/")
                    meta = manifest.config_files.get(config_name)
                    if meta is None:
                        raise RuntimeError(f"Unexpected staged config member: {relative_path}")
                else:
                    source_member = source_members.get(relative_path)
                    if source_member is None:
                        raise RuntimeError(f"Unexpected staged state member: {relative_path}")
                    meta = _file_meta(
                        item,
                        source_path=relative_path,
                        ownership_source=source_member,
                    )
                manifest.files[relative_path] = meta

            manifest.includes_workspaces = (stage / "workspaces").is_dir()
            manifest.includes_tenants = (stage / "tenants").is_dir()
            manifest.tree_sha256 = _tree_sha256(manifest.files)

            # 6. Manifest
            (stage / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")

            # 7. Pack archive
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(str(archive), "w:gz") as tar:

                def archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo:
                    if not member.isfile() or member.name == "manifest.json":
                        return member
                    meta = manifest.files.get(member.name)
                    if meta is None:
                        raise RuntimeError(
                            f"Archive member is missing manifest metadata: {member.name}"
                        )
                    if not (
                        _has_valid_posix_mode(meta.mode)
                        and _has_valid_posix_id(meta.uid)
                        and _has_valid_posix_id(meta.gid)
                    ):
                        raise RuntimeError(
                            f"Archive member has incomplete POSIX metadata: {member.name}"
                        )
                    assert meta.mode is not None
                    assert meta.uid is not None
                    assert meta.gid is not None
                    member.mode = meta.mode
                    member.uid = meta.uid
                    member.gid = meta.gid
                    member.uname = ""
                    member.gname = ""
                    return member

                for item in sorted(stage.iterdir()):
                    tar.add(str(item), arcname=item.name, filter=archive_filter)

        _LOG.info("backup created: %s", archive)
        return archive

    # ── verify ────────────────────────────────────────────────────

    def verify_backup(self, archive_path: Path) -> BackupManifest:
        """Verify archive integrity (manifest, sizes, and SHA-256 checksums).

        Returns the parsed manifest on success.
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_path}")

        manifest = self._read_manifest(archive_path)
        if manifest.version > _BACKUP_VERSION:
            raise ValueError(
                f"Backup version {manifest.version} > supported {_BACKUP_VERSION}. "
                "Upgrade OpenScience first."
            )

        errors: list[str] = []
        with tarfile.open(str(archive_path), "r:gz") as tar:
            members = tar.getmembers()
            members_by_name: dict[str, list[tarfile.TarInfo]] = {}
            for member in members:
                if not _is_relative_path(member.name):
                    errors.append(f"{member.name}: unsafe archive path")
                    continue
                members_by_name.setdefault(member.name, []).append(member)

            if manifest.version >= 3:
                members_to_verify = list(manifest.files.items())
                actual_files = {
                    member.name
                    for member in members
                    if member.isfile() and member.name != "manifest.json"
                }
                expected_files = set(manifest.files)
                for member_name in sorted(expected_files):
                    if not _is_supported_member_path(member_name):
                        errors.append(f"{member_name}: unsupported manifest member path")
                for member_name in sorted(actual_files - expected_files):
                    errors.append(f"{member_name}: not listed in manifest")
                database_members = {
                    member_name.removeprefix("databases/"): meta
                    for member_name, meta in manifest.files.items()
                    if member_name.startswith("databases/")
                }
                if set(database_members) != set(manifest.databases):
                    errors.append("manifest: database inventory does not match file inventory")
                config_members = {
                    member_name.removeprefix("config/"): meta
                    for member_name, meta in manifest.files.items()
                    if member_name.startswith("config/")
                }
                if set(config_members) != set(manifest.config_files):
                    errors.append("manifest: config inventory does not match file inventory")
                for root_name, enabled in (
                    ("workspaces", manifest.includes_workspaces),
                    ("tenants", manifest.includes_tenants),
                ):
                    present = any(
                        member.name == root_name or member.name.startswith(f"{root_name}/")
                        for member in members
                    )
                    if present != enabled:
                        errors.append(f"{root_name}: include flag does not match archive contents")
                if manifest.tree_sha256 is None:
                    errors.append("manifest: missing tree_sha256")
                elif _tree_sha256(manifest.files) != manifest.tree_sha256:
                    errors.append("manifest: tree checksum mismatch")
            else:
                members_to_verify = [
                    *((f"databases/{name}", meta) for name, meta in manifest.databases.items()),
                    *((f"config/{name}", meta) for name, meta in manifest.config_files.items()),
                ]

            for member_name, meta in members_to_verify:
                named_members = members_by_name.get(member_name, [])
                if len(named_members) != 1:
                    state = "missing" if not named_members else "duplicated"
                    errors.append(f"{member_name}: {state}")
                    continue
                member = named_members[0]
                if not member.isfile():
                    errors.append(f"{member_name}: not a regular file")
                    continue
                if member.size != meta.size:
                    errors.append(f"{member_name}: size mismatch")
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    errors.append(f"{member_name}: unreadable")
                    continue
                with stream:
                    if _sha256_stream(stream) != meta.sha256:
                        errors.append(f"{member_name}: checksum mismatch")
                        continue
                if manifest.version >= 3:
                    if not _has_valid_posix_mode(meta.mode):
                        errors.append(f"{member_name}: manifest mode is missing or invalid")
                    elif (member.mode & 0o7777) != meta.mode:
                        errors.append(f"{member_name}: mode mismatch")
                    if not _has_valid_posix_id(meta.uid):
                        errors.append(f"{member_name}: manifest uid is missing or invalid")
                    elif member.uid != meta.uid:
                        errors.append(f"{member_name}: uid mismatch")
                    if not _has_valid_posix_id(meta.gid):
                        errors.append(f"{member_name}: manifest gid is missing or invalid")
                    elif member.gid != meta.gid:
                        errors.append(f"{member_name}: gid mismatch")

        if errors:
            raise ValueError("Backup verification failed:\n  " + "\n  ".join(errors))

        _LOG.info("backup verified: %s", archive_path)
        return manifest

    # ── restore ───────────────────────────────────────────────────

    def restore_backup(
        self,
        archive_path: Path,
        *,
        target_state_root: Path | None = None,
        target_workspace_root: Path | None = None,
        target_tenant_root: Path | None = None,
        skip_pre_backup: bool = False,
        validators: Sequence[StagedRestoreValidator] = (),
    ) -> Path:
        """Restore a backup into a *new* state root and return that path.

        The active state root is never overwritten.  The caller must provide a
        previously non-existent ``target_state_root``; all archive checks,
        SQLite integrity checks, mandatory domain reconciliation, member
        ownership/mode verification, and optional *validators* finish in a
        sibling candidate directory before it is atomically renamed into
        place.  A pre-restore snapshot of this service's state root is still
        created unless *skip_pre_backup* is true.
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_path}")

        if target_state_root is None:
            raise ValueError(
                "target_state_root is required; restore only supports a new staged root"
            )
        state_root = target_state_root.resolve()
        workspace_target = target_workspace_root.resolve() if target_workspace_root else None
        tenant_target = target_tenant_root.resolve() if target_tenant_root else None
        _validate_restore_target_roots(state_root, workspace_target, tenant_target)

        manifest = self.verify_backup(archive_path)

        if manifest.version > _BACKUP_VERSION:
            raise ValueError(
                f"Backup version {manifest.version} > supported {_BACKUP_VERSION}. "
                "Upgrade OpenScience first."
            )

        journal_path = state_root.parent / f".{state_root.name}.restore-promotion.json"
        recovery = _recover_pending_restore_promotion(
            journal_path,
            expected_manifest_digest=_manifest_digest(manifest),
        )
        if recovery == "completed":
            _LOG.info("completed interrupted restore promotion → %s", state_root)
            return state_root
        if state_root.exists():
            raise ValueError(f"target_state_root must not exist: {state_root}")

        _LOG.info(
            "restoring backup from %s (%s, %d db, %d cfg)",
            archive_path,
            manifest.created_at,
            len(manifest.databases),
            len(manifest.config_files),
        )

        # Pre-restore safety net for the active source root.  The target root
        # does not exist yet and is therefore never overwritten.
        source_runtime_root = self._runtime_root
        if (
            not skip_pre_backup
            and source_runtime_root.exists()
            and any(source_runtime_root.iterdir())
        ):
            pre = archive_path.parent / f"pre-restore-{_ts()}.tar.gz"
            _LOG.info("creating pre-restore safety backup → %s", pre)
            self.create_backup(pre)
            _LOG.info(
                "safety backup saved; if restore fails, recover with: ainrf backup restore %s", pre
            )

        candidate_root = state_root.parent / f".{state_root.name}.restore-{uuid4().hex}"
        candidate_workspace_root: Path | None = None
        candidate_tenant_root: Path | None = None
        if workspace_target is not None:
            if workspace_target.exists():
                raise ValueError(f"target_workspace_root must not exist: {workspace_target}")
            candidate_workspace_root = workspace_target.parent / (
                f".{workspace_target.name}.restore-{uuid4().hex}"
            )
        if tenant_target is not None:
            if tenant_target.exists():
                raise ValueError(f"target_tenant_root must not exist: {tenant_target}")
            candidate_tenant_root = tenant_target.parent / (
                f".{tenant_target.name}.restore-{uuid4().hex}"
            )

        promoted_pairs: list[tuple[Path, Path]] = []
        promotion_journal_created = False
        candidate_paths = [candidate_root]
        if candidate_workspace_root is not None:
            candidate_paths.append(candidate_workspace_root)
        if candidate_tenant_root is not None:
            candidate_paths.append(candidate_tenant_root)
        try:
            with tempfile.TemporaryDirectory(prefix="ainrf-restore-") as tmp:
                stage = Path(tmp) / "archive"
                with tarfile.open(str(archive_path), "r:gz") as tar:
                    tar.extractall(str(stage), filter="data")

                candidate_root.mkdir(parents=True)
                runtime_root = candidate_root / "runtime"

                # 1. Databases
                for db_name, meta in manifest.databases.items():
                    src = stage / "databases" / db_name
                    if not src.exists():
                        raise ValueError(
                            f"database {db_name} listed in manifest but absent from archive"
                        )
                    actual = _sha256_of(src)
                    if actual != meta.sha256:
                        raise ValueError(f"{db_name}: checksum mismatch (archive corrupted)")
                    dest = runtime_root / db_name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    _LOG.info("restored database %s", db_name)

                # 2. Config files
                for cfg_name, meta in manifest.config_files.items():
                    src = stage / "config" / cfg_name
                    if not src.exists():
                        raise ValueError(
                            f"config {cfg_name} listed in manifest but absent from archive"
                        )
                    actual = _sha256_of(src)
                    if actual != meta.sha256:
                        raise ValueError(f"{cfg_name}: checksum mismatch (archive corrupted)")
                    dest = _config_restore_path(candidate_root, cfg_name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    _LOG.info("restored config %s", cfg_name)

                # 3. State subdirectories.  v3 archives have an explicit
                # member inventory, while v2 archives retain the historical
                # fixed fallback because their manifest did not name every
                # nested state member.
                state_directories = (
                    _state_directory_names_from_manifest(manifest)
                    if manifest.version >= 3
                    else _STATE_DIRS
                )
                for dirname in state_directories:
                    src = stage / dirname
                    if src.is_dir():
                        shutil.copytree(src, candidate_root / dirname)
                        _LOG.info("restored state dir %s", dirname)

                # 4. Optional high-risk workspace/tenant data only activates
                # when the caller supplied an explicit target root.
                promotion_pairs = [(candidate_root, state_root)]
                if workspace_target and manifest.includes_workspaces:
                    ws_src = stage / "workspaces"
                    if ws_src.is_dir():
                        assert candidate_workspace_root is not None
                        shutil.copytree(ws_src, candidate_workspace_root)
                        promotion_pairs.append((candidate_workspace_root, workspace_target))
                        _LOG.info("staged workspaces → %s", candidate_workspace_root)
                if tenant_target and manifest.includes_tenants:
                    t_src = stage / "tenants"
                    if t_src.is_dir():
                        assert candidate_tenant_root is not None
                        shutil.copytree(t_src, candidate_tenant_root)
                        promotion_pairs.append((candidate_tenant_root, tenant_target))
                        _LOG.info("staged tenants → %s", candidate_tenant_root)

                for db_name, meta in manifest.databases.items():
                    database_path = runtime_root / db_name
                    _validate_sqlite_database(database_path)
                    _validate_database_schema_version(database_path, meta)
                # This gate is unconditional.  API/CLI callers may add
                # validators, but cannot opt out of the domain reconciliation
                # and member-level restore verifier by passing an empty list.
                validate_staged_domain_restore(candidate_root, manifest)
                _apply_and_verify_restored_member_metadata(
                    manifest,
                    candidate_root=candidate_root,
                    candidate_workspace_root=candidate_workspace_root,
                    candidate_tenant_root=candidate_tenant_root,
                )
                for validator in validators:
                    validator(candidate_root, manifest)
                candidate_domain_state, _candidate_run_id = _staged_domain_reconciliation_target(
                    candidate_root
                )
                _write_high_risk_restore_report(
                    candidate_root,
                    workspace_root=(
                        candidate_workspace_root
                        if candidate_workspace_root is not None
                        and candidate_workspace_root.is_dir()
                        else None
                    ),
                    tenant_root=(
                        candidate_tenant_root
                        if candidate_tenant_root is not None and candidate_tenant_root.is_dir()
                        else None
                    ),
                    control_plane_v2=candidate_domain_state == "v2",
                )
                _write_restore_generation_attestation(candidate_root, manifest)

                journal: dict[str, object] = {
                    "version": _RESTORE_PROMOTION_JOURNAL_VERSION,
                    "operation_id": uuid4().hex,
                    "archive": str(archive_path.resolve()),
                    "manifest_digest": _manifest_digest(manifest),
                    "hostname": socket.gethostname(),
                    "process_id": os.getpid(),
                    "phase": "prepared",
                    "created_at": _ts(),
                    "pairs": [
                        {"candidate": str(candidate), "target": str(target), "status": "staged"}
                        for candidate, target in promotion_pairs
                    ],
                }
                _write_promotion_journal(
                    journal_path,
                    journal,
                    exclusive=True,
                )
                promotion_journal_created = True
                raw_pairs = journal["pairs"]
                assert isinstance(raw_pairs, list)
                for index, (candidate, target) in enumerate(promotion_pairs):
                    entry = raw_pairs[index]
                    assert isinstance(entry, dict)
                    entry["status"] = "promoting"
                    journal["phase"] = "promoting"
                    _write_promotion_journal(journal_path, journal)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(candidate, target)
                    # Record the rename before syncing the directory.  If the
                    # sync itself fails, the exception handler must still know
                    # this target needs to be moved back to its private
                    # candidate path.
                    promoted_pairs.append((candidate, target))
                    _fsync_directory(target.parent)
                    entry["status"] = "promoted"
                    _write_promotion_journal(journal_path, journal)
                journal["phase"] = "completed"
                _write_promotion_journal(journal_path, journal)
                _remove_promotion_journal(journal_path)
        except BaseException:
            # A multi-root promotion either completes as a unit or restores
            # every target back to its private candidate path.  The active
            # source root was never used as a target here.
            rollback_error: BaseException | None = None
            for candidate, target in reversed(promoted_pairs):
                if target.exists() and not candidate.exists():
                    try:
                        os.replace(target, candidate)
                        # Keep the journal until every rollback rename is
                        # durable.  A failed fsync leaves enough pair state
                        # for the next restore invocation to fail closed or
                        # recover safely instead of forgetting a target.
                        _fsync_directory(target.parent)
                    except BaseException as exc:
                        rollback_error = exc
                        break
            if rollback_error is None:
                for candidate in candidate_paths:
                    if candidate.exists():
                        shutil.rmtree(candidate, ignore_errors=True)
                if promotion_journal_created:
                    _remove_promotion_journal(journal_path)
            else:
                _LOG.error(
                    "restore promotion rollback was not durable; retaining journal for recovery",
                    exc_info=rollback_error,
                )
                raise RuntimeError(
                    "restore promotion rollback was not durable; journal retained for recovery"
                ) from rollback_error
            raise

        _LOG.info("restore staged and published to %s", state_root)
        return state_root

    def promote_restored_generation(
        self,
        generation_root: Path,
        *,
        active_state_pointer: Path,
        maintenance_state_root: Path | None = None,
        maintenance_stability_window_seconds: float = 5.0,
    ) -> ActiveGenerationPromotion:
        """Atomically select a verified staged state root through a symlink.

        This deliberately does not promote workspace or tenant trees.  Those
        remain explicit restore outputs for an operator to inspect through the
        high-risk report. The current active generation must pass the durable
        maintenance preflight, and this operation owns its maintenance lease
        from before journal creation through the pointer swap.
        """

        if maintenance_stability_window_seconds < 0:
            raise ValueError("maintenance_stability_window_seconds must be non-negative")
        generation = generation_root.resolve()
        if not generation.is_dir():
            raise ValueError("generation_root must be an existing verified state directory")
        attestation = _read_restore_generation_attestation(generation)
        pointer = _absolute_lexical_path(active_state_pointer)
        if not pointer.parent.is_dir():
            raise ValueError("active generation pointer parent must already exist")

        active_before_recovery = _read_active_generation_pointer(pointer)
        maintenance_root = (
            maintenance_state_root.resolve()
            if maintenance_state_root is not None
            else active_before_recovery
        )
        if maintenance_root is None:
            raise ValueError(
                "generation promotion requires an active state pointer or maintenance_state_root"
            )
        if active_before_recovery is not None and maintenance_root != active_before_recovery:
            raise ValueError("maintenance_state_root must be the current active state generation")

        # DomainCutoverController imports BackupService at module load. Keep
        # this dependency local so importing the backup package remains
        # acyclic while promotion still uses the real persisted barrier.
        from ainrf.domain_control.service import DomainMaintenanceService

        # A process that resolves the pointer immediately after the swap must
        # still encounter a durable write fence in the selected generation.
        # Operators can explicitly enter maintenance on the staged root before
        # promotion; silently initializing it here would mutate the verified
        # generation and could reopen a restored legacy state.
        staged_maintenance = DomainMaintenanceService(generation)
        try:
            staged_maintenance.adopt_existing_maintenance_schema()
        except RuntimeError as exc:
            raise ValueError(
                "generation promotion requires the staged generation to retain "
                "a readable maintenance control plane"
            ) from exc
        if not staged_maintenance.status().is_active:
            raise ValueError(
                "generation promotion requires the staged generation to remain in maintenance"
            )

        maintenance = DomainMaintenanceService(maintenance_root)
        try:
            maintenance.adopt_existing_maintenance_schema()
        except RuntimeError as exc:
            raise ValueError(
                "generation promotion requires a readable persisted maintenance control plane"
            ) from exc
        maintenance_before = maintenance.status()
        preflight = maintenance.preflight(
            stability_window_seconds=maintenance_stability_window_seconds
        )
        maintenance_after_preflight = maintenance.status()
        if (
            not preflight.ready
            or not maintenance_after_preflight.is_active
            or maintenance_after_preflight.maintenance_epoch != maintenance_before.maintenance_epoch
        ):
            raise ValueError("active maintenance preflight is not ready for generation promotion")

        lease = maintenance.begin_maintenance_operation(
            source="backup.promote-generation",
            expected_epoch=maintenance_before.maintenance_epoch,
        )
        try:
            maintenance.check_maintenance_operation(lease)
            recovered = recover_active_generation_promotion(pointer)
            previous_generation = _read_active_generation_pointer(pointer)
            if active_before_recovery is not None and previous_generation != maintenance_root:
                raise ValueError(
                    "stale promotion changed the active state pointer; rerun against its maintenance epoch"
                )
            if previous_generation == generation:
                return ActiveGenerationPromotion(
                    active_pointer=pointer,
                    generation_root=generation,
                    previous_generation_root=previous_generation,
                    operation_id=None,
                    recovered=recovered is not None,
                )

            operation_id = uuid4().hex
            journal_path = _active_generation_promotion_journal_path(pointer)
            journal = _active_generation_promotion_payload(
                active_pointer=pointer,
                generation_root=generation,
                previous_generation_root=previous_generation,
                attestation=attestation,
                operation_id=operation_id,
            )
            temporary_pointer, _, _ = _active_generation_journal_paths(
                journal, active_pointer=pointer
            )
            journal_created = False
            try:
                maintenance.check_maintenance_operation(lease)
                _write_promotion_journal(journal_path, journal, exclusive=True)
                journal_created = True
                os.symlink(str(generation), temporary_pointer)
                _fsync_directory(pointer.parent)
                journal["phase"] = "candidate_ready"
                _write_promotion_journal(journal_path, journal)
                journal["phase"] = "promoting"
                _write_promotion_journal(journal_path, journal)
                maintenance.check_maintenance_operation(lease)
                os.replace(temporary_pointer, pointer)
                _fsync_directory(pointer.parent)
                maintenance.check_maintenance_operation(lease)
                journal["phase"] = "promoted"
                _write_promotion_journal(journal_path, journal)
                _remove_promotion_journal(journal_path)
            except BaseException:
                if journal_created:
                    try:
                        _rollback_active_generation_promotion(
                            journal_path,
                            journal,
                            active_pointer=pointer,
                            temporary_pointer=temporary_pointer,
                            generation_root=generation,
                            previous_generation_root=previous_generation,
                        )
                    except BaseException as rollback_error:
                        _LOG.error(
                            "active generation promotion rollback was not durable; retaining journal",
                            exc_info=rollback_error,
                        )
                        raise RuntimeError(
                            "active generation promotion rollback was not durable; journal retained"
                        ) from rollback_error
                raise
            maintenance.check_maintenance_operation(lease)
        finally:
            maintenance.finish_mutation(lease)

        _LOG.info("active state generation switched to %s", generation)
        return ActiveGenerationPromotion(
            active_pointer=pointer,
            generation_root=generation,
            previous_generation_root=previous_generation,
            operation_id=operation_id,
            recovered=recovered is not None,
        )

    # ── internal ──────────────────────────────────────────────────

    @staticmethod
    def _read_manifest(archive_path: Path) -> BackupManifest:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            matches = [member for member in tar.getmembers() if member.name == "manifest.json"]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError("Invalid backup: missing manifest.json")
            stream = tar.extractfile(matches[0])
            if stream is None:
                raise ValueError("Invalid backup: unreadable manifest.json")
            with stream:
                return BackupManifest.from_json(stream.read().decode("utf-8"))

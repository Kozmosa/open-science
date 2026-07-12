"""Stable, read-only snapshots for legacy domain migration sources.

The domain importer must never read a live SQLite database directly: a WAL can
contain committed rows which are absent from the ``.sqlite3`` main file.  It
also cannot trust a JSON registry after it has started processing it.  This
module creates a fixed, temporary source set which is held for an entire
import, while retaining a source manifest suitable for reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self


class SourceStaleError(RuntimeError):
    """Raised when a JSON source changes while an import snapshot is in use."""


@dataclass(frozen=True, slots=True)
class SourceFile:
    relative_path: str
    sha256: str
    size: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Observed source files plus a location-independent content digest.

    ``state_root`` is deliberately only a display label retained for callers
    of the original API. The canonical representation and digest exclude it,
    so two identical source trees at different absolute paths have the same
    migration identity.
    """

    state_root: str
    files: tuple[SourceFile, ...]

    def canonical_dict(self) -> dict[str, object]:
        """Return the location-independent source identity."""
        return {
            "version": 1,
            "files": [
                {
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "size": item.size,
                }
                for item in sorted(self.files, key=lambda item: item.relative_path)
            ],
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, object]:
        """Return the backward-compatible display manifest with its digest."""
        result = asdict(self)
        result["digest"] = self.digest
        return result


@dataclass(frozen=True, slots=True)
class _JsonSnapshot:
    source_path: Path
    snapshot_path: Path
    fingerprint: SourceFile


def _relative_path(path: Path, state_root: Path) -> str:
    return path.relative_to(state_root).as_posix()


def _source_stat(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


def _observe_json(path: Path, relative_path: str) -> tuple[bytes, SourceFile]:
    """Capture one internally stable JSON observation."""
    try:
        before_inode, before_mtime_ns, before_size = _source_stat(path)
        payload = path.read_bytes()
        after_inode, after_mtime_ns, after_size = _source_stat(path)
    except FileNotFoundError as exc:
        raise SourceStaleError(f"JSON source disappeared: {relative_path}") from exc

    digest = hashlib.sha256(payload).hexdigest()
    if (before_inode, before_mtime_ns, before_size) != (
        after_inode,
        after_mtime_ns,
        after_size,
    ) or len(payload) != before_size:
        raise SourceStaleError(f"JSON source changed while being read: {relative_path}")
    return payload, SourceFile(
        relative_path=relative_path,
        sha256=digest,
        size=before_size,
        inode=before_inode,
        mtime_ns=before_mtime_ns,
    )


def _stable_json_fingerprint(path: Path, relative_path: str) -> tuple[bytes, SourceFile]:
    """Read a JSON source only when its pre/post observations match exactly."""
    payload, before = _observe_json(path, relative_path)
    _, after = _observe_json(path, relative_path)
    if before != after:
        raise SourceStaleError(f"JSON source changed while being read: {relative_path}")
    return payload, before


def _snapshot_sqlite(source: Path, target: Path) -> None:
    """Create a consistent SQLite backup without opening the source for writes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _sqlite_snapshot_fingerprint(source: Path, snapshot: Path, relative_path: str) -> SourceFile:
    """Fingerprint a fixed SQLite backup, retaining observed source metadata."""
    digest = hashlib.sha256()
    with snapshot.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    inode, mtime_ns, _ = _source_stat(source)
    return SourceFile(
        relative_path=relative_path,
        sha256=digest.hexdigest(),
        size=snapshot.stat().st_size,
        inode=inode,
        mtime_ns=mtime_ns,
    )


def _legacy_agentic_fingerprint(source: Path, snapshot: Path, relative_path: str) -> SourceFile:
    """Fingerprint legacy Task data without making v2 shadow writes stale.

    ``agentic_researcher.sqlite3`` is both the historical Task source and the
    additive v2 target. The importer can safely write new v2 tables while
    preserving a manifest identity for the historical Task columns alone.
    """
    columns = (
        "task_id",
        "project_id",
        "workspace_id",
        "environment_id",
        "researcher_type",
        "harness_engine",
        "user_skills",
        "user_mcp_servers",
        "status",
        "title",
        "prompt",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "latest_output_seq",
        "owner_user_id",
        "exit_code",
        "error_summary",
        "token_usage_json",
    )
    snapshot_uri = f"{snapshot.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(snapshot_uri, uri=True) as conn:
        available = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if not available:
            rows = []
        else:
            selected_columns = ", ".join(
                f'"{column}"' if column in available else f'NULL AS "{column}"'
                for column in columns
            )
            order_by = '"task_id"' if "task_id" in available else "rowid"
            rows = conn.execute(
                f"SELECT {selected_columns} FROM tasks ORDER BY {order_by}"
            ).fetchall()
    encoded = json.dumps(
        {"columns": columns, "rows": rows}, separators=(",", ":"), ensure_ascii=True
    ).encode()
    inode, mtime_ns, _ = _source_stat(source)
    return SourceFile(
        relative_path=relative_path,
        sha256=hashlib.sha256(encoded).hexdigest(),
        size=len(encoded),
        inode=inode,
        mtime_ns=mtime_ns,
    )


def _discover_json_sources(state_root: Path) -> tuple[Path, ...]:
    """Find legacy registries and checkpoint/state JSON under known roots."""
    source_roots = (state_root / "runtime", state_root / "session-states")
    discovered: list[Path] = []
    for source_root in source_roots:
        if not source_root.is_dir():
            continue
        discovered.extend(path for path in source_root.rglob("*.json") if path.is_file())
    return tuple(sorted(discovered, key=lambda path: _relative_path(path, state_root)))


def _discover_sqlite_sources(state_root: Path) -> tuple[Path, ...]:
    """Find every runtime SQLite legacy source, including the literature store."""
    runtime_root = state_root / "runtime"
    if not runtime_root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in runtime_root.rglob("*.sqlite3") if path.is_file()),
            key=lambda path: _relative_path(path, state_root),
        )
    )


def _normalize_relative_path(relative_path: str) -> str:
    candidate = PurePosixPath(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("source snapshot paths must be relative to the state root")
    return candidate.as_posix()


class SourceSnapshotSet:
    """A context-managed, fixed set of legacy JSON and SQLite sources.

    JSON sources are copied only after their pre/post inode, mtime, size, and
    SHA-256 observations agree. They are rechecked at every ``read_json`` and
    before a successful context exits. SQLite readers operate only on backup
    snapshots, which remain available until the context closes.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root.resolve()
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._snapshot_root: Path | None = None
        self._json_snapshots: dict[str, _JsonSnapshot] = {}
        self._sqlite_snapshots: dict[str, Path] = {}
        self._manifest: SourceManifest | None = None

    def __enter__(self) -> Self:
        if self._temporary_directory is not None:
            raise RuntimeError("SourceSnapshotSet cannot be entered more than once")
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="openscience-domain-source-")
        self._snapshot_root = Path(self._temporary_directory.name)
        try:
            self._capture()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                self.verify_unchanged()
        finally:
            self.close()
        _ = exc
        _ = traceback
        return False

    @property
    def manifest(self) -> SourceManifest:
        self._require_open()
        if self._manifest is None:
            raise RuntimeError("SourceSnapshotSet has not captured sources")
        return self._manifest

    @property
    def snapshot_root(self) -> Path:
        """The temporary root containing paths relative to the original state root."""
        self._require_open()
        if self._snapshot_root is None:
            raise RuntimeError("SourceSnapshotSet has not captured sources")
        return self._snapshot_root

    @property
    def json_sources(self) -> tuple[str, ...]:
        self._require_open()
        return tuple(sorted(self._json_snapshots))

    @property
    def sqlite_sources(self) -> tuple[str, ...]:
        self._require_open()
        return tuple(sorted(self._sqlite_snapshots))

    def json_path(self, relative_path: str) -> Path:
        """Return a fixed JSON snapshot path for a known state-relative source."""
        self._require_open()
        normalized = _normalize_relative_path(relative_path)
        self._verify_json_source(normalized)
        try:
            return self._json_snapshots[normalized].snapshot_path
        except KeyError as exc:
            raise FileNotFoundError(
                f"JSON source is not part of this snapshot: {normalized}"
            ) from exc

    def sqlite_path(self, relative_path: str) -> Path:
        """Return a fixed SQLite backup path for a known state-relative source."""
        self._require_open()
        normalized = _normalize_relative_path(relative_path)
        try:
            return self._sqlite_snapshots[normalized]
        except KeyError as exc:
            raise FileNotFoundError(
                f"SQLite source is not part of this snapshot: {normalized}"
            ) from exc

    def read_json(self, relative_path: str) -> object:
        """Read a JSON snapshot while proving its live source remains unchanged."""
        normalized = _normalize_relative_path(relative_path)
        self._verify_json_source(normalized)
        try:
            value = json.loads(self.json_path(normalized).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON source {normalized}: {exc}") from exc
        self._verify_json_source(normalized)
        return value

    def connect_sqlite(self, relative_path: str) -> sqlite3.Connection:
        """Open a read-only connection to a fixed SQLite backup snapshot."""
        snapshot = self.sqlite_path(relative_path)
        snapshot_uri = f"{snapshot.resolve().as_uri()}?mode=ro"
        return sqlite3.connect(snapshot_uri, uri=True)

    def verify_unchanged(self) -> None:
        """Reject a source set whose JSON membership or contents became stale."""
        self._require_open()
        current_json = {
            _relative_path(path, self._state_root)
            for path in _discover_json_sources(self._state_root)
        }
        expected_json = set(self._json_snapshots)
        if current_json != expected_json:
            raise SourceStaleError("JSON source set changed while import was running")
        for relative_path in sorted(expected_json):
            self._verify_json_source(relative_path)

    def close(self) -> None:
        """Delete temporary snapshots without modifying any legacy source."""
        temporary_directory = self._temporary_directory
        self._temporary_directory = None
        self._snapshot_root = None
        self._json_snapshots.clear()
        self._sqlite_snapshots.clear()
        self._manifest = None
        if temporary_directory is not None:
            temporary_directory.cleanup()

    def _capture(self) -> None:
        snapshot_root = self.snapshot_root
        files: list[SourceFile] = []
        for source in _discover_json_sources(self._state_root):
            relative_path = _relative_path(source, self._state_root)
            payload, fingerprint = _stable_json_fingerprint(source, relative_path)
            snapshot = snapshot_root / relative_path
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(payload)
            self._json_snapshots[relative_path] = _JsonSnapshot(source, snapshot, fingerprint)
            files.append(fingerprint)
        for source in _discover_sqlite_sources(self._state_root):
            relative_path = _relative_path(source, self._state_root)
            snapshot = snapshot_root / relative_path
            _snapshot_sqlite(source, snapshot)
            self._sqlite_snapshots[relative_path] = snapshot
            if source.name == "agentic_researcher.sqlite3":
                files.append(_legacy_agentic_fingerprint(source, snapshot, relative_path))
            else:
                files.append(_sqlite_snapshot_fingerprint(source, snapshot, relative_path))
        self._manifest = SourceManifest(
            state_root=self._state_root.name,
            files=tuple(sorted(files, key=lambda item: item.relative_path)),
        )

    def _verify_json_source(self, relative_path: str) -> None:
        self._require_open()
        try:
            snapshot = self._json_snapshots[relative_path]
        except KeyError as exc:
            raise FileNotFoundError(
                f"JSON source is not part of this snapshot: {relative_path}"
            ) from exc
        _, current = _stable_json_fingerprint(snapshot.source_path, relative_path)
        if current != snapshot.fingerprint:
            raise SourceStaleError(f"JSON source changed during import: {relative_path}")

    def _require_open(self) -> None:
        if self._temporary_directory is None:
            raise RuntimeError("SourceSnapshotSet must be used inside its context manager")


def capture_source_manifest(state_root: Path) -> SourceManifest:
    """Capture a one-shot manifest while preserving the legacy public API."""
    with SourceSnapshotSet(state_root) as snapshots:
        return snapshots.manifest

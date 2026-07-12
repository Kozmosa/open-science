"""Stable, read-only fingerprints for legacy domain migration sources."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

_JSON_SOURCES = ("projects.json", "task_edges.json", "workspaces.json")
_SQLITE_SOURCES = ("auth.sqlite3", "sessions.sqlite3", "agentic_researcher.sqlite3")


@dataclass(frozen=True, slots=True)
class SourceFile:
    relative_path: str
    sha256: str
    size: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SourceManifest:
    state_root: str
    files: tuple[SourceFile, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _fingerprint(path: Path, relative_path: str) -> SourceFile:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    stat = path.stat()
    return SourceFile(
        relative_path=relative_path,
        sha256=digest.hexdigest(),
        size=stat.st_size,
        inode=stat.st_ino,
        mtime_ns=stat.st_mtime_ns,
    )


def _snapshot_sqlite(source: Path) -> Path:
    temporary = tempfile.NamedTemporaryFile(
        prefix="openscience-domain-source-", suffix=".sqlite3", delete=False
    )
    temporary.close()
    snapshot = Path(temporary.name)
    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(snapshot))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return snapshot


def _fingerprint_legacy_tasks(source: Path) -> SourceFile:
    """Hash only legacy Task columns so shadow writes do not stale their source."""
    columns = (
        "task_id, project_id, workspace_id, environment_id, researcher_type, harness_engine, "
        "user_skills, user_mcp_servers, status, title, prompt, created_at, updated_at, "
        "started_at, completed_at, latest_output_seq, owner_user_id, exit_code, error_summary, "
        "token_usage_json"
    )
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as conn:
        try:
            rows = conn.execute(f"SELECT {columns} FROM tasks ORDER BY task_id").fetchall()
        except sqlite3.Error:
            rows = []
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()
    stat = source.stat()
    return SourceFile(
        relative_path="runtime/agentic_researcher.sqlite3#legacy_tasks",
        sha256=hashlib.sha256(encoded).hexdigest(),
        size=len(encoded),
        inode=stat.st_ino,
        # The same file is also the v2 target database. Its file mtime changes
        # on shadow writes, so it cannot participate in source equivalence.
        mtime_ns=0,
    )


def capture_source_manifest(state_root: Path) -> SourceManifest:
    """Fingerprint legacy JSON and consistent SQLite snapshots without source writes."""
    runtime_root = state_root / "runtime"
    files: list[SourceFile] = []
    for name in _JSON_SOURCES:
        source = runtime_root / name
        if source.exists():
            files.append(_fingerprint(source, f"runtime/{name}"))
    for name in _SQLITE_SOURCES:
        source = runtime_root / name
        if not source.exists():
            continue
        if name == "agentic_researcher.sqlite3":
            files.append(_fingerprint_legacy_tasks(source))
            continue
        snapshot = _snapshot_sqlite(source)
        try:
            files.append(_fingerprint(snapshot, f"runtime/{name}"))
        finally:
            snapshot.unlink(missing_ok=True)
    return SourceManifest(state_root=str(state_root.resolve()), files=tuple(files))

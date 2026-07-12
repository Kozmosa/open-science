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
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO
from uuid import uuid4

_LOG = logging.getLogger(__name__)

_BACKUP_VERSION = 3

# Known SQLite databases relative to <state_root>/runtime/
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

# Runtime JSON files relative to <state_root>/runtime/
_RUNTIME_CONFIGS: tuple[str, ...] = (
    "projects.json",
    "task_edges.json",
    "workspaces.json",
)

# Small state subdirectories relative to <state_root>/
_STATE_DIRS: tuple[str, ...] = (
    "session-states",
    "detections",
)


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


def _dump_sqlite_safe(source: Path, dest: Path) -> None:
    """Consistent snapshot of a live SQLite database via the C backup API."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    # A point-in-time SQLite backup is a single main database file.  Some
    # connection configurations leave transient sidecars beside the staged
    # destination; they must never become independent archive members.
    for suffix in ("-wal", "-shm", "-journal"):
        dest.with_name(f"{dest.name}{suffix}").unlink(missing_ok=True)


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


def _file_meta(path: Path, *, source_path: str, schema_version: int | None = None) -> FileMeta:
    """Return manifest metadata for a staged regular file."""
    stat = path.stat()
    return FileMeta(
        size=stat.st_size,
        sha256=_sha256_of(path),
        source_path=source_path,
        schema_version=schema_version,
        mode=stat.st_mode & 0o7777,
        uid=stat.st_uid,
        gid=stat.st_gid,
    )


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

            # 1. SQLite databases
            db_dir = stage / "databases"
            db_dir.mkdir()
            for name in _SQLITE_DATABASES:
                src = self._runtime_root / name
                if not src.exists():
                    continue
                dst = db_dir / name
                _dump_sqlite_safe(src, dst)
                schema_version = _database_schema_version(dst, _database_name_from_filename(name))
                # The read-only schema probe can itself create transient WAL
                # bookkeeping files on some SQLite builds.
                for suffix in ("-wal", "-shm", "-journal"):
                    dst.with_name(f"{dst.name}{suffix}").unlink(missing_ok=True)
                manifest.databases[name] = _file_meta(
                    dst,
                    source_path=f"runtime/{name}",
                    schema_version=schema_version,
                )
                _LOG.info("backed up database %s (%d bytes)", name, dst.stat().st_size)

            # 2. Top-level config files
            cfg_dir = stage / "config"
            cfg_dir.mkdir()
            for name in (*_TOPLEVEL_CONFIGS, *_RUNTIME_CONFIGS):
                src = (self._runtime_root if name in _RUNTIME_CONFIGS else self._state_root) / name
                if not src.exists():
                    continue
                dst = cfg_dir / name
                shutil.copy2(src, dst)
                manifest.config_files[name] = _file_meta(
                    dst,
                    source_path=f"runtime/{name}" if name in _RUNTIME_CONFIGS else name,
                )
                _LOG.info("backed up config %s", name)

            # 3. State subdirectories
            for dirname in _STATE_DIRS:
                src = self._state_root / dirname
                if src.is_dir():
                    shutil.copytree(src, stage / dirname)
                    _LOG.info("backed up state dir %s", dirname)

            # 4. Optional: workspaces
            if include_workspaces and workspace_root and workspace_root.is_dir():
                shutil.copytree(workspace_root, stage / "workspaces")
                _LOG.info("backed up workspaces")

            # 5. Optional: tenant homes
            if include_tenants and tenant_root and tenant_root.is_dir():
                shutil.copytree(tenant_root, stage / "tenants")
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
                    meta = _file_meta(item, source_path=relative_path)
                manifest.files[relative_path] = meta

            manifest.includes_workspaces = (stage / "workspaces").is_dir()
            manifest.includes_tenants = (stage / "tenants").is_dir()
            manifest.tree_sha256 = _tree_sha256(manifest.files)

            # 6. Manifest
            (stage / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")

            # 7. Pack archive
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(str(archive), "w:gz") as tar:
                for item in sorted(stage.iterdir()):
                    tar.add(str(item), arcname=item.name)

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
                for member_name in sorted(actual_files - expected_files):
                    errors.append(f"{member_name}: not listed in manifest")
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
                if manifest.version >= 3 and meta.mode is not None and member.mode != meta.mode:
                    errors.append(f"{member_name}: mode mismatch")

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
    ) -> Path:
        """Restore a backup into a *new* state root and return that path.

        The active state root is never overwritten.  The caller must provide a
        previously non-existent ``target_state_root``; all archive checks and
        SQLite integrity checks finish in a sibling candidate directory before
        it is atomically renamed into place.  A pre-restore snapshot of this
        service's state root is still created unless *skip_pre_backup* is true.
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_path}")

        if target_state_root is None:
            raise ValueError(
                "target_state_root is required; restore only supports a new staged root"
            )
        state_root = target_state_root.resolve()
        if state_root.exists():
            raise ValueError(f"target_state_root must not exist: {state_root}")

        manifest = self.verify_backup(archive_path)

        if manifest.version > _BACKUP_VERSION:
            raise ValueError(
                f"Backup version {manifest.version} > supported {_BACKUP_VERSION}. "
                "Upgrade OpenScience first."
            )

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
        if target_workspace_root is not None:
            if target_workspace_root.exists():
                raise ValueError(f"target_workspace_root must not exist: {target_workspace_root}")
            candidate_workspace_root = target_workspace_root.parent / (
                f".{target_workspace_root.name}.restore-{uuid4().hex}"
            )
        if target_tenant_root is not None:
            if target_tenant_root.exists():
                raise ValueError(f"target_tenant_root must not exist: {target_tenant_root}")
            candidate_tenant_root = target_tenant_root.parent / (
                f".{target_tenant_root.name}.restore-{uuid4().hex}"
            )

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
                dest = (runtime_root if cfg_name in _RUNTIME_CONFIGS else candidate_root) / cfg_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                _LOG.info("restored config %s", cfg_name)

            # 3. State subdirectories
            for dirname in _STATE_DIRS:
                src = stage / dirname
                if src.is_dir():
                    shutil.copytree(src, candidate_root / dirname)
                    _LOG.info("restored state dir %s", dirname)

            # 4. Optional: workspaces
            if target_workspace_root and manifest.includes_workspaces:
                ws_src = stage / "workspaces"
                if ws_src.is_dir():
                    assert candidate_workspace_root is not None
                    shutil.copytree(ws_src, candidate_workspace_root)
                    _LOG.info("staged workspaces → %s", candidate_workspace_root)

            # 5. Optional: tenants
            if target_tenant_root and manifest.includes_tenants:
                t_src = stage / "tenants"
                if t_src.is_dir():
                    assert candidate_tenant_root is not None
                    shutil.copytree(t_src, candidate_tenant_root)
                    _LOG.info("staged tenants → %s", candidate_tenant_root)

            for db_name in manifest.databases:
                _validate_sqlite_database(runtime_root / db_name)

            os.replace(candidate_root, state_root)
            if candidate_workspace_root is not None:
                assert target_workspace_root is not None
                os.replace(candidate_workspace_root, target_workspace_root)
            if candidate_tenant_root is not None:
                assert target_tenant_root is not None
                os.replace(candidate_tenant_root, target_tenant_root)

        _LOG.info("restore staged and published to %s", state_root)
        return state_root

    # ── internal ──────────────────────────────────────────────────

    @staticmethod
    def _read_manifest(archive_path: Path) -> BackupManifest:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            member = tar.extractfile("manifest.json")
            if member is None:
                raise ValueError("Invalid backup: missing manifest.json")
            return BackupManifest.from_json(member.read().decode("utf-8"))

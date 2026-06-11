"""Backup and restore service for AINRF persistent state.

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
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_LOG = logging.getLogger(__name__)

_BACKUP_VERSION = 1

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


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ── manifest ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FileMeta:
    size: int
    sha256: str


@dataclass(slots=True)
class BackupManifest:
    version: int = _BACKUP_VERSION
    created_at: str = ""
    databases: dict[str, FileMeta] = field(default_factory=dict)
    config_files: dict[str, FileMeta] = field(default_factory=dict)
    includes_workspaces: bool = False
    includes_tenants: bool = False

    # -- serialisation --------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> BackupManifest:
        d = json.loads(text)
        for key in ("databases", "config_files"):
            if key in d and isinstance(d[key], dict):
                d[key] = {k: FileMeta(**v) for k, v in d[key].items()}
        return cls(**d)


# ── service ───────────────────────────────────────────────────────


class BackupService:
    """Create, verify, and restore AINRF data backups."""

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

        manifest = BackupManifest(
            created_at=datetime.now(timezone.utc).isoformat(),
            includes_workspaces=include_workspaces,
            includes_tenants=include_tenants,
        )

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
                manifest.databases[name] = FileMeta(dst.stat().st_size, _sha256_of(dst))
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
                manifest.config_files[name] = FileMeta(dst.stat().st_size, _sha256_of(dst))
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
        """Verify archive integrity (manifest + size checks).

        Returns the parsed manifest on success.
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_path}")

        manifest = self._read_manifest(archive_path)
        if manifest.version > _BACKUP_VERSION:
            raise ValueError(
                f"Backup version {manifest.version} > supported {_BACKUP_VERSION}. "
                "Upgrade AINRF first."
            )

        errors: list[str] = []
        with tarfile.open(str(archive_path), "r:gz") as tar:
            for db_name, meta in manifest.databases.items():
                try:
                    m = tar.getmember(f"databases/{db_name}")
                    if m.size != meta.size:
                        errors.append(f"databases/{db_name}: size mismatch")
                except KeyError:
                    errors.append(f"databases/{db_name}: missing")

            for cfg_name, meta in manifest.config_files.items():
                try:
                    m = tar.getmember(f"config/{cfg_name}")
                    if m.size != meta.size:
                        errors.append(f"config/{cfg_name}: size mismatch")
                except KeyError:
                    errors.append(f"config/{cfg_name}: missing")

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
    ) -> None:
        """Restore state from a backup archive.

        A pre-restore safety snapshot is created automatically unless
        *skip_pre_backup* is ``True``.
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_path}")

        state_root = target_state_root or self._state_root
        runtime_root = state_root / "runtime"
        manifest = self._read_manifest(archive_path)

        if manifest.version > _BACKUP_VERSION:
            raise ValueError(
                f"Backup version {manifest.version} > supported {_BACKUP_VERSION}. "
                "Upgrade AINRF first."
            )

        _LOG.info(
            "restoring backup from %s (%s, %d db, %d cfg)",
            archive_path,
            manifest.created_at,
            len(manifest.databases),
            len(manifest.config_files),
        )

        # Pre-restore safety net
        if not skip_pre_backup and runtime_root.exists() and any(runtime_root.iterdir()):
            pre = archive_path.parent / f"pre-restore-{_ts()}.tar.gz"
            _LOG.info("creating pre-restore safety backup → %s", pre)
            BackupService(state_root).create_backup(pre)
            _LOG.info(
                "safety backup saved; if restore fails, recover with: ainrf backup restore %s", pre
            )

        # Extract to staging, then copy — avoids partial overwrite on failure
        with tempfile.TemporaryDirectory(prefix="ainrf-restore-") as tmp:
            stage = Path(tmp) / "stage"
            with tarfile.open(str(archive_path), "r:gz") as tar:
                tar.extractall(str(stage), filter="data")

            # 1. Databases
            for db_name, meta in manifest.databases.items():
                src = stage / "databases" / db_name
                if not src.exists():
                    _LOG.warning("database %s listed in manifest but absent from archive", db_name)
                    continue
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
                    _LOG.warning("config %s listed in manifest but absent from archive", cfg_name)
                    continue
                actual = _sha256_of(src)
                if actual != meta.sha256:
                    raise ValueError(f"{cfg_name}: checksum mismatch (archive corrupted)")
                dest = (runtime_root if cfg_name in _RUNTIME_CONFIGS else state_root) / cfg_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                _LOG.info("restored config %s", cfg_name)

            # 3. State subdirectories
            for dirname in _STATE_DIRS:
                src = stage / dirname
                if src.is_dir():
                    dest = state_root / dirname
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    shutil.copytree(src, dest)
                    _LOG.info("restored state dir %s", dirname)

            # 4. Optional: workspaces
            if target_workspace_root and manifest.includes_workspaces:
                ws_src = stage / "workspaces"
                if ws_src.is_dir():
                    if target_workspace_root.is_dir():
                        shutil.rmtree(target_workspace_root)
                    shutil.copytree(ws_src, target_workspace_root)
                    _LOG.info("restored workspaces → %s", target_workspace_root)

            # 5. Optional: tenants
            if target_tenant_root and manifest.includes_tenants:
                t_src = stage / "tenants"
                if t_src.is_dir():
                    if target_tenant_root.is_dir():
                        shutil.rmtree(target_tenant_root)
                    shutil.copytree(t_src, target_tenant_root)
                    _LOG.info("restored tenants → %s", target_tenant_root)

        _LOG.info("restore complete")

    # ── internal ──────────────────────────────────────────────────

    @staticmethod
    def _read_manifest(archive_path: Path) -> BackupManifest:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            member = tar.extractfile("manifest.json")
            if member is None:
                raise ValueError("Invalid backup: missing manifest.json")
            return BackupManifest.from_json(member.read().decode("utf-8"))

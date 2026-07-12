"""Unit tests for ainrf.backup — create, verify, restore roundtrip."""

from __future__ import annotations

import hashlib
import sqlite3
import tarfile
from io import BytesIO
import json
from pathlib import Path

import pytest

from ainrf.backup.service import BackupManifest, BackupService

pytestmark = [pytest.mark.unit]


# ── helpers ───────────────────────────────────────────────────────


def _seed_state(state_root: Path) -> None:
    """Populate a minimal state_root with databases and config."""
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    # Create two SQLite databases with a row each
    for db_name in ("auth.sqlite3", "sessions.sqlite3"):
        conn = sqlite3.connect(str(runtime / db_name))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('hello')")
        conn.commit()
        conn.close()

    # Top-level config
    (state_root / "config.json").write_text('{"api_key_hashes": []}', encoding="utf-8")
    (state_root / "search-settings.json").write_text(
        '{"active_backend": "semantic_scholar"}', encoding="utf-8"
    )

    # Runtime config
    (runtime / "projects.json").write_text('{"default": {}}', encoding="utf-8")
    (runtime / "workspaces.json").write_text('{"default": {}}', encoding="utf-8")

    # State subdirectory
    ss = state_root / "session-states" / "task-abc"
    ss.mkdir(parents=True)
    (ss / "checkpoint.json").write_text('{"step": 1}', encoding="utf-8")


def _write_v2_archive(
    archive: Path,
    *,
    database: Path,
    config: Path,
    auth_schema_version: int | None = None,
) -> Path:
    """Write the on-disk manifest format emitted by backup manifest v2."""
    manifest = {
        "version": 2,
        "created_at": "2026-07-12T00:00:00+00:00",
        "databases": {
            "auth.sqlite3": {
                "size": database.stat().st_size,
                "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                "source_path": "runtime/auth.sqlite3",
                "schema_version": auth_schema_version,
            }
        },
        "config_files": {
            "config.json": {
                "size": config.stat().st_size,
                "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                "source_path": "config.json",
                "schema_version": None,
            }
        },
        "includes_workspaces": False,
        "includes_tenants": False,
    }
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(database, arcname="databases/auth.sqlite3")
        tar.add(config, arcname="config/config.json")
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, BytesIO(manifest_bytes))
    return archive


class _RejectingRestoreValidator:
    def __init__(self, candidates: list[Path]) -> None:
        self._candidates = candidates

    def __call__(self, candidate_root: Path, manifest: BackupManifest) -> None:
        self._candidates.append(candidate_root)
        assert candidate_root.exists()
        assert (candidate_root / "runtime" / "auth.sqlite3").exists()
        assert manifest.version == 3
        raise ValueError("reconciliation rejected staged restore")


# ── tests ─────────────────────────────────────────────────────────


def test_create_backup_captures_databases(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")

    assert archive.exists()
    assert archive.suffix == ".gz"
    # Archive should be readable
    manifest = svc.verify_backup(archive)
    assert manifest.version == 3
    assert "auth.sqlite3" in manifest.databases
    assert "sessions.sqlite3" in manifest.databases
    assert "config.json" in manifest.config_files
    assert "projects.json" in manifest.config_files
    assert "workspaces.json" in manifest.config_files
    assert manifest.config_files["workspaces.json"].source_path == "runtime/workspaces.json"
    assert not manifest.includes_workspaces


def test_create_backup_skips_missing_dbs(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    (state_root / "runtime").mkdir(parents=True)
    # Only one DB exists
    conn = sqlite3.connect(str(state_root / "runtime" / "auth.sqlite3"))
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")
    manifest = svc.verify_backup(archive)

    assert "auth.sqlite3" in manifest.databases
    assert "sessions.sqlite3" not in manifest.databases


def test_verify_rejects_corrupted_archive(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")

    # Corrupt the archive by truncating
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])

    with pytest.raises(Exception):
        svc.verify_backup(archive)


def test_restore_roundtrip(tmp_path: Path) -> None:
    src_root = tmp_path / "src-state"
    _seed_state(src_root)

    svc = BackupService(src_root)
    archive = svc.create_backup(tmp_path / "out")

    # Restore into a fresh directory
    dst_root = tmp_path / "dst-state"
    dst_svc = BackupService(dst_root)
    dst_svc.restore_backup(archive, target_state_root=dst_root, skip_pre_backup=True)

    # Verify databases restored
    for db_name in ("auth.sqlite3", "sessions.sqlite3"):
        conn = sqlite3.connect(str(dst_root / "runtime" / db_name))
        rows = conn.execute("SELECT v FROM t").fetchall()
        conn.close()
        assert rows == [("hello",)]

    # Verify config restored
    assert (dst_root / "config.json").read_text() == '{"api_key_hashes": []}'
    assert (dst_root / "search-settings.json").exists()
    assert (dst_root / "runtime" / "projects.json").exists()

    # Verify state subdirectory restored
    assert (
        dst_root / "session-states" / "task-abc" / "checkpoint.json"
    ).read_text() == '{"step": 1}'


def test_restore_creates_pre_backup(tmp_path: Path) -> None:
    src_root = tmp_path / "src-state"
    _seed_state(src_root)

    svc = BackupService(src_root)
    archive = svc.create_backup(tmp_path / "archives" / "test.tar.gz")

    # Restore with pre-backup enabled (default)
    dst_root = tmp_path / "dst-state"
    _seed_state(dst_root)  # existing data

    dst_svc = BackupService(dst_root)
    staged_root = tmp_path / "staged-state"
    dst_svc.restore_backup(archive, target_state_root=staged_root)  # pre-backup defaults to True

    # A pre-restore backup should exist alongside the archive
    pre_backups = list(archive.parent.glob("pre-restore-*.tar.gz"))
    assert len(pre_backups) == 1
    assert (dst_root / "runtime" / "projects.json").exists()


def test_backup_includes_workspaces(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    ws_root = tmp_path / "ws"
    (ws_root / "project1").mkdir(parents=True)
    (ws_root / "project1" / "README.md").write_text("# project1", encoding="utf-8")

    svc = BackupService(state_root)
    archive = svc.create_backup(
        tmp_path / "out.tar.gz",
        include_workspaces=True,
        workspace_root=ws_root,
    )
    manifest = svc.verify_backup(archive)
    assert manifest.includes_workspaces

    # Restore with workspace
    dst_root = tmp_path / "dst-state"
    dst_ws = tmp_path / "dst-ws"
    dst_svc = BackupService(dst_root)
    dst_svc.restore_backup(
        archive,
        target_state_root=dst_root,
        target_workspace_root=dst_ws,
        skip_pre_backup=True,
    )
    assert (dst_ws / "project1" / "README.md").read_text() == "# project1"


def test_verify_missing_archive(tmp_path: Path) -> None:
    svc = BackupService(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.verify_backup(tmp_path / "nonexistent.tar.gz")


def test_restore_missing_archive(tmp_path: Path) -> None:
    svc = BackupService(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.restore_backup(tmp_path / "nonexistent.tar.gz")


def test_restore_requires_new_staged_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")

    existing_root = tmp_path / "existing"
    existing_root.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        BackupService(source_root).restore_backup(archive, target_state_root=existing_root)


def test_verify_rejects_checksum_tampering(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "config/projects.json":
                replacement = b'{"changed": {}}'
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(ValueError, match="checksum mismatch"):
        BackupService(source_root).verify_backup(tampered)


def test_manifest_v3_inventories_every_nested_state_member(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    (state_root / "detections" / "env-host").mkdir(parents=True)
    (state_root / "detections" / "env-host" / "snapshot.json").write_text(
        '{"status": "ok"}', encoding="utf-8"
    )
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "project" / "nested").mkdir(parents=True)
    (workspace_root / "project" / "nested" / "note.txt").write_text("note", encoding="utf-8")
    tenant_root = tmp_path / "tenants"
    (tenant_root / "alice" / ".config").mkdir(parents=True)
    (tenant_root / "alice" / ".config" / "settings.json").write_text("{}", encoding="utf-8")

    archive = BackupService(state_root).create_backup(
        tmp_path / "archive.tar.gz",
        include_workspaces=True,
        workspace_root=workspace_root,
        include_tenants=True,
        tenant_root=tenant_root,
    )

    manifest = BackupService(state_root).verify_backup(archive)
    assert manifest.version == 3
    assert manifest.includes_workspaces
    assert manifest.includes_tenants
    assert manifest.tree_sha256
    assert {
        "session-states/task-abc/checkpoint.json",
        "detections/env-host/snapshot.json",
        "workspaces/project/nested/note.txt",
        "tenants/alice/.config/settings.json",
    } <= set(manifest.files)
    assert manifest.files["workspaces/project/nested/note.txt"].mode is not None
    assert manifest.files["workspaces/project/nested/note.txt"].uid is not None


def test_verify_rejects_tampered_nested_state_member(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    archive = BackupService(state_root).create_backup(tmp_path / "archive.tar.gz")
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "session-states/task-abc/checkpoint.json":
                replacement = b'{"step": 9}'
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(
        ValueError, match="session-states/task-abc/checkpoint.json: checksum mismatch"
    ):
        BackupService(state_root).verify_backup(tampered)


def test_verify_rejects_include_flag_mismatch(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    (workspace_root / "README.md").write_text("workspace", encoding="utf-8")
    archive = BackupService(state_root).create_backup(
        tmp_path / "archive.tar.gz", include_workspaces=True, workspace_root=workspace_root
    )
    tampered = tmp_path / "flag-mismatch.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "manifest.json":
                assert data is not None
                payload = json.loads(data.read().decode("utf-8"))
                payload["includes_workspaces"] = False
                replacement = json.dumps(payload).encode("utf-8")
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(
        ValueError, match="workspaces: include flag does not match archive contents"
    ):
        BackupService(state_root).verify_backup(tampered)


def test_v2_archive_remains_verifiable_and_restorable(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    database = source_root / "runtime" / "auth.sqlite3"
    config = source_root / "config.json"
    archive = _write_v2_archive(tmp_path / "v2.tar.gz", database=database, config=config)

    service = BackupService(source_root)
    assert service.verify_backup(archive).version == 2
    target = tmp_path / "restored"
    service.restore_backup(archive, target_state_root=target, skip_pre_backup=True)
    assert (target / "runtime" / "auth.sqlite3").exists()
    assert (target / "config.json").read_text(encoding="utf-8") == config.read_text(
        encoding="utf-8"
    )


def test_restore_rejects_manifest_schema_version_before_promotion(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    database = source_root / "runtime" / "auth.sqlite3"
    conn = sqlite3.connect(str(database))
    conn.execute(
        "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO _schema_version (database, version) VALUES ('auth', 7)")
    conn.commit()
    conn.close()

    target = tmp_path / "schema-mismatch"
    archive = _write_v2_archive(
        tmp_path / "schema-mismatch.tar.gz",
        database=database,
        config=source_root / "config.json",
        auth_schema_version=8,
    )

    with pytest.raises(ValueError, match="schema version mismatch"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
        )

    assert not target.exists()
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_restore_runs_custom_validator_before_promotion_and_cleans_candidate(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    candidates: list[Path] = []
    validator = _RejectingRestoreValidator(candidates)

    with pytest.raises(ValueError, match="reconciliation rejected staged restore"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
            validators=(validator,),
        )

    assert not target.exists()
    assert candidates
    assert all(not candidate.exists() for candidate in candidates)
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_restore_removes_promotion_journal_after_success(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    journal = target.parent / f".{target.name}.restore-promotion.json"

    restored = BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    assert restored == target
    assert (target / "runtime" / "auth.sqlite3").exists()
    assert not journal.exists()

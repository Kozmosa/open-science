"""Unit tests for ainrf.backup — create, verify, restore roundtrip."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainrf.backup.service import BackupService

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

    # State subdirectory
    ss = state_root / "session-states" / "task-abc"
    ss.mkdir(parents=True)
    (ss / "checkpoint.json").write_text('{"step": 1}', encoding="utf-8")


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
    assert manifest.version == 1
    assert "auth.sqlite3" in manifest.databases
    assert "sessions.sqlite3" in manifest.databases
    assert "config.json" in manifest.config_files
    assert "projects.json" in manifest.config_files
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
    dst_svc.restore_backup(archive, skip_pre_backup=True)

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
    dst_svc.restore_backup(archive)  # skip_pre_backup defaults to False

    # A pre-restore backup should exist alongside the archive
    pre_backups = list(archive.parent.glob("pre-restore-*.tar.gz"))
    assert len(pre_backups) == 1


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

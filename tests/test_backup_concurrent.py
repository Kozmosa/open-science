"""Backup service tests including concurrent-write snapshot consistency."""

from __future__ import annotations

import sqlite3
import tarfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

from ainrf.backup.service import BackupService
from ainrf.db.connection import connect

pytestmark = [pytest.mark.unit, pytest.mark.backup]


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    root = tmp_path / "ainrf-state"
    (root / "runtime").mkdir(parents=True)
    return root


@pytest.fixture
def populated_db(state_root: Path) -> Path:
    db = state_root / "runtime" / "sessions.sqlite3"
    conn = connect(str(db))
    conn.execute("CREATE TABLE counters (id INTEGER PRIMARY KEY, val INTEGER NOT NULL)")
    conn.execute("INSERT INTO counters (id, val) VALUES (1, 0)")
    conn.commit()
    conn.close()
    return db


class TestBackupService:
    def test_create_backup_contains_manifest(self, state_root: Path, populated_db: Path) -> None:
        svc = BackupService(state_root)
        archive = svc.create_backup(output_path=state_root.parent / "manifest-backup.tar.gz")

        assert archive.exists()
        with tarfile.open(str(archive), "r:gz") as tar:
            assert "manifest.json" in tar.getnames()
            assert "databases/sessions.sqlite3" in tar.getnames()

        manifest = svc.verify_backup(archive)
        assert manifest.version == 3
        assert "sessions.sqlite3" in manifest.databases

    @pytest.mark.concurrent
    def test_backup_during_concurrent_writes_is_consistent(
        self, state_root: Path, populated_db: Path
    ) -> None:
        """SQLite backup() should yield a transactionally consistent snapshot."""
        svc = BackupService(state_root)
        db_path = populated_db

        def writer(_i: int) -> None:
            c = connect(str(db_path))
            c.execute("UPDATE counters SET val = val + 1 WHERE id = 1")
            c.commit()
            c.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            future = pool.submit(
                svc.create_backup,
                output_path=state_root.parent / "concurrent-backup.tar.gz",
            )
            list(pool.map(writer, range(100)))
            archive = future.result()

        # Verify archive integrity.
        manifest = svc.verify_backup(archive)
        assert "sessions.sqlite3" in manifest.databases

        # Restore to a fresh directory and inspect the counter value.
        restore_root = state_root.parent / "restored"
        svc.restore_backup(archive, target_state_root=restore_root)

        restored_conn = sqlite3.connect(str(restore_root / "runtime" / "sessions.sqlite3"))
        cur = restored_conn.execute("SELECT val FROM counters WHERE id = 1")
        restored_val = cur.fetchone()[0]
        restored_conn.close()

        live_conn = sqlite3.connect(str(db_path))
        cur = live_conn.execute("SELECT val FROM counters WHERE id = 1")
        live_val = cur.fetchone()[0]
        live_conn.close()

        # Snapshot must capture a point-in-time value.
        assert 0 <= restored_val <= live_val
        assert isinstance(restored_val, int)

    def test_restore_rejects_corrupted_database(self, state_root: Path, populated_db: Path) -> None:
        svc = BackupService(state_root)
        archive = svc.create_backup(output_path=state_root.parent / "source-backup.tar.gz")

        # Tamper with the database inside the archive by appending a second
        # member with the same name so extraction yields corrupted bytes.
        tampered = state_root.parent / "tampered.tar.gz"
        with tarfile.open(str(archive), "r:gz") as src:
            with tarfile.open(str(tampered), "w:gz") as dst:
                for member in src.getmembers():
                    data = src.extractfile(member)
                    dst.addfile(member, data)
                    if member.name == "databases/sessions.sqlite3" and data:
                        junk = tarfile.TarInfo(name="databases/sessions.sqlite3")
                        junk.size = 4
                        dst.addfile(junk, BytesIO(b"\x00\x00\x00\x00"))

        restore_root = state_root.parent / "restored2"
        # Restore verifies all members before staging, so duplicate members are rejected.
        with pytest.raises(ValueError, match="duplicated"):
            svc.restore_backup(tampered, target_state_root=restore_root)

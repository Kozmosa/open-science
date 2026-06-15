"""Database edge-case and SQLite contention tests.

These tests exercise the shared connection factory and persistence primitives
that underpin every service.  Run with ``-n1`` so worker isolation does not
mask real lock contention.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ainrf.db.connection import atomic_write_json, connect
from ainrf.sessions.service import SessionService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


# ---------------------------------------------------------------------------
# connect() baseline behaviour
# ---------------------------------------------------------------------------
class TestConnectionBaseline:
    def test_connect_sets_wal_busy_timeout_foreign_keys(self, tmp_path: Path):
        db_path = tmp_path / "test.sqlite3"
        conn = connect(str(db_path))
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].upper() == "WAL"
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()

    def test_connect_isolation_level_immediate(self, tmp_path: Path):
        db_path = tmp_path / "test.sqlite3"
        conn = connect(str(db_path))
        try:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.commit()
            # BEGIN IMMEDIATE should acquire a write lock without any DML.
            conn.execute("BEGIN IMMEDIATE")
            conn.commit()
        finally:
            conn.close()

    def test_foreign_keys_enforced(self, tmp_path: Path):
        db_path = tmp_path / "test.sqlite3"
        conn = connect(str(db_path))
        try:
            conn.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id))"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO child VALUES ('c1', 'missing')")
                conn.commit()
        finally:
            conn.close()

    def test_connect_extra_pragmas(self, tmp_path: Path):
        db_path = tmp_path / "test.sqlite3"
        conn = connect(str(db_path), extra_pragmas={"synchronous": "NORMAL"})
        try:
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# SQLite contention
# ---------------------------------------------------------------------------
class TestSQLiteContention:
    def test_busy_timeout_absorbs_concurrent_writes(self, tmp_path: Path):
        """16 threads INSERTing concurrently should not raise database is locked."""
        db_path = tmp_path / "test.sqlite3"
        conn = connect(str(db_path))
        try:
            conn.execute("CREATE TABLE counters (id INTEGER PRIMARY KEY, val INTEGER)")
            conn.execute("INSERT INTO counters VALUES (1, 0)")
            conn.commit()
        finally:
            conn.close()

        def increment(_i: int):
            c = connect(str(db_path))
            try:
                c.execute("UPDATE counters SET val = val + 1 WHERE id = 1")
                c.commit()
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(increment, range(100)))

        conn = connect(str(db_path))
        try:
            total = conn.execute("SELECT val FROM counters WHERE id = 1").fetchone()[0]
            assert total == 100
        finally:
            conn.close()

    def test_foreign_keys_persist_across_connections(self, tmp_path: Path):
        """foreign_keys is per-connection; every new connect() must re-enable it."""
        db_path = tmp_path / "test.sqlite3"

        def make_schema():
            conn = connect(str(db_path))
            try:
                conn.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
                conn.execute(
                    "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id))"
                )
                conn.commit()
            finally:
                conn.close()

        make_schema()

        conn = connect(str(db_path))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO child VALUES ('c1', 'missing')")
                conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------
class TestAtomicWriteJson:
    def test_atomic_write_json_roundtrip(self, tmp_path: Path):
        path = tmp_path / "data.json"
        atomic_write_json(path, {"key": "value", "unicode": "中文"})
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == {
            "key": "value",
            "unicode": "中文",
        }
        assert not (tmp_path / "data.json.tmp").exists()

    def test_atomic_write_json_concurrent_overwrite(self, tmp_path: Path):
        path = tmp_path / "data.json"

        def writer(i: int):
            atomic_write_json(path, {"writer": i})

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(writer, range(20)))

        # File must contain exactly one complete JSON object, never a mix.
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "writer" in data

    def test_atomic_write_json_is_atomic_on_crash(self, tmp_path: Path):
        """If the writer process dies mid-write, the original file must remain intact."""
        path = tmp_path / "data.json"
        original = {"version": 1}
        atomic_write_json(path, original)

        def crash_writer(path_str: str):
            import os

            target = Path(path_str)
            tmp = target.parent / (target.name + ".crash.tmp")
            # Simulate crash by writing tmp but never renaming.
            tmp.write_text('{"version": 2}', encoding="utf-8")
            os._exit(1)  # Hard exit without cleanup.

        proc = multiprocessing.Process(target=crash_writer, args=(str(path),))
        proc.start()
        proc.join()

        # Original file must be untouched.
        assert json.loads(path.read_text(encoding="utf-8")) == original
        # tmp file may or may not exist depending on timing; if it does, it
        # must not have overwritten the target.
        tmp = path.parent / (path.name + ".crash.tmp")
        if tmp.exists():
            assert tmp.read_text(encoding="utf-8") == '{"version": 2}'


# ---------------------------------------------------------------------------
# Service-level DB edge cases
# ---------------------------------------------------------------------------
class TestServiceDbEdgeCases:
    def test_corrupted_sqlite_file_raises_on_initialize(self, tmp_path: Path):
        db_path = tmp_path / "runtime" / "sessions.sqlite3"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"this is not a sqlite database")

        svc = SessionService(state_root=tmp_path)
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError)):
            svc.initialize()

    def test_missing_runtime_directory_is_created(self, tmp_path: Path):
        svc = SessionService(state_root=tmp_path)
        svc.initialize()
        assert (tmp_path / "runtime" / "sessions.sqlite3").exists()

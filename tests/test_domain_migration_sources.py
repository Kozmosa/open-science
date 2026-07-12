"""Read-only legacy source manifest tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainrf.domain_migration import capture_source_manifest
from ainrf.domain_migration.sources import SourceSnapshotSet, SourceStaleError

pytestmark = [pytest.mark.unit]


def test_capture_source_manifest_is_source_read_only(state_root: Path) -> None:
    runtime = state_root / "runtime"
    projects = runtime / "projects.json"
    projects.write_text('{"project-a": {}}', encoding="utf-8")
    sessions = runtime / "sessions.json"
    sessions.write_text('{"items": []}', encoding="utf-8")
    database = runtime / "sessions.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE session_rows (id INTEGER PRIMARY KEY)")

    before = (
        projects.stat().st_mtime_ns,
        sessions.stat().st_mtime_ns,
        database.stat().st_mtime_ns,
    )
    manifest = capture_source_manifest(state_root)
    after = (
        projects.stat().st_mtime_ns,
        sessions.stat().st_mtime_ns,
        database.stat().st_mtime_ns,
    )

    assert before == after
    assert {item.relative_path for item in manifest.files} == {
        "runtime/projects.json",
        "runtime/sessions.json",
        "runtime/sessions.sqlite3",
    }
    assert all(item.sha256 for item in manifest.files)
    assert manifest.digest


def test_source_snapshot_set_rejects_changed_json_source(state_root: Path) -> None:
    source = state_root / "runtime" / "projects.json"
    source.write_text('{"items": [{"project_id": "before"}]}', encoding="utf-8")

    with pytest.raises(SourceStaleError, match="runtime/projects.json"):
        with SourceSnapshotSet(state_root) as snapshots:
            assert snapshots.read_json("runtime/projects.json") == {
                "items": [{"project_id": "before"}]
            }
            source.write_text('{"items": [{"project_id": "after"}]}', encoding="utf-8")

            snapshots.read_json("runtime/projects.json")


def test_sqlite_snapshot_reads_wal_and_remains_fixed(state_root: Path) -> None:
    database = state_root / "runtime" / "sessions.sqlite3"
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE session_rows (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        writer.execute("INSERT INTO session_rows (title) VALUES ('before')")
        writer.commit()
        assert Path(f"{database}-wal").exists()

        with SourceSnapshotSet(state_root) as snapshots:
            assert snapshots.sqlite_sources == ("runtime/sessions.sqlite3",)
            with snapshots.connect_sqlite("runtime/sessions.sqlite3") as snapshot:
                assert snapshot.execute("SELECT title FROM session_rows").fetchall() == [
                    ("before",)
                ]

            writer.execute("INSERT INTO session_rows (title) VALUES ('after')")
            writer.commit()

            with snapshots.connect_sqlite("runtime/sessions.sqlite3") as snapshot:
                assert snapshot.execute("SELECT title FROM session_rows").fetchall() == [
                    ("before",)
                ]
    finally:
        writer.close()


def test_manifest_digest_is_independent_of_absolute_state_root(tmp_path: Path) -> None:
    first = tmp_path / "first-state"
    second = tmp_path / "second-state"
    for root in (first, second):
        runtime = root / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "projects.json").write_text('{"items": []}', encoding="utf-8")

    first_manifest = capture_source_manifest(first)
    second_manifest = capture_source_manifest(second)

    assert first_manifest.state_root != second_manifest.state_root
    assert first_manifest.canonical_dict() == second_manifest.canonical_dict()
    assert first_manifest.digest == second_manifest.digest

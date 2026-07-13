"""Read-only legacy source manifest tests."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from ainrf.domain_control import DomainMaintenanceService
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


def test_source_manifest_excludes_cutover_seal_journal(state_root: Path) -> None:
    runtime = state_root / "runtime"
    (runtime / "projects.json").write_text('{"items": []}', encoding="utf-8")
    (runtime / "domain-legacy-source-seal.json").write_text('{"phase": "sealed"}', encoding="utf-8")

    manifest = capture_source_manifest(state_root)

    assert {item.relative_path for item in manifest.files} == {"runtime/projects.json"}


def test_source_manifest_excludes_non_domain_runtime_state(state_root: Path) -> None:
    """The import manifest and cutover seal cover the same legacy domain set."""

    runtime = state_root / "runtime"
    (runtime / "projects.json").write_text('{"items": []}', encoding="utf-8")
    (runtime / "skill_registries.json").write_text('{"skills": []}', encoding="utf-8")
    with sqlite3.connect(runtime / "literature.sqlite3") as conn:
        conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY)")

    legacy_checkpoint = state_root / "session-states" / "task-legacy" / "checkpoint.json"
    legacy_checkpoint.parent.mkdir()
    legacy_checkpoint.write_text('{"checkpoint": "legacy"}', encoding="utf-8")
    v2_checkpoint = state_root / "session-states" / "attempt-v2" / "checkpoint.json"
    v2_checkpoint.parent.mkdir()
    v2_checkpoint.write_text('{"checkpoint": "v2"}', encoding="utf-8")

    manifest = capture_source_manifest(state_root)

    paths = {item.relative_path for item in manifest.files}
    assert {
        "runtime/projects.json",
        "session-states/task-legacy/checkpoint.json",
    } <= paths
    assert "runtime/skill_registries.json" not in paths
    assert "runtime/literature.sqlite3" not in paths
    assert "session-states/attempt-v2/checkpoint.json" not in paths


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


def test_source_snapshot_rejects_a_symlinked_json_source_inside_state_root(
    state_root: Path,
) -> None:
    runtime = state_root / "runtime"
    target = runtime / "projects-source.json"
    target.write_text('{"items": []}', encoding="utf-8")
    source = runtime / "projects.json"
    source.symlink_to(target)

    with pytest.raises(
        SourceStaleError, match=r"source cannot be a symlink: runtime/projects\.json"
    ):
        capture_source_manifest(state_root)


def test_source_snapshot_rejects_a_sqlite_symlink_that_escapes_state_root(
    state_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-sessions.sqlite3"
    with sqlite3.connect(outside) as conn:
        conn.execute("CREATE TABLE session_rows (id INTEGER PRIMARY KEY)")

    source = state_root / "runtime" / "sessions.sqlite3"
    source.symlink_to(outside)

    with pytest.raises(
        SourceStaleError, match=r"source escaped state root: runtime/sessions\.sqlite3"
    ):
        capture_source_manifest(state_root)


def test_source_snapshot_rejects_a_json_source_through_an_escaping_parent_symlink(
    state_root: Path, tmp_path: Path
) -> None:
    outside_runtime = tmp_path / "outside-runtime"
    outside_runtime.mkdir()
    (outside_runtime / "projects.json").write_text('{"items": []}', encoding="utf-8")

    runtime = state_root / "runtime"
    runtime.rmdir()
    runtime.symlink_to(outside_runtime, target_is_directory=True)

    with pytest.raises(
        SourceStaleError, match=r"source escaped state root: runtime/projects\.json"
    ):
        capture_source_manifest(state_root)


def test_maintenance_source_fingerprint_retains_inode_mtime_size_and_hash(
    state_root: Path,
) -> None:
    source = state_root / "runtime" / "projects.json"
    payload = b'{"items": []}'
    source.write_bytes(payload)
    initial_stat = source.stat()

    service = DomainMaintenanceService(state_root)
    initial = service._source_fingerprints()["runtime/projects.json"]

    assert initial == (
        initial_stat.st_ino,
        initial_stat.st_mtime_ns,
        initial_stat.st_size,
        hashlib.sha256(payload).hexdigest(),
    )

    replacement = state_root / "runtime" / "replacement.json"
    replacement.write_bytes(payload)
    os.utime(replacement, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns))
    replacement.replace(source)

    replaced = service._source_fingerprints()["runtime/projects.json"]
    assert replaced[0] != initial[0]
    assert replaced[1:] == initial[1:]


def test_maintenance_source_fingerprint_uses_physical_sqlite_source_size(
    state_root: Path,
) -> None:
    service = DomainMaintenanceService(state_root)
    service.initialize()
    database = state_root / "runtime" / "agentic_researcher.sqlite3"

    fingerprint = service._source_fingerprints()["runtime/agentic_researcher.sqlite3"]

    assert fingerprint[2] == database.stat().st_size


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

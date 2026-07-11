"""Read-only legacy source manifest tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainrf.domain_migration import capture_source_manifest

pytestmark = [pytest.mark.unit]


def test_capture_source_manifest_is_source_read_only(state_root: Path) -> None:
    runtime = state_root / "runtime"
    projects = runtime / "projects.json"
    projects.write_text('{"project-a": {}}', encoding="utf-8")
    database = runtime / "sessions.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE session_rows (id INTEGER PRIMARY KEY)")

    before = (projects.stat().st_mtime_ns, database.stat().st_mtime_ns)
    manifest = capture_source_manifest(state_root)
    after = (projects.stat().st_mtime_ns, database.stat().st_mtime_ns)

    assert before == after
    assert {item.relative_path for item in manifest.files} == {
        "runtime/projects.json",
        "runtime/sessions.sqlite3",
    }
    assert all(item.sha256 for item in manifest.files)

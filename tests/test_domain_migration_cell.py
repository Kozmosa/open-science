"""Synthetic legacy fixture and isolated migration-cell tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.domain_migration import capture_source_manifest

pytestmark = [pytest.mark.unit]


def test_fixture_matrix_has_isolated_runtime_inputs() -> None:
    fixture_root = Path(__file__).parents[1] / "testing" / "domain_migration" / "fixtures"
    expected = {
        "normal",
        "empty",
        "missing-fields",
        "duplicate-path",
        "owner-anomaly",
        "unmapped-session",
    }
    assert expected <= {path.name for path in fixture_root.iterdir() if path.is_dir()}
    for name in expected:
        runtime = fixture_root / name / "runtime"
        assert runtime.is_dir()
        manifest = capture_source_manifest(fixture_root / name)
        assert manifest.state_root.endswith(name)


def test_dry_run_fixture_reads_without_writing(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    source = runtime / "projects.json"
    source.write_text(json.dumps({"items": []}), encoding="utf-8")
    before = source.read_bytes()
    capture_source_manifest(tmp_path)
    assert source.read_bytes() == before

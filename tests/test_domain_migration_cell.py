"""Synthetic legacy fixture and isolated migration-cell recovery tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.backup import BackupService
from ainrf.domain_migration import (
    DomainImporter,
    DomainReconciliationService,
    MigrationInterruptedError,
    capture_source_manifest,
)

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


def test_isolated_cell_recovers_importer_and_reconciles_after_staged_restore(
    tmp_path: Path,
) -> None:
    """Exercise the B2 recovery sequence against a disposable legacy state.

    This is deliberately stronger than the shell dry-run helper: the test
    creates a real backup, interrupts after a committed importer record,
    reconstructs the importer as if the process restarted, restores the
    original legacy snapshot into a new generation, and runs reconciliation
    again.  It remains a deterministic L0 proof; the matching Docker L2 cell
    uses the same scenario names and is intentionally separately authorized.
    """

    state_root = tmp_path / "legacy-state"
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True)
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="cell-user", display_name="Cell user", password="safe-password")
    workspace_path = state_root / "synthetic-workspace"
    workspace_path.mkdir()
    projects_source = runtime / "projects.json"
    workspaces_source = runtime / "workspaces.json"
    projects_source.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "project_id": "cell-project",
                        "name": "Cell project",
                        "owner_user_id": user.id,
                        "is_default": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    workspaces_source.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "workspace_id": "cell-workspace",
                        "project_id": "cell-project",
                        "owner_user_id": user.id,
                        "default_workdir": str(workspace_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source_before = {
        projects_source: projects_source.read_bytes(),
        workspaces_source: workspaces_source.read_bytes(),
    }
    artifact_sha = "c" * 64
    archive = BackupService(state_root).create_backup(tmp_path / "cell-backup.tar.gz")
    manifest = BackupService(state_root).verify_backup(archive)
    assert manifest.version >= 3

    interrupted_importer = DomainImporter(state_root)
    with pytest.raises(MigrationInterruptedError) as raised:
        interrupted_importer.run(
            mode="validate",
            artifact_sha=artifact_sha,
            interrupt_after_records=1,
        )
    run_id = raised.value.run_id
    interrupted = interrupted_importer.inspect(run_id)
    assert interrupted.status == "interrupted"
    assert interrupted.checkpoint

    # A fresh repository object is the process-restart boundary: it reads only
    # the durable run/checkpoint rows written before the injected interruption.
    restarted_importer = DomainImporter(state_root)
    completed = restarted_importer.resume(run_id, artifact_sha=artifact_sha)
    assert completed.status == "completed"
    results = tuple(restarted_importer.record_results(run_id))
    assert {(item.record_type, item.source_record_id) for item in results} >= {
        ("project", "cell-project"),
        ("workspace", "cell-workspace"),
    }
    reconciliation = DomainReconciliationService(state_root).reconcile(run_id)
    assert reconciliation.run_id == run_id
    assert projects_source.read_bytes() == source_before[projects_source]
    assert workspaces_source.read_bytes() == source_before[workspaces_source]

    staged_root = tmp_path / "restored-generation"
    restored_root = BackupService(state_root).restore_backup(
        archive,
        target_state_root=staged_root,
        skip_pre_backup=True,
    )
    assert restored_root == staged_root
    restored_importer = DomainImporter(staged_root)
    restored = restored_importer.run(mode="validate", artifact_sha=artifact_sha)
    assert restored.status == "completed"
    restored_reconciliation = DomainReconciliationService(staged_root).reconcile(restored.run_id)
    assert restored_reconciliation.run_id == restored.run_id

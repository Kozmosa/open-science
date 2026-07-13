"""Deterministic committed-cutover setup for v2 API contract tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from ainrf.backup import BackupService
from ainrf.db import connect
from ainrf.domain_control import (
    DomainCutoverController,
    DomainMaintenanceService,
    backup_manifest_sha256,
)
from ainrf.domain_migration import DomainImporter, DomainReconciliationService


V2_ARTIFACT_SHA = "b" * 64
_NOW = "2026-07-12T00:00:00+00:00"


def prepare_committed_v2_cutover(state_root: Path, tmp_path: Path) -> None:
    """Create the exact immutable evidence a v2 API process must validate.

    API tests must not flip the constraint flags directly: v2 startup now
    validates a completed import, verified backup, reconciliation result,
    maintenance epoch, artifact digest, and legacy-source inventory together.
    This helper mirrors the controller's real prepare/commit path while using
    only pytest-owned state and backup artifacts.
    """

    controller = DomainCutoverController(state_root)
    run = DomainImporter(state_root).run(artifact_sha=V2_ARTIFACT_SHA)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES ('project-ready', 'owner-ready', 'Ready project', 'active', 1, ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.commit()

    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="test-cutover-operator", reason="prepare v2 API fixture")
    try:
        controller.finalize_constraints(
            actor_id="test-cutover-operator",
            run_id=run.run_id,
            stability_window_seconds=0,
        )
        archive = BackupService(state_root).create_backup(tmp_path / "v2-cutover-backup.tar.gz")
        manifest = BackupService(state_root).verify_backup(archive)
        DomainReconciliationService(state_root).finalize_run(
            run.run_id,
            "test-cutover-operator",
            V2_ARTIFACT_SHA,
            {
                "manifest_sha256": backup_manifest_sha256(manifest),
                "validated_at": _NOW,
                "status": "valid",
            },
        )

        with closing(connect(db_path)) as conn:
            schema_row = conn.execute(
                "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
            ).fetchone()
        assert schema_row is not None
        schema_version = int(schema_row[0])

        controller.prepare(
            actor_id="test-cutover-operator",
            run_id=run.run_id,
            backup_archive=archive,
            artifact_sha=V2_ARTIFACT_SHA,
            artifact_contract_min=2,
            artifact_contract_max=2,
            artifact_schema_min=schema_version,
            artifact_schema_max=schema_version,
            stability_window_seconds=0,
        )
        controller.commit(
            actor_id="test-cutover-operator",
            run_id=run.run_id,
            backup_archive=archive,
            artifact_sha=V2_ARTIFACT_SHA,
            artifact_contract_min=2,
            artifact_contract_max=2,
            artifact_schema_min=schema_version,
            artifact_schema_max=schema_version,
            stability_window_seconds=0,
        )
    finally:
        maintenance.exit(actor_id="test-cutover-operator")

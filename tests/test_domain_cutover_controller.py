"""Focused domain cutover controller and legacy-source guard tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.backup import BackupService
from ainrf.db import connect
from ainrf.domain_control import (
    CutoverPreconditionError,
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    LegacySourceGuard,
    LegacySourceDriftError,
    backup_manifest_sha256,
)
from ainrf.domain_migration import DomainImporter, DomainReconciliationService

pytestmark = [pytest.mark.unit]

_ARTIFACT_SHA = "a" * 64
_NOW = "2026-07-12T00:00:00+00:00"


def _schema_version(state_root: Path) -> int:
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        row = conn.execute(
            "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
        ).fetchone()
    assert row is not None
    return int(row[0])


def _ready_cutover(
    state_root: Path, tmp_path: Path
) -> tuple[DomainCutoverController, str, Path, int]:
    """Create finalized migration and matching verified backup evidence."""

    controller = DomainCutoverController(state_root)
    run = DomainImporter(state_root).run(artifact_sha=_ARTIFACT_SHA)
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
        conn.execute("UPDATE domain_cutover_state SET constraints_ready = 1 WHERE singleton = 1")
        conn.commit()

    archive = BackupService(state_root).create_backup(tmp_path / "cutover-backup.tar.gz")
    manifest = BackupService(state_root).verify_backup(archive)
    DomainReconciliationService(state_root).finalize_run(
        run.run_id,
        "operator-finalize",
        _ARTIFACT_SHA,
        {
            "manifest_sha256": backup_manifest_sha256(manifest),
            "validated_at": _NOW,
            "status": "valid",
        },
    )
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator-cutover", reason="test cutover")
    return controller, run.run_id, archive, _schema_version(state_root)


def _prepare(
    controller: DomainCutoverController, run_id: str, archive: Path, schema_version: int
) -> None:
    result = controller.prepare(
        actor_id="operator-cutover",
        run_id=run_id,
        backup_archive=archive,
        artifact_sha=_ARTIFACT_SHA,
        artifact_contract_min=2,
        artifact_contract_max=2,
        artifact_schema_min=schema_version,
        artifact_schema_max=schema_version,
        stability_window_seconds=0,
    )
    assert result.state == "prepared"
    assert result.first_v2_write_at is None


def _commit(
    controller: DomainCutoverController, run_id: str, archive: Path, schema_version: int
) -> None:
    result = controller.commit(
        actor_id="operator-cutover",
        run_id=run_id,
        backup_archive=archive,
        artifact_sha=_ARTIFACT_SHA,
        artifact_contract_min=2,
        artifact_contract_max=2,
        artifact_schema_min=schema_version,
        artifact_schema_max=schema_version,
        stability_window_seconds=0,
    )
    assert result.state == "v2"
    assert result.cutover_ready


def test_prepare_commit_binds_evidence_and_fences_first_v2_write(
    state_root: Path, tmp_path: Path
) -> None:
    controller, run_id, archive, schema_version = _ready_cutover(state_root, tmp_path)

    _prepare(controller, run_id, archive, schema_version)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        with pytest.raises(
            sqlite3.IntegrityError, match="prepared domain cutover evidence is immutable"
        ):
            conn.execute(
                "UPDATE domain_cutover_state SET artifact_sha = ? WHERE singleton = 1",
                ("b" * 64,),
            )
    _commit(controller, run_id, archive, schema_version)

    with closing(connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        pending = controller.record_first_v2_write_in_transaction(
            conn, actor_id="task-owner", artifact_sha=_ARTIFACT_SHA
        )
        assert pending.first_v2_write_actor_id == "task-owner"
        conn.rollback()
    assert controller.status().first_v2_write_at is None

    with closing(connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        recorded = controller.record_first_v2_write_in_transaction(
            conn, actor_id="task-owner", artifact_sha=_ARTIFACT_SHA
        )
        conn.commit()
    assert recorded.first_v2_write_actor_id == "task-owner"
    assert controller.status().first_v2_write_at is not None

    with closing(connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="committed state is immutable"):
            conn.execute("UPDATE domain_cutover_state SET cutover_ready = 0 WHERE singleton = 1")
    with pytest.raises(DomainCutoverError, match="cannot be aborted"):
        controller.abort(actor_id="operator-cutover", reason="too late")


def test_commit_source_drift_automatically_aborts_prepared_cutover(
    state_root: Path, tmp_path: Path
) -> None:
    projects_json = state_root / "runtime" / "projects.json"
    projects_json.write_text('{"items": []}\n', encoding="utf-8")
    controller, run_id, archive, schema_version = _ready_cutover(state_root, tmp_path)
    _prepare(controller, run_id, archive, schema_version)

    projects_json.write_text('{"items": [{"project_id": "changed"}]}\n', encoding="utf-8")
    with pytest.raises(CutoverPreconditionError, match="cutover-ready|inventory"):
        _commit(controller, run_id, archive, schema_version)

    status = controller.status()
    assert status.state == "legacy"
    assert not status.cutover_ready


def test_legacy_source_guard_excludes_control_plane_database(state_root: Path) -> None:
    DomainCutoverController(state_root)
    sessions_db = state_root / "runtime" / "sessions.sqlite3"
    with closing(sqlite3.connect(sessions_db)) as conn:
        conn.execute("CREATE TABLE legacy_sessions (session_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO legacy_sessions VALUES ('session-1')")
        conn.commit()
    projects_json = state_root / "runtime" / "projects.json"
    projects_json.write_text('{"items": []}\n', encoding="utf-8")
    legacy_session_state = state_root / "session-states" / "legacy.json"
    legacy_session_state.write_text('{"session_id": "session-1"}\n', encoding="utf-8")
    legacy_checkpoint = state_root / "session-states" / "task-legacy" / "checkpoint.json"
    legacy_checkpoint.parent.mkdir()
    legacy_checkpoint.write_text('{"checkpoint": "legacy"}\n', encoding="utf-8")

    skill_registry = state_root / "runtime" / "skill_registries.json"
    skill_registry.write_text('{"skills": []}\n', encoding="utf-8")
    v2_checkpoint = state_root / "session-states" / "attempt-v2" / "checkpoint.json"
    v2_checkpoint.parent.mkdir()
    v2_checkpoint.write_text('{"checkpoint": "v2"}\n', encoding="utf-8")

    guard = LegacySourceGuard(state_root)
    inventory = guard.capture()
    paths = {item.relative_path for item in inventory.files}
    assert "runtime/agentic_researcher.sqlite3" not in paths
    assert inventory.excluded_paths == ("runtime/agentic_researcher.sqlite3",)
    assert {
        "runtime/projects.json",
        "runtime/sessions.sqlite3",
        "session-states/legacy.json",
        "session-states/task-legacy/checkpoint.json",
    } <= paths
    assert "runtime/skill_registries.json" not in paths
    assert "session-states/attempt-v2/checkpoint.json" not in paths

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute("CREATE TABLE cutover_guard_test (id TEXT PRIMARY KEY)")
        conn.commit()
    guard.verify(inventory)

    skill_registry.write_text('{"skills": ["changed"]}\n', encoding="utf-8")
    v2_checkpoint.write_text('{"checkpoint": "changed"}\n', encoding="utf-8")
    guard.verify(inventory)

    projects_json.write_text('{"items": ["changed"]}\n', encoding="utf-8")
    with pytest.raises(LegacySourceDriftError):
        guard.verify(inventory)

    updated_inventory = guard.capture()
    legacy_checkpoint.write_text('{"checkpoint": "changed"}\n', encoding="utf-8")
    with pytest.raises(LegacySourceDriftError):
        guard.verify(updated_inventory)

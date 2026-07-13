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
from ainrf.domain.write_fence import DomainWriteFence
from ainrf.domain_migration import DomainImporter, DomainReconciliationService
from ainrf.projects import ProjectRegistryService

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
        conn.commit()

    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator-cutover", reason="test cutover")
    controller.finalize_constraints(
        actor_id="operator-cutover",
        run_id=run.run_id,
        stability_window_seconds=0,
    )
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


def test_constraint_finalizer_requires_maintenance_and_installs_task_guard(
    state_root: Path,
) -> None:
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
        conn.commit()

    with pytest.raises(CutoverPreconditionError, match="maintenance preflight failed"):
        controller.finalize_constraints(
            actor_id="operator-cutover",
            run_id=run.run_id,
            stability_window_seconds=0,
        )

    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator-cutover", reason="install final Task guard")
    try:
        finalized = controller.finalize_constraints(
            actor_id="operator-cutover",
            run_id=run.run_id,
            stability_window_seconds=0,
        )
        assert finalized.cutover_allowed
        assert len(finalized.guard_digest) == 64
        with closing(connect(db_path)) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="derived environment"):
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, workspace_id, environment_id, researcher_type,
                        harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
                    ) VALUES (
                        'task-invalid', 'project-ready', 'workspace-missing', 'environment-missing',
                        'vanilla', 'claude-code', 'queued', 'Invalid', 'No workspace', ?, ?, 'owner-ready'
                    )
                    """,
                    (_NOW, _NOW),
                )
            audit = conn.execute(
                """
                SELECT metadata_json FROM domain_audit_events
                WHERE event_type = 'domain_cutover.constraints_finalized'
                  AND subject_type = 'domain_constraints' AND subject_id = 'tasks'
                """
            ).fetchone()
        assert audit is not None
        assert finalized.guard_digest in str(audit["metadata_json"])
    finally:
        maintenance.exit(actor_id="operator-cutover")


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


def test_legacy_source_seal_covers_domain_json_and_is_reversible(state_root: Path) -> None:
    runtime = state_root / "runtime"
    source_paths = (
        runtime / "projects.json",
        runtime / "workspaces.json",
        runtime / "environments.json",
        runtime / "task_edges.json",
        runtime / "sessions.json",
    )
    for path in source_paths:
        path.write_text('{"items": []}\n', encoding="utf-8")
        path.chmod(0o640)
    checkpoint = state_root / "session-states" / "legacy-task" / "checkpoint.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text('{"session_id": "legacy"}\n', encoding="utf-8")
    checkpoint.chmod(0o600)

    guard = LegacySourceGuard(state_root)
    inventory = guard.capture()
    seal = guard.seal(inventory)

    assert seal.phase == "sealed"
    assert {item.relative_path for item in seal.files} == {
        item.relative_path for item in inventory.files
    }
    for item in seal.files:
        path = state_root / item.relative_path
        assert path.stat().st_mode & 0o222 == 0
    guard.verify_sealed(inventory)

    guard.unseal(inventory)
    assert not (runtime / "domain-legacy-source-seal.json").exists()
    assert (runtime / "projects.json").stat().st_mode & 0o7777 == 0o640
    assert checkpoint.stat().st_mode & 0o7777 == 0o600


def test_legacy_source_seal_inventories_and_seals_sessions_wal_sidecars(
    state_root: Path,
) -> None:
    sessions_db = state_root / "runtime" / "sessions.sqlite3"
    connection = sqlite3.connect(sessions_db)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE legacy_sessions (session_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO legacy_sessions VALUES ('session-1')")
        connection.commit()
        assert sessions_db.with_name("sessions.sqlite3-wal").is_file()
        assert sessions_db.with_name("sessions.sqlite3-shm").is_file()

        guard = LegacySourceGuard(state_root)
        inventory = guard.capture()
        paths = {item.relative_path for item in inventory.files}
        assert {
            "runtime/sessions.sqlite3",
            "runtime/sessions.sqlite3-wal",
            "runtime/sessions.sqlite3-shm",
        } <= paths

        guard.seal(inventory)
        guard.verify_sealed(inventory)
        for relative_path in paths:
            assert (state_root / relative_path).stat().st_mode & 0o222 == 0
        guard.unseal(inventory)
    finally:
        connection.close()


def test_legacy_project_registry_cannot_atomically_replace_a_sealed_json_source(
    state_root: Path,
) -> None:
    projects_json = state_root / "runtime" / "projects.json"
    projects_json.write_text(
        """{
  "items": [
    {
      "project_id": "project-existing",
      "name": "Existing",
      "description": null,
      "default_workspace_id": null,
      "default_environment_id": null,
      "created_at": "2026-07-12T00:00:00+00:00",
      "updated_at": "2026-07-12T00:00:00+00:00",
      "owner_user_id": "owner"
    }
  ]
}
""",
        encoding="utf-8",
    )
    guard = LegacySourceGuard(state_root)
    inventory = guard.capture()
    guard.seal(inventory)
    registry = ProjectRegistryService(state_root)
    registry.initialize()

    with pytest.raises(PermissionError, match="legacy source is sealed"):
        registry.create_project(name="Blocked", description=None, owner_user_id="owner")

    guard.unseal(inventory)


def test_committed_cutover_rejects_permission_tampering_on_legacy_sources(
    state_root: Path, tmp_path: Path
) -> None:
    projects_json = state_root / "runtime" / "projects.json"
    projects_json.write_text('{"items": []}\n', encoding="utf-8")
    controller, run_id, archive, schema_version = _ready_cutover(state_root, tmp_path)
    _prepare(controller, run_id, archive, schema_version)
    _commit(controller, run_id, archive, schema_version)

    seal_path = state_root / "runtime" / "domain-legacy-source-seal.json"
    assert seal_path.is_file()
    assert projects_json.stat().st_mode & 0o222 == 0
    controller.assert_v2_writable(artifact_sha=_ARTIFACT_SHA)

    projects_json.chmod(0o644)
    with pytest.raises(DomainCutoverError, match="legacy source monitor is not stable"):
        controller.assert_v2_writable(artifact_sha=_ARTIFACT_SHA)


def test_failed_precommit_seal_restores_modes_and_aborts_prepared_state(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_json = state_root / "runtime" / "projects.json"
    workspaces_json = state_root / "runtime" / "workspaces.json"
    projects_json.write_text('{"items": []}\n', encoding="utf-8")
    workspaces_json.write_text('{"items": []}\n', encoding="utf-8")
    projects_json.chmod(0o640)
    workspaces_json.chmod(0o640)
    controller, run_id, archive, schema_version = _ready_cutover(state_root, tmp_path)
    _prepare(controller, run_id, archive, schema_version)

    original_chmod = controller._legacy_sources._chmod
    calls = 0

    def fail_second_seal(relative_path: str, mode: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated chmod failure")
        original_chmod(relative_path, mode)

    monkeypatch.setattr(controller._legacy_sources, "_chmod", fail_second_seal)
    with pytest.raises(CutoverPreconditionError, match="legacy source seal failed"):
        _commit(controller, run_id, archive, schema_version)

    assert controller.status().state == "legacy"
    assert projects_json.stat().st_mode & 0o7777 == 0o640
    assert workspaces_json.stat().st_mode & 0o7777 == 0o640
    assert not (state_root / "runtime" / "domain-legacy-source-seal.json").exists()


def test_write_fence_rejects_direct_v2_writes_before_cutover(state_root: Path) -> None:
    fence = DomainWriteFence(state_root)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(DomainCutoverError, match="require a committed"):
            fence.record_first_v2_write(conn, actor_id="direct-writer")
        conn.rollback()

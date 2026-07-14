"""Crash-resume contracts for the durable domain importer."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
from pathlib import Path
import sqlite3
from typing import cast

import pytest

from ainrf.auth.service import AuthService
from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError
from ainrf.domain_migration import DomainImporter, MigrationInterruptedError

pytestmark = [pytest.mark.unit]

_ARTIFACT_SHA = "a" * 64
_OTHER_ARTIFACT_SHA = "b" * 64


def _write_json(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"items": items}), encoding="utf-8")


def _legacy_sources(state_root: Path) -> set[tuple[str, str]]:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    workspace_path = state_root / "workspaces" / "active"
    workspace_path.mkdir(parents=True)
    retired_workspace_path = state_root / "workspaces" / "retired"
    retired_workspace_path.mkdir(parents=True)
    runtime = state_root / "runtime"
    _write_json(
        runtime / "projects.json",
        [
            {"project_id": "project-active", "name": "Active", "owner_user_id": user.id},
            {
                "project_id": "project-unmapped",
                "name": "Unmapped",
                "owner_user_id": "retired-user",
            },
        ],
    )
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "workspace-active",
                "project_id": "project-active",
                "owner_user_id": user.id,
                "default_workdir": str(workspace_path),
            },
            {
                "workspace_id": "workspace-unmapped",
                "project_id": "project-unmapped",
                "owner_user_id": "retired-user",
                "default_workdir": str(retired_workspace_path),
            },
        ],
    )
    return {
        ("project", "project-active"),
        ("project", "project-unmapped"),
        ("workspace", "workspace-active"),
        ("workspace", "workspace-unmapped"),
    }


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return mapping[name]
    missing = object()
    result = getattr(value, name, missing)
    if result is missing:
        raise AssertionError(f"Expected {name!r} on migration inspection/result")
    return result


def _interrupted_run(importer: DomainImporter, *, after_records: int) -> str:
    with pytest.raises(MigrationInterruptedError) as raised:
        importer.run(
            mode="validate",
            artifact_sha=_ARTIFACT_SHA,
            interrupt_after_records=after_records,
        )
    run_id = raised.value.run_id
    assert isinstance(run_id, str)
    assert run_id
    return run_id


def test_interrupted_import_persists_checkpoint_and_resumes_once_per_source_record(
    state_root: Path,
) -> None:
    expected_sources = _legacy_sources(state_root)
    importer = DomainImporter(state_root)
    run_id = _interrupted_run(importer, after_records=2)

    interrupted = importer.inspect(run_id)
    assert _field(interrupted, "status") == "interrupted"
    assert _field(interrupted, "artifact_sha") == _ARTIFACT_SHA
    assert isinstance(_field(interrupted, "phase"), str)
    checkpoint = _field(interrupted, "checkpoint")
    assert isinstance(checkpoint, Mapping)
    assert checkpoint
    manifest_digest = _field(interrupted, "source_manifest_sha256")
    assert isinstance(manifest_digest, str)
    assert len(manifest_digest) == 64
    heartbeat = _field(interrupted, "heartbeat_at")
    assert isinstance(heartbeat, str)
    assert heartbeat

    partial_results = tuple(importer.record_results(run_id))
    assert len(partial_results) == 2
    assert (
        len(
            {
                (str(_field(result, "record_type")), str(_field(result, "source_record_id")))
                for result in partial_results
            }
        )
        == 2
    )

    completed = importer.resume(run_id, artifact_sha=_ARTIFACT_SHA)
    assert _field(completed, "run_id") == run_id
    assert _field(completed, "status") == "completed"

    results = tuple(importer.record_results(run_id))
    identities = Counter(
        (str(_field(result, "record_type")), str(_field(result, "source_record_id")))
        for result in results
    )
    assert identities == Counter({source: 1 for source in expected_sources})
    statuses = {
        (str(_field(result, "record_type")), str(_field(result, "source_record_id"))): str(
            _field(result, "status")
        )
        for result in results
    }
    assert statuses == {
        ("project", "project-active"): "imported",
        ("workspace", "workspace-active"): "imported",
        ("project", "project-unmapped"): "attention_needed",
        ("workspace", "workspace-unmapped"): "attention_needed",
    }

    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with sqlite3.connect(db_path) as conn:
        legacy_rows = {
            (str(record_type), str(source_record_id))
            for record_type, source_record_id in conn.execute(
                """
                SELECT record_type, source_record_id
                FROM legacy_domain_records
                WHERE run_id = ?
                """,
                (run_id,),
            )
        }
    assert legacy_rows == {
        ("project", "project-unmapped"),
        ("workspace", "workspace-unmapped"),
    }


def test_resume_rejects_a_different_artifact_without_losing_persisted_progress(
    state_root: Path,
) -> None:
    _legacy_sources(state_root)
    importer = DomainImporter(state_root)
    run_id = _interrupted_run(importer, after_records=1)
    persisted_results = tuple(importer.record_results(run_id))

    with pytest.raises(ValueError, match="artifact"):
        importer.resume(run_id, artifact_sha=_OTHER_ARTIFACT_SHA)

    inspection = importer.inspect(run_id)
    assert _field(inspection, "status") == "interrupted"
    assert _field(inspection, "artifact_sha") == _ARTIFACT_SHA
    assert tuple(importer.record_results(run_id)) == persisted_results


def test_importer_refuses_to_start_a_write_run_during_maintenance(state_root: Path) -> None:
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="migration cutover")

    try:
        with pytest.raises(MaintenanceModeError, match="paused for maintenance"):
            DomainImporter(state_root).run(mode="apply", artifact_sha=_ARTIFACT_SHA)
    finally:
        maintenance.exit(actor_id="operator")

    participants = DomainMaintenanceService(state_root).participants()
    assert any(
        participant.participant_type == "admin-cli" and participant.status == "stopped"
        for participant in participants
    )


def test_importer_stops_at_the_maintenance_epoch_and_resumes_from_its_checkpoint(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _legacy_sources(state_root)
    maintenance = DomainMaintenanceService(state_root)
    importer = DomainImporter(state_root)
    original_enter_phase = importer._enter_phase
    entered = False

    def enter_maintenance_before_first_phase(
        conn: sqlite3.Connection,
        run_id: str,
        phase: str,
    ) -> None:
        nonlocal entered
        if not entered:
            entered = True
            maintenance.enter(actor_id="operator", reason="pause importer")
        original_enter_phase(conn, run_id, phase)

    monkeypatch.setattr(importer, "_enter_phase", enter_maintenance_before_first_phase)
    with pytest.raises(MaintenanceModeError, match="crossed a maintenance epoch"):
        importer.run(mode="apply", artifact_sha=_ARTIFACT_SHA)

    with sqlite3.connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        run = conn.execute(
            "SELECT run_id, status FROM domain_migration_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        imported_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
    assert run is not None
    assert run[1] == "running"
    assert imported_projects == (0,)

    maintenance.exit(actor_id="operator")
    resumed = DomainImporter(state_root).resume(str(run[0]), artifact_sha=_ARTIFACT_SHA)

    assert resumed.status == "completed"

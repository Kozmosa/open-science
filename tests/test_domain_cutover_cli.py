"""CLI contract tests for the durable domain cutover controller."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ainrf.cli import app
from ainrf.domain_control import CUTOVER_REQUIRED_PARTICIPANT_TYPES, DomainMaintenanceService
from ainrf.cli import _admin_cli_participant

pytestmark = [pytest.mark.cli]

runner = CliRunner()


class _Result:
    def __init__(self, state: str) -> None:
        self._state = state

    def as_dict(self) -> dict[str, object]:
        return {"state": self._state}


def test_domain_cutover_help_lists_controller_operations() -> None:
    result = runner.invoke(app, ["domain-cutover", "--help"])

    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "prepare" in result.stdout
    assert "commit" in result.stdout
    assert "abort" in result.stdout


def test_domain_cutover_prepare_passes_exact_bound_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    controller_config: dict[str, object] = {}

    class FakeController:
        def prepare(self, **kwargs: object) -> _Result:
            captured.update(kwargs)
            return _Result("prepared")

    def fake_controller(
        state_root: Path,
        *,
        workspace_root: Path | None = None,
        tenant_root: Path | None = None,
    ) -> FakeController:
        controller_config.update(
            {
                "state_root": state_root,
                "workspace_root": workspace_root,
                "tenant_root": tenant_root,
            }
        )
        return FakeController()

    monkeypatch.setattr("ainrf.cli._cutover_controller", fake_controller)
    archive = tmp_path / "backup.tar.gz"
    state_root = tmp_path / "state"
    workspace_root = tmp_path / "selected-workspaces"
    tenant_root = tmp_path / "selected-tenants"
    workspace_root.mkdir()
    tenant_root.mkdir()
    result = runner.invoke(
        app,
        [
            "domain-cutover",
            "prepare",
            "run-1",
            str(archive),
            "--actor-id",
            "operator-1",
            "--artifact-sha",
            "a" * 64,
            "--artifact-contract-min",
            "2",
            "--artifact-contract-max",
            "2",
            "--artifact-schema-min",
            "18",
            "--artifact-schema-max",
            "18",
            "--stability-window-seconds",
            "0",
            "--workspace-root",
            str(workspace_root),
            "--tenant-root",
            str(tenant_root),
            "--state-root",
            str(state_root),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"state": "prepared"}
    participant_id = captured.pop("maintenance_participant_id")
    assert isinstance(participant_id, str) and participant_id
    assert captured == {
        "actor_id": "operator-1",
        "run_id": "run-1",
        "backup_archive": archive,
        "artifact_sha": "a" * 64,
        "artifact_contract_min": 2,
        "artifact_contract_max": 2,
        "artifact_schema_min": 18,
        "artifact_schema_max": 18,
        "stability_window_seconds": 0.0,
    }
    assert controller_config == {
        "state_root": state_root,
        "workspace_root": workspace_root,
        "tenant_root": tenant_root,
    }
    participants = DomainMaintenanceService(state_root).participants()
    assert any(
        participant.participant_type == "admin-cli" and participant.status == "stopped"
        for participant in participants
    )


def test_admin_cli_participant_is_drained_when_maintenance_is_active(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    maintenance = DomainMaintenanceService(state_root)
    for participant_type in CUTOVER_REQUIRED_PARTICIPANT_TYPES:
        maintenance.register_participant(f"fixture:{participant_type}", participant_type)
    maintenance.enter(actor_id="operator", reason="CLI preflight")
    for participant in maintenance.participants():
        maintenance.drain_participant(participant.participant_id)

    participant = _admin_cli_participant(state_root, "domain-maintenance.preflight")
    try:
        report = maintenance.preflight(stability_window_seconds=0)
    finally:
        participant.stop()

    assert report.ready


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "domain-migration",
            "resolve",
            "run-1",
            "issue-1",
            "--resolution-type",
            "assign_project_owner",
            "--actor-id",
            "operator",
            "--payload",
            "{}",
        ],
        [
            "domain-migration",
            "finalize",
            "run-1",
            "--actor-id",
            "operator",
            "--artifact-sha",
            "a" * 64,
            "--restore-evidence",
            "{}",
        ],
        ["domain-migration", "reconcile"],
    ],
)
def test_domain_migration_mutation_commands_refuse_maintenance_before_service_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: list[str],
) -> None:
    state_root = tmp_path / "state"
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="block CLI reconciliation writes")
    constructed = False

    class UnexpectedReconciliationService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            nonlocal constructed
            constructed = True

    monkeypatch.setattr("ainrf.cli.DomainReconciliationService", UnexpectedReconciliationService)
    try:
        result = runner.invoke(app, [*arguments, "--state-root", str(state_root)])
    finally:
        maintenance.exit(actor_id="operator")

    assert result.exit_code == 2
    assert "paused for maintenance" in result.output
    assert not constructed


def test_domain_runtime_resolution_is_registered_and_rejected_during_maintenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="block runtime reconciliation")
    constructed = False

    class UnexpectedTaskApplicationService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            nonlocal constructed
            constructed = True

    monkeypatch.setattr("ainrf.cli.TaskApplicationService", UnexpectedTaskApplicationService)
    try:
        result = runner.invoke(
            app,
            [
                "domain-runtime",
                "resolve-launch-unknown",
                "task-1",
                "attempt-1",
                "--actor-id",
                "operator",
                "--reason",
                "investigated",
                "--state-root",
                str(state_root),
            ],
        )
    finally:
        maintenance.exit(actor_id="operator")

    assert result.exit_code == 2
    assert "paused for maintenance" in result.output
    assert not constructed

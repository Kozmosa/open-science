"""Maintenance fencing for the durable Literature planner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ainrf.cli import app
from ainrf.domain_control import DomainMaintenanceService, DomainWriteParticipant
from ainrf.literature.planner import _run_planner_cycle, run_once
from ainrf.literature.tracking import LiteratureTrackingService

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_planner_cycle_drains_without_dispatching_after_epoch_changes(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LiteratureTrackingService(state_root)
    service.initialize()
    maintenance = DomainMaintenanceService(state_root)
    participant = DomainWriteParticipant(
        maintenance,
        "literature-planner",
        participant_id="literature-planner-maintenance-test",
    )
    participant.start()
    dispatched: list[bool] = []

    def enter_maintenance() -> None:
        maintenance.enter(actor_id="operator", reason="pause Literature planner cycle")

    def unexpected_dispatch(
        _service: LiteratureTrackingService,
        *,
        check_lease: object | None = None,
    ) -> int:
        _ = check_lease
        dispatched.append(True)
        return 0

    monkeypatch.setattr(service, "plan_daily_check", enter_maintenance)
    monkeypatch.setattr("ainrf.literature.planner.dispatch_outbox", unexpected_dispatch)
    try:
        assert _run_planner_cycle(service, participant, plan_daily_check=True) == 0
    finally:
        maintenance.exit(actor_id="operator")
        participant.stop()

    assert dispatched == []
    status = next(
        item
        for item in maintenance.participants()
        if item.participant_id == participant.participant_id
    )
    assert status.in_flight_mutations == 0


def test_planner_outbox_does_not_mark_a_message_published_after_maintenance_starts(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broker handoff must not be followed by an unfenced outbox update."""

    service = LiteratureTrackingService(state_root)
    service.initialize()
    topic = service.create_topic(
        user_id="owner",
        label="Planner maintenance boundary",
        include_terms=[],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    service.create_check(user_id="owner", topic_ids=[str(topic["topic_id"])])
    work_item_id = service.pending_outbox_work_ids()[0]
    maintenance = DomainMaintenanceService(state_root)
    participant = DomainWriteParticipant(
        maintenance,
        "literature-planner",
        participant_id="literature-planner-outbox-boundary-test",
    )
    participant.start()

    def enter_maintenance_after_broker_handoff(*_args: object, **_kwargs: object) -> None:
        maintenance.enter(actor_id="operator", reason="pause Literature outbox commit")

    monkeypatch.setattr(
        "ainrf.literature.tasks.process_work_item.send",
        enter_maintenance_after_broker_handoff,
    )
    try:
        assert _run_planner_cycle(service, participant, plan_daily_check=False) == 0
    finally:
        maintenance.exit(actor_id="operator")
        participant.stop()

    with service._connect() as conn:
        outbox = conn.execute(
            "SELECT status, publish_attempts FROM literature_outbox WHERE work_item_id = ?",
            (work_item_id,),
        ).fetchone()
    assert outbox is not None
    assert (outbox["status"], outbox["publish_attempts"]) == ("pending", 0)


def test_one_shot_planner_does_not_initialize_literature_state_during_maintenance(
    state_root: Path,
) -> None:
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="pause one-shot Literature planner")
    service = LiteratureTrackingService(state_root)
    try:
        assert run_once(service) == 0
    finally:
        maintenance.exit(actor_id="operator")

    assert not (state_root / "runtime" / "literature.sqlite3").exists()


def test_one_shot_planner_cli_uses_the_maintenance_fenced_path(state_root: Path) -> None:
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="pause CLI Literature planner")
    try:
        result = runner.invoke(
            app,
            ["literature-planner", "--once", "--state-root", str(state_root)],
        )
    finally:
        maintenance.exit(actor_id="operator")

    assert result.exit_code == 0
    assert not (state_root / "runtime" / "literature.sqlite3").exists()

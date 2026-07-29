"""Literature planning inside the authoritative domain-worker lease."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain_control import MaintenanceModeError
from ainrf.literature.planner import run_planner_cycle
from ainrf.literature.tracking import LiteratureTrackingService

pytestmark = [pytest.mark.unit]


def test_planner_cycle_stops_before_dispatch_when_lease_changes(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LiteratureTrackingService(state_root)
    checks = 0
    dispatched: list[bool] = []

    def check_lease() -> None:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise MaintenanceModeError("maintenance epoch changed")

    monkeypatch.setattr(service, "plan_daily_check", lambda: None)
    monkeypatch.setattr(
        "ainrf.literature.planner.dispatch_outbox",
        lambda *_args, **_kwargs: dispatched.append(True) or 0,
    )

    with pytest.raises(MaintenanceModeError, match="epoch changed"):
        run_planner_cycle(service, check_lease=check_lease)

    assert dispatched == []


def test_planner_cycle_publishes_under_the_supplied_lease(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LiteratureTrackingService(state_root)
    checks: list[bool] = []
    monkeypatch.setattr(service, "plan_daily_check", lambda: None)
    monkeypatch.setattr(
        "ainrf.literature.planner.dispatch_outbox",
        lambda *_args, **_kwargs: 2,
    )

    result = run_planner_cycle(service, check_lease=lambda: checks.append(True))

    assert result == 2
    assert len(checks) == 4

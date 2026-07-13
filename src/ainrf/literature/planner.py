"""Durable outbox dispatcher and daily literature planner process."""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceModeError,
)
from ainrf.literature.tracking import LiteratureTrackingService


def dispatch_outbox(
    service: LiteratureTrackingService,
    *,
    check_lease: Callable[[], None] | None = None,
) -> int:
    """Publish pending work IDs after their SQLite transaction committed."""
    from ainrf.literature.tasks import process_work_item

    sent = 0
    for work_item_id in service.pending_outbox_work_ids():
        if check_lease is not None:
            check_lease()
        try:
            process_work_item.send(work_item_id)
        except Exception as exc:
            if check_lease is not None:
                check_lease()
            service.mark_outbox_failed(work_item_id, str(exc))
        else:
            if check_lease is not None:
                check_lease()
            service.mark_outbox_published(work_item_id)
            sent += 1
    return sent


def _run_planner_cycle(
    service: LiteratureTrackingService,
    participant: DomainWriteParticipant,
    *,
    plan_daily_check: bool,
) -> int:
    """Run one fenced planner/outbox cycle or drain without writing.

    A planner is deliberately leased per cycle rather than for the lifetime
    of its process.  That lets maintenance observe an idle planner as drained
    and prevents a new epoch from being crossed by a delayed outbox update.
    """

    state = participant.heartbeat()
    if state.status != "active":
        return 0
    try:
        lease = participant.begin_mutation(source="literature-planner.cycle")
    except MaintenanceModeError:
        participant.drain()
        return 0
    try:
        # Initializing the Literature schema can itself create SQLite state.
        # Keep that one-time path inside the same lease as planning and
        # outbox updates, so a fresh ``--once`` process cannot write while a
        # maintenance epoch is already active.
        participant.check_lease(lease)
        service.initialize()
        participant.check_lease(lease)
        if plan_daily_check:
            service.plan_daily_check()
            participant.check_lease(lease)
        sent = dispatch_outbox(
            service,
            check_lease=lambda: participant.check_lease(lease),
        )
        participant.check_lease(lease)
        return sent
    except MaintenanceModeError:
        participant.drain()
        return 0
    finally:
        participant.finish_mutation(lease)


def run_once(service: LiteratureTrackingService) -> int:
    """Run one maintenance-fenced Literature planner/outbox cycle."""

    participant = DomainWriteParticipant(
        DomainMaintenanceService(service.state_root),
        "literature-planner",
        details={"component": "literature-planner-once"},
    )
    participant.start()
    try:
        return _run_planner_cycle(service, participant, plan_daily_check=False)
    finally:
        participant.stop()


def run_forever(service: LiteratureTrackingService, interval_seconds: int = 30) -> None:
    """Run the planner while observing the shared domain maintenance epoch."""
    participant = DomainWriteParticipant(
        DomainMaintenanceService(service.state_root),
        "literature-planner",
        details={"component": "literature-planner"},
    )
    participant.start()
    try:
        while True:
            # arXiv publishes RSS at Eastern midnight.  Waiting ten minutes
            # avoids assuming a fixed UTC offset and naturally follows
            # daylight saving.
            eastern_now = datetime.now(ZoneInfo("America/New_York"))
            _run_planner_cycle(
                service,
                participant,
                plan_daily_check=eastern_now.hour == 0 and eastern_now.minute >= 10,
            )
            time.sleep(interval_seconds)
    finally:
        participant.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenScience literature planner")
    parser.add_argument("--state-root", default=os.getenv("AINRF_STATE_ROOT", ".ainrf"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    arguments = parser.parse_args()
    service = LiteratureTrackingService(Path(arguments.state_root))
    if arguments.once:
        run_once(service)
        return
    run_forever(service, arguments.interval_seconds)


if __name__ == "__main__":
    main()

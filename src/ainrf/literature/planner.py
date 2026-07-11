"""Durable outbox dispatcher and daily literature planner process."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ainrf.literature.tracking import LiteratureTrackingService


def dispatch_outbox(service: LiteratureTrackingService) -> int:
    """Publish pending work IDs after their SQLite transaction committed."""
    from ainrf.literature.tasks import process_work_item

    sent = 0
    for work_item_id in service.pending_outbox_work_ids():
        try:
            process_work_item.send(work_item_id)
        except Exception as exc:
            service.mark_outbox_failed(work_item_id, str(exc))
        else:
            service.mark_outbox_published(work_item_id)
            sent += 1
    return sent


def run_forever(service: LiteratureTrackingService, interval_seconds: int = 30) -> None:
    while True:
        # arXiv publishes RSS at Eastern midnight.  Waiting ten minutes avoids
        # assuming a fixed UTC offset and naturally follows daylight saving.
        eastern_now = datetime.now(ZoneInfo("America/New_York"))
        if eastern_now.hour == 0 and eastern_now.minute >= 10:
            service.plan_daily_check()
        dispatch_outbox(service)
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenScience literature planner")
    parser.add_argument("--state-root", default=os.getenv("AINRF_STATE_ROOT", ".ainrf"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    arguments = parser.parse_args()
    service = LiteratureTrackingService(Path(arguments.state_root))
    service.initialize()
    if arguments.once:
        dispatch_outbox(service)
        return
    run_forever(service, arguments.interval_seconds)


if __name__ == "__main__":
    main()

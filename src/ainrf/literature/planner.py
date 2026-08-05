"""Literature planning and outbox publication inside the domain-worker lease."""

from __future__ import annotations

from collections.abc import Callable

import structlog

from ainrf.literature.tracking import LiteratureTrackingService

logger = structlog.get_logger(__name__).bind(component="literature-planner")


def dispatch_outbox(
    service: LiteratureTrackingService,
    *,
    check_lease: Callable[[], None],
) -> int:
    """Publish pending work IDs while repeatedly checking the caller's lease."""

    from ainrf.literature.tasks import process_work_item

    sent = 0
    for work_item_id in service.pending_outbox_work_ids():
        check_lease()
        try:
            process_work_item.send(work_item_id)
        except Exception as exc:
            check_lease()
            service.mark_outbox_failed(work_item_id, str(exc))
            logger.error(
                "literature_work_item_publish_failed",
                work_item_id=work_item_id,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
        else:
            check_lease()
            service.mark_outbox_published(work_item_id)
            sent += 1
            logger.debug("literature_work_item_published", work_item_id=work_item_id)
    return sent


def run_planner_cycle(
    service: LiteratureTrackingService,
    *,
    check_lease: Callable[[], None],
) -> int:
    """Plan due checks and publish their outbox under a domain-worker lease."""

    check_lease()
    service.initialize()
    check_lease()
    planned_check = service.plan_daily_check()
    check_lease()
    sent = dispatch_outbox(service, check_lease=check_lease)
    check_lease()
    logger.debug(
        "literature_planner_cycle_completed",
        planned_check_id=planned_check.get("check_id") if planned_check else None,
        published_work_item_count=sent,
    )
    return sent

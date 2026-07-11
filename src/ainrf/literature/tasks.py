"""Dramatiq actors.  Messages intentionally contain only a durable work ID."""

from __future__ import annotations

import dramatiq

from ainrf.literature.broker import configure_broker
from ainrf.literature.work import process_durable_work_item

configure_broker()


@dramatiq.actor(max_retries=0, queue_name="literature")
def process_work_item(work_item_id: str) -> None:
    process_durable_work_item(work_item_id)

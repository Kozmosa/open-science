"""APScheduler integration for periodic literature fetching."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ainrf.literature.fetcher import fetch_for_subscription
from ainrf.literature.service import LiteratureService

logger = logging.getLogger(__name__)


class LiteratureScheduler:
    """Manages scheduled literature fetching for active subscriptions."""

    def __init__(self, service: LiteratureService, interval_hours: int = 6):
        self._service = service
        self._scheduler = AsyncIOScheduler()
        self._interval_hours = interval_hours

    def start(self) -> None:
        self._scheduler.add_job(
            self._fetch_all,
            "interval",
            hours=self._interval_hours,
            id="literature_fetch",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Literature scheduler started (interval=%dh)", self._interval_hours)

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Literature scheduler stopped")

    async def _fetch_all(self) -> None:
        """Fetch papers for all active subscriptions, respecting frequency."""
        from datetime import datetime, timezone

        subs = self._service.list_active_subscriptions()
        if not subs:
            return

        now = datetime.now(timezone.utc)
        due_subs = []
        for sub in subs:
            if sub.frequency == "weekly":
                if sub.last_fetched_at:
                    last = datetime.fromisoformat(sub.last_fetched_at)
                    if (now - last).days < 7:
                        continue
            # daily and twicedaily: always fetch (twicedaily handled by interval)
            due_subs.append(sub)

        if not due_subs:
            return

        logger.info("Literature fetch: checking %d due subscriptions", len(due_subs))
        for sub in due_subs:
            try:
                papers = await fetch_for_subscription(sub)
                new = [p for p in papers if not self._service.paper_exists(p.paper_id, sub.subscription_id)]
                if new:
                    count = self._service.insert_papers(new)
                    logger.info("Literature fetch: sub=%s total=%d new=%d", sub.subscription_id, len(papers), count)
                self._service.update_last_fetched(sub.subscription_id)
            except Exception as exc:
                logger.error("Literature fetch failed: sub=%s error=%s", sub.subscription_id, exc)

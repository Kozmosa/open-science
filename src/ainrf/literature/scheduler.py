"""APScheduler integration for per-subscription literature fetching."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ainrf.literature import fetcher as _fetcher_module
from ainrf.literature.service import LiteratureService

if TYPE_CHECKING:
    from ainrf.observability.protocol import ObservabilityReporter

logger = logging.getLogger(__name__)


class LiteratureScheduler:
    """Manages per-subscription scheduled literature fetching.

    Each active subscription gets its own APScheduler ``IntervalTrigger`` job,
    keyed by ``subscription_id``.  A per-subscription ``asyncio.Lock`` prevents
    scheduled and manual fetches from running concurrently for the same
    subscription.
    """

    def __init__(
        self,
        service: LiteratureService,
        reporter: ObservabilityReporter | None = None,
    ):
        self._service = service
        self._scheduler: AsyncIOScheduler | None = None
        self._reporter = reporter
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: set[str] = set()
        self._last_error: dict[str, str] = {}

    def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        for sub in self._service.list_active_subscriptions():
            self.schedule_subscription(sub)
        logger.info("Literature scheduler started with %d active subscription(s)", len(self._locks))

    async def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
        logger.info("Literature scheduler stopped")

    def _get_lock(self, subscription_id: str) -> asyncio.Lock:
        if subscription_id not in self._locks:
            self._locks[subscription_id] = asyncio.Lock()
        return self._locks[subscription_id]

    @staticmethod
    def _frequency_interval(frequency: str) -> IntervalTrigger:
        if frequency == "twicedaily":
            return IntervalTrigger(hours=12)
        if frequency == "weekly":
            return IntervalTrigger(days=7)
        # Default to daily for unknown or empty values.
        return IntervalTrigger(hours=24)

    @staticmethod
    def _compute_next_fetch_at(frequency: str) -> str:
        now = datetime.now(timezone.utc)
        if frequency == "twicedaily":
            return (now + timedelta(hours=12)).isoformat()
        if frequency == "weekly":
            return (now + timedelta(days=7)).isoformat()
        return (now + timedelta(days=1)).isoformat()

    def _parse_next_fetch_at(self, next_fetch_at: str | None) -> datetime | None:
        if not next_fetch_at:
            return None
        try:
            return datetime.fromisoformat(next_fetch_at)
        except ValueError:
            return None

    def schedule_subscription(self, sub) -> None:
        """Add or replace the scheduled job for a subscription."""
        if self._scheduler is None:
            # Scheduler not started yet (e.g. in tests).  Just ensure the lock exists.
            self._get_lock(sub.subscription_id)
            return
        job_id = f"lit-{sub.subscription_id}"
        next_run_time = self._parse_next_fetch_at(sub.next_fetch_at)
        # If next_fetch_at is in the past, let APScheduler run it now.
        if next_run_time is not None and next_run_time <= datetime.now(timezone.utc):
            next_run_time = None
        self._scheduler.add_job(
            self._run_scheduled_fetch,
            self._frequency_interval(sub.frequency),
            id=job_id,
            replace_existing=True,
            next_run_time=next_run_time,
            args=(sub.subscription_id,),
        )
        self._get_lock(sub.subscription_id)
        logger.debug("scheduled subscription=%s frequency=%s", sub.subscription_id, sub.frequency)

    def remove_subscription(self, subscription_id: str) -> None:
        job_id = f"lit-{subscription_id}"
        if self._scheduler is not None:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._locks.pop(subscription_id, None)
        self._running.discard(subscription_id)
        self._last_error.pop(subscription_id, None)

    def reschedule_subscription(self, sub) -> None:
        """Update a subscription's schedule after frequency or timing changes."""
        if not sub.is_active:
            self.remove_subscription(sub.subscription_id)
            return
        self.schedule_subscription(sub)

    async def _run_scheduled_fetch(self, subscription_id: str) -> None:
        try:
            await self.fetch_subscription(subscription_id)
        except Exception as exc:
            # APScheduler already logs the exception; keep the job alive.
            logger.error("scheduled fetch failed: sub=%s error=%s", subscription_id, exc)

    async def fetch_subscription(self, subscription_id: str) -> dict:
        """Fetch papers for a single subscription under a per-subscription lock.

        This is the single locked entry point used by both scheduled jobs and
        manual API triggers, so a subscription can never be fetched twice at the
        same time.
        """
        sub = self._service.get_subscription(subscription_id)
        if sub is None:
            raise ValueError(f"subscription not found: {subscription_id}")

        lock = self._get_lock(subscription_id)
        if lock.locked():
            raise RuntimeError(f"fetch already running for subscription {subscription_id}")

        from ainrf.api.routes.metrics import (  # lazy — avoids circular import
            inc_counter,
            observe_histogram,
            set_gauge,
        )

        async with lock:
            self._running.add(subscription_id)
            self._last_error.pop(subscription_id, None)
            t_start = time.monotonic()
            try:
                papers = await _fetcher_module.fetch_for_subscription(sub, self._reporter)
                new_count = self._service.upsert_papers(subscription_id, papers)
                self._service.update_last_fetched(subscription_id)
                self._service.set_next_fetch_at(
                    subscription_id, self._compute_next_fetch_at(sub.frequency)
                )
                elapsed = time.monotonic() - t_start
                inc_counter(
                    "ainrf_literature_fetch_total",
                    {"subscription_id": subscription_id, "status": "success"},
                )
                inc_counter(
                    "ainrf_literature_papers_fetched_total",
                    {"subscription_id": subscription_id},
                    amount=len(papers),
                )
                if new_count:
                    inc_counter(
                        "ainrf_literature_papers_new_total",
                        {"subscription_id": subscription_id},
                        amount=new_count,
                    )
                observe_histogram(
                    "ainrf_literature_fetch_duration_seconds",
                    elapsed,
                    {"subscription_id": subscription_id},
                )
                set_gauge(
                    "ainrf_literature_last_fetch_timestamp_seconds",
                    time.time(),
                    {"subscription_id": subscription_id},
                )
                logger.info(
                    "fetch complete: subscription=%s papers=%d new=%d",
                    subscription_id,
                    len(papers),
                    new_count,
                )
                return {"paper_count": len(papers), "new_count": new_count}
            except Exception as exc:
                elapsed = time.monotonic() - t_start
                self._last_error[subscription_id] = str(exc)
                inc_counter(
                    "ainrf_literature_fetch_total",
                    {"subscription_id": subscription_id, "status": "failed"},
                )
                observe_histogram(
                    "ainrf_literature_fetch_duration_seconds",
                    elapsed,
                    {"subscription_id": subscription_id},
                )
                logger.error("fetch failed: subscription=%s error=%s", subscription_id, exc)
                raise
            finally:
                self._running.discard(subscription_id)

    def is_fetching(self, subscription_id: str) -> bool:
        return subscription_id in self._running

    def get_last_error(self, subscription_id: str) -> str | None:
        return self._last_error.get(subscription_id)

    @staticmethod
    def _is_due(sub) -> bool:
        """Return True when a subscription should be fetched right now.

        Daily/twicedaily subscriptions are always considered due (the scheduler
        itself enforces the real interval).  Weekly subscriptions are skipped if
        they were already fetched within the last 7 days.
        """
        if sub.frequency == "weekly" and sub.last_fetched_at:
            try:
                last = datetime.fromisoformat(sub.last_fetched_at)
                if datetime.now(timezone.utc) - last < timedelta(days=7):
                    return False
            except ValueError:
                pass
        return True

    async def _fetch_all(self) -> None:
        """Fetch papers for all active subscriptions that are currently due.

        This is primarily a testing/debugging entry point; the production path
        uses per-subscription APScheduler jobs.
        """
        subs = self._service.list_active_subscriptions()
        if not subs:
            return

        due_subs = [sub for sub in subs if self._is_due(sub)]
        if not due_subs:
            return

        logger.info("Literature fetch: checking %d due subscription(s)", len(due_subs))
        for sub in due_subs:
            try:
                await self.fetch_subscription(sub.subscription_id)
            except Exception as exc:
                logger.error("Literature fetch failed: sub=%s error=%s", sub.subscription_id, exc)

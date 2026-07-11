"""Shared arXiv request limiter for RSS and Search API traffic."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from redis import Redis


class ProviderBudgetExhausted(RuntimeError):
    """Raised before a source request that would exceed its daily budget."""


class ArxivRequestLimiter:
    """Redis-backed single-connection, minimum-interval limiter.

    This intentionally reserves a budget unit before the HTTP request.  A
    timeout may have reached arXiv, so it must not be silently refunded.
    """

    def __init__(self) -> None:
        self._namespace = os.getenv(
            "OPENSCIENCE_LITERATURE_REDIS_NAMESPACE", "openscience:literature"
        )
        self._interval_seconds = int(
            os.getenv("OPENSCIENCE_LITERATURE_REQUEST_INTERVAL_SECONDS", "3")
        )
        self._daily_budget = int(os.getenv("OPENSCIENCE_LITERATURE_DAILY_SOURCE_BUDGET", "24"))
        self._client = Redis.from_url(
            os.getenv("OPENSCIENCE_LITERATURE_REDIS_URL", "redis://127.0.0.1:16379/0")
        )

    def acquire(self) -> None:
        day = datetime.now(UTC).date().isoformat()
        budget_key = f"{self._namespace}:arxiv:budget:{day}"
        count = int(self._client.incr(budget_key))
        if count == 1:
            self._client.expire(budget_key, 172800)
        if count > self._daily_budget:
            self._client.decr(budget_key)
            raise ProviderBudgetExhausted("Daily arXiv request budget is exhausted")
        lock_key = f"{self._namespace}:arxiv:request-slot"
        ttl_ms = self._interval_seconds * 1000
        while not self._client.set(lock_key, "1", nx=True, px=ttl_ms):
            time.sleep(0.1)

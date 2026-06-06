from __future__ import annotations

import asyncio
import time

import pytest

from ainrf.literature import fetcher
from ainrf.literature.models import LiteratureSubscription

pytestmark = [pytest.mark.unit]


class SlowEmptyArxivClient:
    def results(self, _search: object) -> list[object]:
        time.sleep(0.05)
        return []


@pytest.mark.anyio
async def test_fetch_for_subscription_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ainrf.literature.fetcher.arxiv.Client", lambda: SlowEmptyArxivClient())
    subscription = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="user-1",
        keywords=["agent"],
        arxiv_categories=["cs.AI"],
    )

    task = asyncio.create_task(fetcher.fetch_for_subscription(subscription))
    start = time.perf_counter()
    await asyncio.sleep(0.01)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.03
    assert not task.done()
    assert await task == []

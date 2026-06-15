"""arXiv fetch + LLM summarization pipeline orchestrator."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ainrf.literature.arxiv_client import fetch_papers
from ainrf.literature.models import LiteratureSubscription
from ainrf.literature.summarizer import AnthropicSummarizer

if TYPE_CHECKING:
    from ainrf.observability.protocol import ObservabilityReporter

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


def _since_for_subscription(sub: LiteratureSubscription) -> datetime | None:
    """Return the datetime from which we should search for new papers."""
    if sub.last_fetched_at:
        try:
            return datetime.fromisoformat(sub.last_fetched_at)
        except ValueError:
            logger.warning(
                "invalid last_fetched_at for subscription=%s: %s",
                sub.subscription_id,
                sub.last_fetched_at,
            )
    return datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)


async def fetch_for_subscription(
    sub: LiteratureSubscription,
    reporter: ObservabilityReporter | None = None,
) -> list:
    """Fetch papers for a single subscription and summarize them.

    Queries arXiv with the subscription's keywords and categories,
    restricted to papers submitted since the last successful fetch (or the
    default lookback window). Papers are then summarized in batches via the
    Anthropic-compatible Messages API configured through environment variables.
    """
    from ainrf.observability.protocol import NullReporter

    _obs = reporter or NullReporter()
    trace_id = f"lit-{sub.subscription_id}"

    _obs.start_trace(
        trace_id=trace_id,
        name="literature-fetch",
        metadata={
            "keywords": sub.keywords,
            "categories": sub.arxiv_categories,
        },
    )

    try:
        since = _since_for_subscription(sub)
        papers = await fetch_papers(sub, since=since)

        if papers:
            summarizer = AnthropicSummarizer(
                reporter=_obs,
                trace_id=trace_id,
            )
            await summarizer.summarize(papers)
    except Exception:
        _obs.end_trace(trace_id=trace_id, output={"paper_count": 0})
        raise

    _obs.end_trace(
        trace_id=trace_id,
        output={"paper_count": len(papers)},
    )
    return papers

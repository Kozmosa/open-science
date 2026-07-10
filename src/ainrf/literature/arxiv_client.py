"""arXiv search client with date-window queries and retries."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import arxiv

from ainrf.literature.models import LiteraturePaper

if TYPE_CHECKING:
    from ainrf.literature.models import LiteratureSubscription

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CAP = 100


def _paper_id_from_entry_id(entry_id: str) -> str:
    """Extract the canonical arXiv ID (without version suffix) from an entry URL."""
    return entry_id.rstrip("/").split("/")[-1].split("v")[0]


def _format_arxiv_date(dt: datetime) -> str:
    """Format a UTC datetime for arXiv's submittedDate query syntax."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def build_query(sub: LiteratureSubscription, since: datetime | None = None) -> str:
    """Build an arXiv query from subscription keywords/categories and optional date window."""
    query_parts: list[str] = []

    if sub.keywords:
        escaped = [kw.replace('"', '\\"') for kw in sub.keywords]
        query_parts.append("(" + " AND ".join(f'"{kw}"' for kw in escaped) + ")")

    if sub.arxiv_categories:
        query_parts.append("(" + " OR ".join(f"cat:{cat}" for cat in sub.arxiv_categories) + ")")

    if since is not None:
        now = datetime.now(timezone.utc)
        query_parts.append(
            f"submittedDate:[{_format_arxiv_date(since)} TO {_format_arxiv_date(now)}]"
        )

    if not query_parts:
        logger.warning(
            "arxiv query has no keywords or categories for subscription=%s", sub.subscription_id
        )
        return "all:recent"

    return " AND ".join(query_parts)


def _to_literature_paper(result: Any) -> LiteraturePaper:
    """Convert an arxiv.Result into our internal LiteraturePaper model."""
    return LiteraturePaper(
        paper_id=_paper_id_from_entry_id(str(result.entry_id)),
        title=str(result.title),
        authors=[a.name for a in result.authors],
        abstract=str(result.summary),
        published_at=result.published.isoformat(),
        arxiv_category=str(result.primary_category),
    )


def fetch_papers_sync(
    sub: LiteratureSubscription,
    *,
    since: datetime | None = None,
    max_results: int | None = None,
) -> list[LiteraturePaper]:
    """Synchronous arXiv fetch; callers should offload to a thread."""
    requested_max = max_results or getattr(sub, "max_results", None) or DEFAULT_MAX_RESULTS
    requested_max = min(max(1, requested_max), MAX_RESULTS_CAP)

    query = build_query(sub, since)
    logger.info(
        "arxiv fetch: subscription=%s query=%r max_results=%d",
        sub.subscription_id,
        query,
        requested_max,
    )

    client = arxiv.Client(
        num_retries=3,
        delay_seconds=3.0,
    )
    search = arxiv.Search(
        query=query,
        max_results=requested_max,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    try:
        results = list(client.results(search))
    except Exception as exc:
        logger.error(
            "arxiv fetch failed: subscription=%s error=%s", sub.subscription_id, exc, exc_info=True
        )
        raise

    papers = [_to_literature_paper(r) for r in results]
    logger.info("arxiv fetch ok: subscription=%s returned=%d", sub.subscription_id, len(papers))
    return papers


async def fetch_papers(
    sub: LiteratureSubscription,
    *,
    since: datetime | None = None,
    max_results: int | None = None,
) -> list[LiteraturePaper]:
    """Offload the synchronous arxiv client to a worker thread."""
    return await asyncio.to_thread(fetch_papers_sync, sub, since=since, max_results=max_results)

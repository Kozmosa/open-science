"""Bounded arXiv Search API adapter for backfill and reconciliation only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Iterable

import arxiv

from ainrf.literature.tracking import DiscoveredPaper, canonical_arxiv_id


class ArxivSearchProvider:
    """Normalise Search API results without using it as the daily feed."""

    name = "arxiv-search"

    async def search(
        self,
        *,
        categories: Iterable[str],
        since: datetime | None = None,
        max_results: int = 100,
    ) -> list[DiscoveredPaper]:
        return await asyncio.to_thread(
            self._search_sync, list(categories), since, min(max(1, max_results), 2000)
        )

    @staticmethod
    def _search_sync(
        categories: list[str], since: datetime | None, max_results: int
    ) -> list[DiscoveredPaper]:
        category_query = " OR ".join(f"cat:{category}" for category in sorted(set(categories)))
        if not category_query:
            raise ValueError("Search backfill requires at least one category")
        query = f"({category_query})"
        if since is not None:
            start = since.astimezone(UTC).strftime("%Y%m%d%H%M")
            end = datetime.now(UTC).strftime("%Y%m%d%H%M")
            query = f"{query} AND submittedDate:[{start} TO {end}]"
        client = arxiv.Client(num_retries=0, delay_seconds=3.0, page_size=min(max_results, 1000))
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.LastUpdatedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        return [_normalise_result(result) for result in client.results(search)]


def _normalise_result(result: Any) -> DiscoveredPaper:
    external_id, provider_version = canonical_arxiv_id(str(result.entry_id))
    categories = [str(category) for category in result.categories]
    return DiscoveredPaper(
        provider="arxiv",
        external_id=external_id,
        provider_version=provider_version,
        title=str(result.title),
        authors=[str(author.name) for author in result.authors],
        abstract=str(result.summary),
        primary_category=str(result.primary_category),
        categories=categories,
        published_at=result.published.isoformat(),
        updated_at=result.updated.isoformat(),
        source_url=str(result.entry_id),
        pdf_url=str(result.pdf_url),
        announce_type="reconcile",
        announced_at=result.updated.isoformat(),
    )

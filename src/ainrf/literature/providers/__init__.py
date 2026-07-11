"""External literature providers and their normalised discovery records."""

from ainrf.literature.providers.arxiv_rss import ArxivRssProvider, RssFetchResult
from ainrf.literature.providers.arxiv_search import ArxivSearchProvider

__all__ = ["ArxivRssProvider", "ArxivSearchProvider", "RssFetchResult"]

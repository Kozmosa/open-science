"""Tests for the arXiv client query builder and fetcher."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ainrf.literature.arxiv_client import (
    _format_arxiv_date,
    _paper_id_from_entry_id,
    build_query,
    fetch_papers_sync,
)
from ainrf.literature.models import LiteratureSubscription

pytestmark = [pytest.mark.unit]


def test_paper_id_from_entry_id_with_version():
    assert _paper_id_from_entry_id("http://arxiv.org/abs/2301.00001v1") == "2301.00001"


def test_paper_id_from_entry_id_without_version():
    assert _paper_id_from_entry_id("https://arxiv.org/abs/2301.00001") == "2301.00001"


def test_format_arxiv_date_uses_utc():
    dt = datetime(2023, 6, 15, 12, 30, tzinfo=timezone.utc)
    assert _format_arxiv_date(dt) == "202306151230"


def test_build_query_keywords_and_categories():
    sub = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="u1",
        keywords=["attention", "transformer"],
        arxiv_categories=["cs.AI", "cs.CL"],
    )
    query = build_query(sub)
    assert '("attention" AND "transformer")' in query
    assert "(cat:cs.AI OR cat:cs.CL)" in query
    assert "submittedDate" not in query


def test_build_query_includes_date_window():
    sub = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="u1",
        keywords=["agent"],
    )
    since = datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    query = build_query(sub, since=since)
    assert '"agent"' in query
    assert "submittedDate:[202301010000 TO" in query


def test_build_query_escapes_quotes_in_keywords():
    sub = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="u1",
        keywords=['large "language" model'],
    )
    query = build_query(sub)
    assert '\\"language\\"' in query


def test_build_query_fallback_when_empty():
    sub = LiteratureSubscription(subscription_id="sub-1", user_id="u1")
    assert build_query(sub) == "all:recent"


def test_fetch_papers_sync_maps_results():
    sub = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="u1",
        keywords=["test"],
        arxiv_categories=["cs.AI"],
    )

    stub = MagicMock()
    stub.entry_id = "http://arxiv.org/abs/2301.00001v1"
    stub.title = "Test Title"
    author = MagicMock()
    author.name = "Author One"
    stub.authors = [author]
    stub.summary = "Abstract text."
    stub.published = datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    stub.primary_category = "cs.AI"

    with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.results.return_value = [stub]
        mock_cls.return_value = mock_client

        papers = fetch_papers_sync(sub)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.paper_id == "2301.00001"
    assert paper.title == "Test Title"
    assert paper.authors == ["Author One"]
    assert paper.abstract == "Abstract text."
    assert paper.arxiv_category == "cs.AI"


def test_fetch_papers_sync_raises_on_arxiv_error():
    sub = LiteratureSubscription(
        subscription_id="sub-1",
        user_id="u1",
        keywords=["test"],
    )

    with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.results.side_effect = RuntimeError("network down")
        mock_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="network down"):
            fetch_papers_sync(sub)

"""Tests for literature Prometheus metrics instrumentation."""

from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ainrf.api.routes.metrics import (
    get_metrics_text,
    reset_metrics,
)
from ainrf.literature.fetcher import fetch_for_subscription
from ainrf.literature.models import LiteraturePaper, LiteratureSubscription
from ainrf.literature.scheduler import LiteratureScheduler
from ainrf.literature.service import LiteratureService
from ainrf.literature.summarizer import AnthropicSummarizer

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    reset_metrics()
    yield
    reset_metrics()


# ── helpers ──────────────────────────────────────────────────────────


def _sub(*, subscription_id: str = "sub-test") -> LiteratureSubscription:
    return LiteratureSubscription(
        subscription_id=subscription_id,
        user_id="user-1",
        keywords=["attention", "transformer"],
        arxiv_categories=["cs.AI"],
    )


def _paper(paper_id: str = "2301.00001") -> LiteraturePaper:
    return LiteraturePaper(
        paper_id=paper_id,
        title="Test Paper Title",
        abstract="This is a test abstract.",
        authors=["Author One", "Author Two"],
        published_at="2023-01-01T00:00:00+00:00",
        arxiv_category="cs.AI",
    )


def _prom_text_contains(name: str, text: str) -> bool:
    """Return True if metric *name* appears in Prometheus text output."""
    return name in text


def _counter_value(name: str, text: str, label_filter: str = "") -> float:
    """Parse a counter value from Prometheus text format.

    If *label_filter* is given, only lines containing that substring are considered.
    Returns 0.0 if not found.
    """
    for line in text.split("\n"):
        if line.startswith(name) and label_filter in line:
            # Prometheus format: name{labels} value
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    return float(parts[1])
                except ValueError:
                    pass
    return 0.0


def _histogram_count(name: str, text: str) -> float:
    """Extract the histogram sample count (the ``_count`` suffix line)."""
    return _counter_value(f"{name}_count", text)


def _arxiv_stub_paper(
    *,
    entry_id: str = "http://arxiv.org/abs/2301.00001v1",
    title: str = "Stub Title",
    authors: list | None = None,
    summary: str = "stub",
    published_iso: str = "2023-01-01T00:00:00+00:00",
    primary_category: str = "cs.AI",
) -> MagicMock:
    stub = MagicMock()
    stub.entry_id = entry_id
    stub.title = title
    stub.authors = authors or []
    stub.summary = summary
    stub.published = MagicMock()
    stub.published.isoformat.return_value = published_iso
    stub.primary_category = primary_category
    return stub


def _anthropic_message(text: str) -> MagicMock:
    message = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    message.content = [content_block]
    message.usage = MagicMock()
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    message.usage.cache_creation_input_tokens = 0
    message.usage.cache_read_input_tokens = 0
    return message


# ══════════════════════════════════════════════════════════════════════
# Scheduler metrics
# ══════════════════════════════════════════════════════════════════════


class TestSchedulerFetchSuccess:
    """Metrics emitted when a scheduled fetch completes successfully."""

    @pytest.mark.anyio
    async def test_fetch_total_counter_success(self, tmp_path: Path) -> None:
        svc = LiteratureService(state_root=tmp_path)
        svc.initialize()
        sub = svc.create_subscription(
            user_id="user-1",
            keywords=["test"],
            arxiv_categories=["cs.AI"],
        )
        scheduler = LiteratureScheduler(svc)

        stub_paper = _arxiv_stub_paper()

        with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.results.return_value = [stub_paper]
            mock_client_cls.return_value = mock_client

            # No API key → skip LLM summarization (metrics still track fetch).
            await scheduler._fetch_all()

        text = get_metrics_text()
        assert _counter_value(
            "ainrf_literature_fetch_total", text,
            label_filter=f'subscription_id="{sub.subscription_id}"',
        ) == 1.0
        assert _counter_value(
            "ainrf_literature_papers_fetched_total", text,
            label_filter=f'subscription_id="{sub.subscription_id}"',
        ) == 1.0
        # One new paper inserted.
        assert _counter_value(
            "ainrf_literature_papers_new_total", text,
            label_filter=f'subscription_id="{sub.subscription_id}"',
        ) == 1.0
        # Histogram should have at least one observation.
        assert _histogram_count("ainrf_literature_fetch_duration_seconds", text) >= 1.0

    @pytest.mark.anyio
    async def test_last_fetch_timestamp_gauge_set(self, tmp_path: Path) -> None:
        svc = LiteratureService(state_root=tmp_path)
        svc.initialize()
        sub = svc.create_subscription(
            user_id="user-1",
            keywords=["test"],
        )
        scheduler = LiteratureScheduler(svc)

        with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
            mock_cls.return_value.results.return_value = []
            await scheduler._fetch_all()

        text = get_metrics_text()
        assert f'subscription_id="{sub.subscription_id}"' in text
        assert "ainrf_literature_last_fetch_timestamp_seconds" in text


class TestSchedulerFetchFailure:
    """Metrics emitted when a scheduled fetch fails."""

    @pytest.mark.anyio
    async def test_fetch_total_counter_failed(self, tmp_path: Path) -> None:
        svc = LiteratureService(state_root=tmp_path)
        svc.initialize()
        sub = svc.create_subscription(
            user_id="user-1",
            keywords=["test"],
        )
        scheduler = LiteratureScheduler(svc)

        # Make fetch_for_subscription raise to trigger the failure path.
        with patch(
            "ainrf.literature.fetcher.fetch_for_subscription",
            side_effect=RuntimeError("arXiv down"),
        ):
            await scheduler._fetch_all()

        text = get_metrics_text()
        assert (
            _counter_value(
                "ainrf_literature_fetch_total",
                text,
                label_filter=f'subscription_id="{sub.subscription_id}"',
            )
            == 1.0
        )
        assert 'status="failed"' in text
        # Histogram should still be recorded for the failed attempt.
        assert _histogram_count("ainrf_literature_fetch_duration_seconds", text) >= 1.0


class TestSchedulerNoSubscriptions:
    @pytest.mark.anyio
    async def test_no_fetch_counter_when_no_active_subs(self, tmp_path: Path) -> None:
        """No fetch data lines are emitted when there are no subscriptions."""
        svc = LiteratureService(state_root=tmp_path)
        svc.initialize()
        scheduler = LiteratureScheduler(svc)
        await scheduler._fetch_all()

        text = get_metrics_text()
        # HELP/TYPE lines exist for pre-declared metrics even without observations.
        # The data line (metric name + value) must not appear.
        assert _counter_value("ainrf_literature_fetch_total", text) == 0.0
        assert _histogram_count("ainrf_literature_fetch_duration_seconds", text) == 0.0


# ══════════════════════════════════════════════════════════════════════
# Fetcher summarize metrics
# ══════════════════════════════════════════════════════════════════════


class TestSummarizeMetrics:
    """Metrics emitted during LLM paper summarization."""

    @pytest.mark.anyio
    async def test_summarize_success_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Count each successful LLM summarize call."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        text = (
            '[{"paper_id": "2301.00001", "title_zh": "测试标题", '
            '"ai_summary": ["点1", "点2", "点3"], "ai_practice_note": "可以试试"}]'
        )

        paper = _paper()
        with patch("anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _anthropic_message(text)
            async with AnthropicSummarizer() as summarizer:
                await summarizer.summarize([paper])

        text = get_metrics_text()
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="success"') == 1.0
        assert _histogram_count("ainrf_literature_summarize_duration_seconds", text) >= 1.0
        # Paper fields should be populated.
        assert paper.title_zh == "测试标题"
        assert paper.ai_summary is not None
        assert paper.ai_practice_note == "可以试试"

    @pytest.mark.anyio
    async def test_summarize_failure_counter_on_http_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count failed summarize calls when LLM returns an error."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        paper = _paper()
        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create",
            side_effect=RuntimeError("internal"),
        ):
            async with AnthropicSummarizer() as summarizer:
                await summarizer.summarize([paper])

        text = get_metrics_text()
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="failed"') == 1.0

    @pytest.mark.anyio
    async def test_summarize_failure_counter_on_exception(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count failed summarize calls when an exception is raised."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            async with AnthropicSummarizer() as summarizer:
                await summarizer.summarize([_paper()])

        text = get_metrics_text()
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="failed"') == 1.0

    @pytest.mark.anyio
    async def test_no_summarize_counter_when_no_api_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no API key is configured, summarize is skipped — no data lines emitted."""
        # Ensure all API key env vars are unset.
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            monkeypatch.delenv(key, raising=False)

        async with AnthropicSummarizer() as summarizer:
            await summarizer.summarize([_paper()])

        text = get_metrics_text()
        # HELP/TYPE lines exist for pre-declared metrics; the data value must be 0.
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="success"') == 0.0
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="failed"') == 0.0
        assert _histogram_count("ainrf_literature_summarize_duration_seconds", text) == 0.0


# ══════════════════════════════════════════════════════════════════════
# End-to-end fetch_for_subscription metrics (smoke test)
# ══════════════════════════════════════════════════════════════════════


class TestFetchForSubscriptionMetrics:
    @pytest.mark.anyio
    async def test_fetch_records_metrics_through_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full fetch_for_subscription call triggers both fetch and summarize metrics."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        stub_paper = _arxiv_stub_paper(
            entry_id="http://arxiv.org/abs/2301.00001v1",
            title="Attention Is All You Need",
            summary="The dominant sequence transduction models...",
            published_iso="2017-06-12T00:00:00+00:00",
            primary_category="cs.CL",
        )

        llm_text = (
            '[{"paper_id": "2301.00001", "title_zh": "注意力即一切", '
            '"ai_summary": ["发现", "方法", "意义"], "ai_practice_note": "可以阅读"}]'
        )

        with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
            mock_cls.return_value.results.return_value = [stub_paper]
            with patch(
                "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = _anthropic_message(llm_text)
                papers = await fetch_for_subscription(_sub(subscription_id="sub-e2e"))

        assert len(papers) == 1

        text = get_metrics_text()
        assert _counter_value("ainrf_literature_summarize_total", text,
                              label_filter='status="success"') == 1.0
        assert _histogram_count("ainrf_literature_summarize_duration_seconds", text) >= 1.0

    @pytest.mark.anyio
    async def test_fetch_handles_duplicate_papers_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Duplicate papers are not double-counted in papers_new_total."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        svc = LiteratureService(state_root=tmp_path)
        svc.initialize()
        sub = svc.create_subscription(
            user_id="user-1",
            keywords=["test"],
        )

        stub_paper = _arxiv_stub_paper(
            entry_id="http://arxiv.org/abs/2301.00001v1",
            title="Test",
            summary="abs",
        )

        llm_text = (
            '[{"paper_id": "2301.00001", "title_zh": "测试", '
            '"ai_summary": ["a", "b", "c"], "ai_practice_note": "可以试"}]'
        )

        scheduler = LiteratureScheduler(svc)

        # First fetch: inserts 1 new paper.
        with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
            mock_cls.return_value.results.return_value = [stub_paper]
            with patch(
                "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = _anthropic_message(llm_text)
                await scheduler._fetch_all()

        # Second fetch: same paper already exists, so papers_new should stay at 1.
        with patch("ainrf.literature.arxiv_client.arxiv.Client") as mock_cls:
            mock_cls.return_value.results.return_value = [stub_paper]
            with patch(
                "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = _anthropic_message(llm_text)
                await scheduler._fetch_all()

        text = get_metrics_text()

        # Total fetches = 2 (both successful).
        assert (
            _counter_value(
                "ainrf_literature_fetch_total",
                text,
                label_filter=f'subscription_id="{sub.subscription_id}"',
            )
            == 2.0
        )
        # Papers fetched from arXiv = 2 (1 each time).
        assert (
            _counter_value(
                "ainrf_literature_papers_fetched_total",
                text,
                label_filter=f'subscription_id="{sub.subscription_id}"',
            )
            == 2.0
        )
        # Papers *new* = 1 (second was duplicate).
        assert (
            _counter_value(
                "ainrf_literature_papers_new_total",
                text,
                label_filter=f'subscription_id="{sub.subscription_id}"',
            )
            == 1.0
        )

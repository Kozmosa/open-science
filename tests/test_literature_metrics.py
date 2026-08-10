"""Tests for literature Prometheus metrics instrumentation."""

from __future__ import annotations

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ainrf.telemetry.metrics import (
    get_metrics_text,
    reset_metrics,
)
from ainrf.literature.models import LiteraturePaper
from ainrf.literature.summarizer import AnthropicSummarizer, ExternalCallFailure

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    reset_metrics()
    yield
    reset_metrics()


# ── helpers ──────────────────────────────────────────────────────────


def _paper(paper_id: str = "2301.00001") -> LiteraturePaper:
    return LiteraturePaper(
        paper_id=paper_id,
        title="Test Paper Title",
        abstract="This is a test abstract.",
        authors=["Author One", "Author Two"],
        published_at="2023-01-01T00:00:00+00:00",
        arxiv_category="cs.AI",
    )


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
# Summarize metrics
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
        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = _anthropic_message(text)
            async with AnthropicSummarizer() as summarizer:
                await summarizer.summarize([paper])

        text = get_metrics_text()
        assert (
            _counter_value(
                "ainrf_literature_summarize_total", text, label_filter='status="success"'
            )
            == 1.0
        )
        assert _histogram_count("ainrf_literature_summarize_duration_seconds", text) >= 1.0
        # Paper fields should be populated.
        assert paper.title_zh == "测试标题"
        assert paper.ai_summary is not None
        assert paper.ai_practice_note == "可以试试"

    @pytest.mark.anyio
    async def test_summarize_failure_counter_on_http_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count failed summarize calls when LLM returns an error."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        paper = _paper()
        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create",
            side_effect=RuntimeError("internal"),
        ):
            async with AnthropicSummarizer() as summarizer:
                with pytest.raises(ExternalCallFailure, match="internal"):
                    await summarizer.summarize([paper])

        text = get_metrics_text()
        assert (
            _counter_value("ainrf_literature_summarize_total", text, label_filter='status="failed"')
            == 1.0
        )

    @pytest.mark.anyio
    async def test_summarize_failure_counter_on_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count failed summarize calls when an exception is raised."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            async with AnthropicSummarizer() as summarizer:
                with pytest.raises(ExternalCallFailure, match="connection refused"):
                    await summarizer.summarize([_paper()])

        text = get_metrics_text()
        assert (
            _counter_value("ainrf_literature_summarize_total", text, label_filter='status="failed"')
            == 1.0
        )

    @pytest.mark.anyio
    async def test_no_summarize_counter_when_no_api_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no API key is configured, summarize is skipped — no data lines emitted."""
        # Ensure all API key env vars are unset.
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            monkeypatch.delenv(key, raising=False)

        async with AnthropicSummarizer() as summarizer:
            await summarizer.summarize([_paper()])

        text = get_metrics_text()
        # HELP/TYPE lines exist for pre-declared metrics; the data value must be 0.
        assert (
            _counter_value(
                "ainrf_literature_summarize_total", text, label_filter='status="success"'
            )
            == 0.0
        )
        assert (
            _counter_value("ainrf_literature_summarize_total", text, label_filter='status="failed"')
            == 0.0
        )
        assert _histogram_count("ainrf_literature_summarize_duration_seconds", text) == 0.0

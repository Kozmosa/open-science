"""Tests for the Anthropic batch summarizer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ainrf.literature.models import LiteraturePaper
from ainrf.literature.summarizer import AnthropicSummarizer

pytestmark = [pytest.mark.unit]


def _paper(paper_id: str = "2301.00001") -> LiteraturePaper:
    return LiteraturePaper(
        paper_id=paper_id,
        subscription_id="sub-1",
        title="Test Paper",
        abstract="This is a test abstract.",
        authors=["Author One"],
        published_at="2023-01-01T00:00:00+00:00",
        arxiv_category="cs.AI",
    )


def _message(text: str) -> MagicMock:
    message = MagicMock()
    block = MagicMock()
    block.text = text
    message.content = [block]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 50
    message.usage.cache_creation_input_tokens = 0
    message.usage.cache_read_input_tokens = 0
    return message


@pytest.mark.anyio
async def test_batch_summarize_populates_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    papers = [_paper("2301.00001"), _paper("2301.00002")]
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题一", "ai_summary": ["a", "b", "c"], '
        '"ai_practice_note": "可以一试"},'
        '{"paper_id": "2301.00002", "title_zh": "标题二", "ai_summary": ["x", "y", "z"], '
        '"ai_practice_note": "可以看看"}]'
    )

    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        summarizer = AnthropicSummarizer(batch_size=5)
        await summarizer.summarize(papers)

    assert papers[0].title_zh == "标题一"
    assert papers[0].ai_practice_note == "可以一试"
    assert papers[1].title_zh == "标题二"
    assert papers[1].ai_practice_note == "可以看看"
    assert papers[0].summary_version == papers[1].summary_version
    assert papers[0].summary_model is not None
    mock_create.assert_awaited_once()


@pytest.mark.anyio
async def test_cache_skips_already_summarized_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    paper = _paper()
    paper.title_zh = "已有标题"
    paper.ai_summary = "- a\n- b\n- c"
    paper.summary_version = "v1:claude-sonnet-4-5"

    summarizer = AnthropicSummarizer(batch_size=5)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        await summarizer.summarize([paper])

    mock_create.assert_not_awaited()


@pytest.mark.anyio
async def test_fallback_single_on_bad_batch_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    paper = _paper()

    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        # First batch call returns invalid JSON; fallback single call succeeds.
        mock_create.side_effect = [
            _message("not json"),
            _message('{"title_zh": "单篇标题", "ai_summary": ["a"], "ai_practice_note": "可以"}'),
        ]
        summarizer = AnthropicSummarizer(batch_size=5)
        await summarizer.summarize([paper])

    assert paper.title_zh == "单篇标题"
    assert mock_create.await_count == 2


@pytest.mark.anyio
async def test_noop_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    paper = _paper()
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        await AnthropicSummarizer().summarize([paper])

    mock_create.assert_not_awaited()
    assert paper.title_zh is None

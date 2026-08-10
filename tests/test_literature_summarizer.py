"""Tests for the Anthropic batch summarizer."""

from __future__ import annotations

import asyncio
import email.utils
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import anthropic
import httpx

from ainrf.literature.attempts import LiteratureExternalCallAdapter
from ainrf.literature.models import LiteraturePaper
from ainrf.literature.summarizer import (
    AnthropicSummarizer,
    DurableAttemptPersistenceFailure,
    ExternalCallFailure,
    _retry_after_seconds,
)
from ainrf.literature.tracking import LiteratureTrackingService

pytestmark = [pytest.mark.unit]


def test_retry_after_accepts_delta_seconds_and_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("ainrf.literature.summarizer.time.time", lambda: now)
    response = SimpleNamespace(
        headers={
            "Retry-After": email.utils.format_datetime(
                datetime.fromtimestamp(now + 42, UTC), usegmt=True
            )
        }
    )
    assert _retry_after_seconds(SimpleNamespace(response=response)) == 42
    response.headers["Retry-After"] = "17"
    assert _retry_after_seconds(SimpleNamespace(response=response)) == 17


def _paper(paper_id: str = "2301.00001") -> LiteraturePaper:
    return LiteraturePaper(
        paper_id=paper_id,
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
        async with AnthropicSummarizer(batch_size=5) as summarizer:
            await summarizer.summarize(papers)

    assert papers[0].title_zh == "标题一"
    assert papers[0].ai_practice_note == "可以一试"
    assert papers[1].title_zh == "标题二"
    assert papers[1].ai_practice_note == "可以看看"
    assert papers[0].summary_version == papers[1].summary_version
    assert papers[0].summary_model is not None
    mock_create.assert_awaited_once()


@pytest.mark.anyio
async def test_batch_summarize_persists_external_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(
        service,
        work_item_id="summary-work",
        attempt_number=1,
    )
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            await summarizer.summarize([_paper()])

    attempts = service.list_api_attempts(work_item_id="summary-work")
    assert len(attempts) == 1
    assert attempts[0].provider == "anthropic"
    assert attempts[0].operation == "summary.batch"
    assert attempts[0].state == "response_received"
    assert attempts[0].response_hash is not None
    assert attempts[0].response_payload == response


@pytest.mark.anyio
async def test_durable_batch_invalid_response_does_not_fallback_to_single(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(service, work_item_id="batch-invalid", attempt_number=1)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message("not json")
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(ExternalCallFailure, match="remains unparsable"):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempts = service.list_api_attempts(work_item_id="batch-invalid")
    assert len(attempts) == 1
    assert attempts[0].operation == "summary.batch"
    assert attempts[0].state == "definitive_failure"
    assert attempts[0].error_kind == "invalid_response"
    assert attempts[0].response_payload == "not json"


@pytest.mark.anyio
async def test_durable_batch_missing_paper_does_not_fallback_to_single(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(service, work_item_id="batch-missing", attempt_number=1)
    response = (
        '[{"paper_id": "other-paper", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(ExternalCallFailure, match="omitted requested papers"):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempts = service.list_api_attempts(work_item_id="batch-missing")
    assert len(attempts) == 1
    assert attempts[0].operation == "summary.batch"
    assert attempts[0].state == "definitive_failure"
    assert attempts[0].error_kind == "missing_paper"
    assert attempts[0].response_payload == response


@pytest.mark.anyio
async def test_anthropic_max_tokens_mismatch_starts_new_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    first_adapter = LiteratureExternalCallAdapter(
        service, work_item_id="request-fingerprint-work", attempt_number=1
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(
            batch_size=5,
            max_tokens=800,
            attempt_adapter=first_adapter,
        ) as summarizer:
            await summarizer.summarize([_paper()])
    mock_create.assert_awaited_once()
    assert mock_create.await_args is not None
    assert mock_create.await_args.kwargs["max_tokens"] == 800
    first = service.list_api_attempts(work_item_id="request-fingerprint-work")[0]

    second_adapter = LiteratureExternalCallAdapter(
        service,
        work_item_id="request-fingerprint-work",
        attempt_number=2,
        recovery_attempt=first,
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(
            batch_size=5,
            max_tokens=801,
            attempt_adapter=second_adapter,
        ) as summarizer:
            await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    assert mock_create.await_args is not None
    assert mock_create.await_args.kwargs["max_tokens"] == 801
    attempts = service.list_api_attempts(work_item_id="request-fingerprint-work")
    assert len(attempts) == 2
    assert attempts[0].request_fingerprint != attempts[1].request_fingerprint


@pytest.mark.anyio
async def test_anthropic_matching_full_request_replays_without_provider_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    first_adapter = LiteratureExternalCallAdapter(
        service, work_item_id="request-replay-work", attempt_number=1
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(
            batch_size=5,
            max_tokens=800,
            attempt_adapter=first_adapter,
        ) as summarizer:
            await summarizer.summarize([_paper()])
    mock_create.assert_awaited_once()
    first = service.list_api_attempts(work_item_id="request-replay-work")[0]

    second_adapter = LiteratureExternalCallAdapter(
        service,
        work_item_id="request-replay-work",
        attempt_number=2,
        recovery_attempt=first,
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        async with AnthropicSummarizer(
            batch_size=5,
            max_tokens=800,
            attempt_adapter=second_adapter,
        ) as summarizer:
            await summarizer.summarize([_paper()])

    mock_create.assert_not_awaited()
    attempts = service.list_api_attempts(work_item_id="request-replay-work")
    assert len(attempts) == 1
    assert attempts[0].request_fingerprint == first.request_fingerprint
    assert second_adapter.replaying


@pytest.mark.anyio
async def test_batch_reporter_failure_does_not_fallback_or_refetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Post-response telemetry failure cannot create a single-paper call."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(
        service, work_item_id="telemetry-fault", attempt_number=1
    )
    reporter = MagicMock()
    reporter.record_generation.side_effect = RuntimeError("telemetry unavailable")
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"},'
        '{"paper_id": "2301.00002", "title_zh": "标题二", '
        '"ai_summary": ["b"], "ai_practice_note": "可以"}]'
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(
            batch_size=5,
            attempt_adapter=adapter,
            reporter=reporter,
        ) as summarizer:
            await summarizer.summarize([_paper("2301.00001"), _paper("2301.00002")])

    mock_create.assert_awaited_once()
    reporter.record_generation.assert_called_once()
    attempts = service.list_api_attempts(work_item_id="telemetry-fault")
    assert len(attempts) == 1
    assert attempts[0].state == "response_received"
    assert attempts[0].response_payload == response


@pytest.mark.anyio
async def test_batch_response_record_fault_does_not_fallback_to_single(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A durable-record fault is not a batch provider failure."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(service, work_item_id="batch-fault", attempt_number=1)
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"},'
        '{"paper_id": "2301.00002", "title_zh": "标题二", '
        '"ai_summary": ["b"], "ai_practice_note": "可以"}]'
    )
    original_record = service.record_api_response

    def record_then_fault(
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> NoReturn:
        original_record(
            attempt_id,
            status_code=status_code,
            response_hash=response_hash,
            response_payload=response_payload,
            retry_after_seconds=retry_after_seconds,
        )
        raise RuntimeError("record committed then failed")

    monkeypatch.setattr(service, "record_api_response", record_then_fault)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(RuntimeError, match="durable Anthropic response recording failed"):
                await summarizer.summarize([_paper("2301.00001"), _paper("2301.00002")])

    mock_create.assert_awaited_once()
    attempt = service.list_api_attempts(work_item_id="batch-fault")[0]
    assert attempt.state == "response_received"
    assert attempt.response_payload == response


@pytest.mark.anyio
@pytest.mark.parametrize("fault", [KeyboardInterrupt("stop"), asyncio.CancelledError()])
async def test_batch_response_record_base_exception_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: BaseException,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(service, work_item_id="batch-base", attempt_number=1)
    response = (
        '[{"paper_id": "2301.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    original_record = service.record_api_response

    def record_then_fault(
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> NoReturn:
        original_record(
            attempt_id,
            status_code=status_code,
            response_hash=response_hash,
            response_payload=response_payload,
            retry_after_seconds=retry_after_seconds,
        )
        raise fault

    monkeypatch.setattr(service, "record_api_response", record_then_fault)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message(response)
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(type(fault)):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempt = service.list_api_attempts(work_item_id="batch-base")[0]
    assert attempt.state == "response_received"
    assert attempt.response_payload == response


@pytest.mark.anyio
async def test_anthropic_timeout_is_unknown_without_single_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(service, work_item_id="timeout-work", attempt_number=1)
    timeout = anthropic.APITimeoutError(httpx.Request("POST", "https://example.test"))
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=timeout),
    ) as mock_create:
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(ExternalCallFailure):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempt = service.list_api_attempts(work_item_id="timeout-work")[0]
    assert attempt.state == "unknown"
    assert attempt.error_kind == "timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fault", "error_kind"),
    [
        (asyncio.CancelledError("provider cancelled"), "cancelled"),
        (KeyboardInterrupt("worker interrupted"), "request_uncertain"),
    ],
)
async def test_anthropic_base_exception_is_fenced_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: BaseException,
    error_kind: str,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(
        service, work_item_id="base-exception-work", attempt_number=1
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=fault),
    ) as mock_create:
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(type(fault)):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempt = service.list_api_attempts(work_item_id="base-exception-work")[0]
    assert attempt.state == "unknown"
    assert attempt.error_kind == error_kind
    assert attempt.error_message == str(fault)
    assert attempt.status_code is None
    assert attempt.response_hash is None
    assert attempt.response_payload is None
    assert attempt.response_received_at is None
    assert attempt.completed_at is not None
    assert attempt.retry_after_seconds == 60


@pytest.mark.anyio
@pytest.mark.parametrize("secondary_kind", ["mark", "metric"])
async def test_provider_failure_secondary_fault_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    secondary_kind: str,
) -> None:
    """Attempt/metric failures cannot turn a provider error into a single call."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(
        service, work_item_id=f"provider-secondary-{secondary_kind}", attempt_number=1
    )
    provider_error = RuntimeError("provider failed")
    if secondary_kind == "mark":

        def mark_failure(*_args: object, **_kwargs: object) -> NoReturn:
            raise RuntimeError("mark failed")

        monkeypatch.setattr(AnthropicSummarizer, "_mark_exception", mark_failure)
    else:

        def metric_failure(self: AnthropicSummarizer) -> NoReturn:
            raise RuntimeError("failed metric")

        monkeypatch.setattr(AnthropicSummarizer, "_record_failed", metric_failure)

    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=provider_error),
    ) as mock_create:
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(DurableAttemptPersistenceFailure):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempts = service.list_api_attempts(work_item_id=f"provider-secondary-{secondary_kind}")
    assert len(attempts) == 1
    if secondary_kind == "mark":
        recovery_adapter = LiteratureExternalCallAdapter(
            service,
            work_item_id=f"provider-secondary-{secondary_kind}",
            attempt_number=2,
            recovery_attempt=attempts[0],
        )
        with patch(
            "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
        ) as recovery_create:
            async with AnthropicSummarizer(
                batch_size=5, attempt_adapter=recovery_adapter
            ) as summarizer:
                with pytest.raises(ExternalCallFailure, match="lacks replayable"):
                    await summarizer.summarize([_paper()])
        recovery_create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("primary_kind", "secondary_kind"),
    [
        ("cancelled", "mark"),
        ("cancelled", "metric"),
        ("keyboard", "mark"),
        ("keyboard", "metric"),
    ],
)
async def test_provider_base_exception_secondary_fault_preserves_primary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    primary_kind: str,
    secondary_kind: str,
) -> None:
    """Cancellation/interrupt identity survives durable and metric faults."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    work_item_id = f"provider-base-{primary_kind}-{secondary_kind}"
    adapter = LiteratureExternalCallAdapter(service, work_item_id=work_item_id, attempt_number=1)
    primary = (
        asyncio.CancelledError("provider cancelled")
        if primary_kind == "cancelled"
        else KeyboardInterrupt("provider interrupted")
    )
    if secondary_kind == "mark":

        def mark_failure(*_args: object, **_kwargs: object) -> NoReturn:
            raise RuntimeError("mark failed")

        monkeypatch.setattr(AnthropicSummarizer, "_mark_exception", mark_failure)
    else:

        def metric_failure(self: AnthropicSummarizer) -> NoReturn:
            raise RuntimeError("failed metric")

        monkeypatch.setattr(AnthropicSummarizer, "_record_failed", metric_failure)

    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=primary),
    ) as mock_create:
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(type(primary)) as raised:
                await summarizer.summarize([_paper()])

    assert raised.value is primary
    mock_create.assert_awaited_once()
    attempts = service.list_api_attempts(work_item_id=work_item_id)
    assert len(attempts) == 1
    if secondary_kind == "mark":
        assert attempts[0].state == "started"
    else:
        assert attempts[0].state == "unknown"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fault", "error_kind"),
    [
        (asyncio.CancelledError("response extraction cancelled"), "cancelled"),
        (RuntimeError("response extraction failed"), "response_processing_error"),
    ],
)
async def test_anthropic_response_extraction_failure_is_fenced_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: BaseException,
    error_kind: str,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    adapter = LiteratureExternalCallAdapter(
        service, work_item_id="response-extraction-work", attempt_number=1
    )

    def extract_failure(_message: object) -> str:
        raise fault

    monkeypatch.setattr(AnthropicSummarizer, "_text_from_message", staticmethod(extract_failure))
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = _message("response exists")
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=adapter) as summarizer:
            with pytest.raises(type(fault)):
                await summarizer.summarize([_paper()])

    mock_create.assert_awaited_once()
    attempts = service.list_api_attempts(work_item_id="response-extraction-work")
    assert len(attempts) == 1
    assert attempts[0].state == "unknown"
    assert attempts[0].error_kind == error_kind
    assert attempts[0].response_payload is None
    assert attempts[0].response_hash is None
    assert attempts[0].response_received_at is None
    assert attempts[0].completed_at is not None


@pytest.mark.anyio
async def test_matching_unknown_anthropic_attempt_without_payload_does_not_refetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    first_adapter = LiteratureExternalCallAdapter(
        service,
        work_item_id="unknown-recovery-work",
        attempt_number=1,
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(
            side_effect=anthropic.APITimeoutError(httpx.Request("POST", "https://example.test"))
        ),
    ):
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=first_adapter) as summarizer:
            with pytest.raises(ExternalCallFailure):
                await summarizer.summarize([_paper()])

    recovery = service.list_api_attempts(work_item_id="unknown-recovery-work")[0]
    assert recovery.state == "unknown"
    second_adapter = LiteratureExternalCallAdapter(
        service,
        work_item_id="unknown-recovery-work",
        attempt_number=2,
        recovery_attempt=recovery,
    )
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create", new_callable=AsyncMock
    ) as mock_create:
        async with AnthropicSummarizer(batch_size=5, attempt_adapter=second_adapter) as summarizer:
            with pytest.raises(ExternalCallFailure, match="lacks replayable response evidence"):
                await summarizer.summarize([_paper()])
    mock_create.assert_not_awaited()


@pytest.mark.anyio
async def test_cache_skips_already_summarized_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AINRF_LITERATURE_MODEL", "claude-sonnet-4-5")

    paper = _paper()
    paper.title_zh = "已有标题"
    paper.ai_summary = "- a\n- b\n- c"
    paper.summary_version = "v1:claude-sonnet-4-5"

    async with AnthropicSummarizer(batch_size=5) as summarizer:
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
        async with AnthropicSummarizer(batch_size=5) as summarizer:
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
        async with AnthropicSummarizer() as summarizer:
            await summarizer.summarize([paper])

    mock_create.assert_not_awaited()
    assert paper.title_zh is None

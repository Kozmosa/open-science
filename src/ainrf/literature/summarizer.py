"""Anthropic SDK based paper summarizer with batching and cache-aware skipping."""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import logging
import os
import time
from datetime import UTC
from typing import TYPE_CHECKING, NoReturn

import anthropic
import httpx
import json_repair

from ainrf.literature.attempts import (
    ExternalCallAttempt,
    ExternalCallRecoveryBlocked,
    LiteratureExternalCallAdapter,
)
from ainrf.literature.models import LiteraturePaper

if TYPE_CHECKING:
    from anthropic.types import MessageParam

    from ainrf.observability.protocol import ObservabilityReporter

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_MAX_TOKENS = 800
SUMMARY_PROMPT_VERSION = "v1"


class ExternalCallFailure(RuntimeError):
    """A provider failure whose durable attempt must be reconciled by the worker."""

    def __init__(self, message: str, *, state: str) -> None:
        super().__init__(message)
        self.state = state


class DurableAttemptPersistenceFailure(ExternalCallFailure):
    """The provider response exists, but recording its evidence failed.

    This is intentionally an ``ExternalCallFailure`` so the worker preserves
    the original work-item failure, while the batch path can distinguish it
    from a provider failure and must not issue fallback single-paper calls.
    """

    def __init__(self, message: str, *, state: str) -> None:
        super().__init__(message, state=state)


class ResponseProcessingFailure(ExternalCallFailure):
    """The provider returned, but local response handling could not finish."""

    def __init__(self, message: str, *, state: str) -> None:
        super().__init__(message, state=state)


# Falls back through the same env keys the rest of the codebase uses.
FALLBACK_MODEL = "claude-sonnet-4-5"

BATCH_SUMMARIZE_PROMPT = """你是一个学术文献摘要助手。请对以下论文列表做提炼，对每篇论文输出一个 JSON 对象：

1. 将标题翻译为中文（简洁准确，不超过 40 字）
2. 写 3 条"重点概要"（每条 1 句话，分别覆盖核心发现、方法创新、实践意义，用中文）
3. 写 1 条"实践提醒"（面向研究者的一句话行动建议，以"可以"开头，用中文）

输出格式为 JSON 数组，每个元素必须包含 paper_id 字段以便对应：
[
  {{
    "paper_id": "arxiv id",
    "title_zh": "...",
    "ai_summary": ["...", "...", "..."],
    "ai_practice_note": "..."
  }},
  ...
]

论文列表（按顺序）：
{papers}"""


def _select_model() -> str:
    return (
        os.environ.get("AINRF_LITERATURE_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        or FALLBACK_MODEL
    )


def _api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


def _base_url() -> str | None:
    return os.environ.get("ANTHROPIC_BASE_URL")


def _summary_version(model: str) -> str:
    return f"{SUMMARY_PROMPT_VERSION}:{model}"


def _paper_prompt_block(index: int, paper: LiteraturePaper) -> str:
    return (
        f"[{index}] paper_id: {paper.paper_id}\n"
        f"title: {paper.title}\n"
        f"authors: {', '.join(paper.authors[:5])}\n"
        f"abstract: {paper.abstract[:2000]}\n"
    )


def _parse_json(text: str) -> dict | list | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        repaired = json_repair.repair_json(text, return_objects=True)
    except Exception:
        return None
    return repaired if isinstance(repaired, (dict, list)) else None


def _extract_json_list(text: str) -> list[dict] | None:
    parsed = _parse_json(text)
    return parsed if isinstance(parsed, list) else None


def _extract_json_object(text: str) -> dict | None:
    parsed = _parse_json(text)
    return parsed if isinstance(parsed, dict) else None


def _apply_summary(paper: LiteraturePaper, result: dict, model: str) -> None:
    paper.title_zh = result.get("title_zh")
    bullets = result.get("ai_summary", [])
    if isinstance(bullets, list):
        paper.ai_summary = "\n".join(f"- {s}" for s in bullets if isinstance(s, str))
    paper.ai_practice_note = result.get("ai_practice_note")
    paper.summary_version = _summary_version(model)
    paper.summary_model = model


class AnthropicSummarizer:
    """Summarize papers via Anthropic-compatible Messages API.

    - Skips papers whose cached summary_version matches the current model/prompt.
    - Processes papers in batches for lower cost/latency.
    - Falls back to one-paper-per-call if a batch fails to parse.
    """

    def __init__(
        self,
        *,
        reporter: ObservabilityReporter | None = None,
        trace_id: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        attempt_adapter: LiteratureExternalCallAdapter | None = None,
    ) -> None:
        self._reporter = reporter
        self._trace_id = trace_id or "lit-unknown"
        self._batch_size = max(1, batch_size)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._max_tokens = max_tokens
        self._attempt_adapter = attempt_adapter
        self._model = _select_model()
        self._summary_version = _summary_version(self._model)
        api_key = _api_key()
        base_url = _base_url()
        self._client: anthropic.AsyncAnthropic | None = None
        if api_key:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        else:
            logger.warning("anthropic api key not configured; summarization will be skipped")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def __aenter__(self) -> AnthropicSummarizer:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def _need_summary(self, paper: LiteraturePaper) -> bool:
        return not (
            paper.title_zh and paper.ai_summary and paper.summary_version == self._summary_version
        )

    async def summarize(self, papers: list[LiteraturePaper]) -> None:
        """Summarize all papers that are not already cached."""
        if self._client is None:
            return

        to_summarize = [p for p in papers if self._need_summary(p)]
        if not to_summarize:
            logger.debug("all %d papers already cached; skipping summarization", len(papers))
            return

        logger.info(
            "summarizing papers: total=%d need_summary=%d batch_size=%d model=%s",
            len(papers),
            len(to_summarize),
            self._batch_size,
            self._model,
        )

        for i in range(0, len(to_summarize), self._batch_size):
            batch = to_summarize[i : i + self._batch_size]
            await self._summarize_batch(batch)

    async def _summarize_batch(self, batch: list[LiteraturePaper]) -> None:
        recovery = (
            self._attempt_adapter.recovery_attempt if self._attempt_adapter is not None else None
        )
        if len(batch) == 1 and recovery is not None and recovery.operation == "summary.single":
            await self._summarize_single(batch[0])
            return
        async with self._semaphore:
            t_start = time.monotonic()
            primary: BaseException | None = None
            try:
                try:
                    text = await self._call_llm_batch(batch)
                except ExternalCallFailure:
                    raise
                except Exception as exc:
                    logger.warning(
                        "batch summarization failed; falling back to single-paper calls: %s", exc
                    )
                    await self._fallback_single(batch)
                    return

                try:
                    results = _extract_json_list(text)
                except ExternalCallFailure:
                    raise
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        self._latest_attempt(), exc, "local batch response parsing failed"
                    )
                if not results:
                    logger.warning("batch summarization returned unparsable JSON")
                    self._mark_definitive("invalid_response", "Batch response was not a JSON list")
                    if self._attempt_adapter is not None:
                        raise ExternalCallFailure(
                            "durable batch response remains unparsable",
                            state="definitive_failure",
                        )
                    await self._fallback_single(batch)
                    return

                try:
                    result_by_id = {
                        str(r.get("paper_id")): r
                        for r in results
                        if isinstance(r, dict) and r.get("paper_id")
                    }
                    missing = [paper for paper in batch if paper.paper_id not in result_by_id]
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        self._latest_attempt(), exc, "local batch response processing failed"
                    )
                if missing:
                    logger.warning("%d papers missing from batch response", len(missing))
                    if self._attempt_adapter is not None:
                        self._mark_definitive(
                            "missing_paper",
                            f"Batch response omitted {len(missing)} requested paper(s)",
                        )
                        raise ExternalCallFailure(
                            "durable batch response omitted requested papers",
                            state="definitive_failure",
                        )
                try:
                    for paper in batch:
                        result = result_by_id.get(paper.paper_id)
                        if result:
                            _apply_summary(paper, result, self._model)
                            self._record_success(paper)
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        self._latest_attempt(), exc, "local batch response processing failed"
                    )
                if missing:
                    await self._fallback_single(missing)
            except BaseException as exc:
                primary = exc
                raise
            finally:
                self._observe_duration_preserving(time.monotonic() - t_start, primary)

    def _latest_attempt(self) -> ExternalCallAttempt | None:
        if self._attempt_adapter is None or not self._attempt_adapter.attempts:
            return None
        return self._attempt_adapter.attempts[-1]

    def _fence_response_processing_failure(
        self,
        attempt: ExternalCallAttempt | None,
        exc: BaseException,
    ) -> str:
        if isinstance(exc, asyncio.CancelledError):
            error_kind = "cancelled"
        elif isinstance(exc, Exception):
            error_kind = "response_processing_error"
        else:
            error_kind = "request_uncertain"
        if attempt is None or self._attempt_adapter is None:
            return "unknown"
        current = self._attempt_adapter.fence_response_boundary(
            attempt,
            error_kind=error_kind,
            error_message=str(exc) or type(exc).__name__,
        )
        return current.state if current is not None else "unknown"

    def _raise_provider_failure(
        self,
        attempt: ExternalCallAttempt | None,
        exc: BaseException,
    ) -> NoReturn:
        """Convert provider failures without allowing secondary faults to mask them."""

        state = "unknown"
        secondary: BaseException | None = None
        try:
            state = self._mark_exception(attempt, exc)
        except BaseException as fence_error:
            secondary = fence_error
            self._fence_provider_failure(attempt, exc)
            logger.warning(
                "durable Literature provider failure recording failed: %s",
                fence_error,
                exc_info=True,
            )
        try:
            self._record_failed()
        except BaseException as metric_error:
            if secondary is None:
                secondary = metric_error
            logger.warning(
                "Literature failure metric recording failed: %s", metric_error, exc_info=True
            )
        if not isinstance(exc, Exception):
            raise exc
        if secondary is not None:
            failure = DurableAttemptPersistenceFailure(
                "durable Literature provider failure recording failed",
                state=state,
            )
            failure.add_note(f"primary provider error: {str(exc) or type(exc).__name__}")
            raise failure from secondary
        raise ExternalCallFailure(str(exc) or type(exc).__name__, state=state) from exc

    def _fence_provider_failure(
        self,
        attempt: ExternalCallAttempt | None,
        exc: BaseException,
    ) -> None:
        """Warn about a failed secondary fence without changing attempt state.

        A provider exception has already crossed the external-call seam.  A
        failed attempt/telemetry write is secondary diagnostic information; a
        best-effort ``unknown`` transition here could itself fail or turn the
        recovery row into a new, misleading outcome.  The matching started
        attempt remains a recovery block, so this path must not issue another
        provider request.
        """

        if attempt is None or self._attempt_adapter is None:
            return
        logger.warning(
            "durable Literature provider-failure fence skipped after secondary failure: "
            "attempt_id=%s provider_error=%s",
            attempt.attempt_id,
            str(exc) or type(exc).__name__,
        )

    def _raise_response_processing_failure(
        self,
        attempt: ExternalCallAttempt | None,
        exc: BaseException,
        message: str,
    ) -> NoReturn:
        """Fence local response handling while preserving the primary fault."""

        state = "unknown"
        secondary: BaseException | None = None
        try:
            state = self._fence_response_processing_failure(attempt, exc)
        except BaseException as fence_error:
            secondary = fence_error
            logger.warning(
                "durable Literature response fence failed: %s", fence_error, exc_info=True
            )
        try:
            self._record_failed()
        except BaseException as metric_error:
            if secondary is None:
                secondary = metric_error
            logger.warning(
                "Literature failure metric recording failed: %s", metric_error, exc_info=True
            )
        if not isinstance(exc, Exception):
            raise exc
        if secondary is not None:
            failure = DurableAttemptPersistenceFailure(
                "durable Literature response-failure recording failed",
                state=state,
            )
            failure.add_note(f"primary response-processing error: {str(exc) or type(exc).__name__}")
            raise failure from secondary
        raise ResponseProcessingFailure(message, state=state) from exc

    def _observe_duration_preserving(
        self,
        elapsed: float,
        primary: BaseException | None,
    ) -> None:
        """Keep a secondary telemetry BaseException from replacing a primary fault."""

        try:
            self._observe_duration(elapsed)
        except BaseException as secondary:
            if primary is None:
                raise
            logger.warning(
                "Literature duration telemetry failed while handling another error: %s",
                secondary,
                exc_info=True,
            )
            primary.add_note(f"secondary duration telemetry error: {str(secondary)}")

    @staticmethod
    def _text_from_message(message: object) -> str:
        content = getattr(message, "content", [])
        if not content:
            return ""
        return str(getattr(content[0], "text", ""))

    def _provider_request(self, messages: list[MessageParam]) -> dict[str, object]:
        """Describe every response-affecting argument sent to Anthropic."""

        if self._client is None:
            raise RuntimeError("anthropic client is not configured")
        api_version = self._client.default_headers.get("anthropic-version")
        return {
            "base_url": str(self._client.base_url),
            "path": "/v1/messages",
            "api_version": api_version if isinstance(api_version, str) else None,
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }

    async def _call_llm_batch(self, batch: list[LiteraturePaper]) -> str:
        if self._client is None:
            raise RuntimeError("anthropic client is not configured")

        blocks = "\n---\n".join(
            _paper_prompt_block(idx, paper) for idx, paper in enumerate(batch, start=1)
        )
        prompt = BATCH_SUMMARIZE_PROMPT.format(papers=blocks)
        messages: list[MessageParam] = [{"role": "user", "content": prompt}]
        try:
            attempt = self._begin_attempt(
                operation="summary.batch",
                request=self._provider_request(messages),
            )
        except ExternalCallRecoveryBlocked as exc:
            raise ExternalCallFailure(str(exc), state="unknown") from exc
        except ExternalCallFailure:
            raise
        except Exception as exc:
            raise DurableAttemptPersistenceFailure(
                "durable Anthropic batch attempt creation failed",
                state="unknown",
            ) from exc
        if attempt is not None and attempt.response_payload is not None:
            return attempt.response_payload
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=messages,
            )
        except BaseException as exc:
            self._raise_provider_failure(attempt, exc)
        try:
            response_text = self._text_from_message(message)
            self._record_response(attempt, response_text)
            usage = getattr(message, "usage", None)
            self._record_generation(
                paper_ids=[p.paper_id for p in batch],
                usage=usage,
            )
        except ExternalCallFailure:
            raise
        except BaseException as exc:
            self._raise_response_processing_failure(
                attempt, exc, "local Anthropic response processing failed"
            )
        return response_text

    async def _fallback_single(self, papers: list[LiteraturePaper]) -> None:
        for paper in papers:
            await self._summarize_single(paper)

    async def _summarize_single(self, paper: LiteraturePaper) -> None:
        if self._client is None:
            return

        prompt = (
            f"论文标题: {paper.title}\n"
            f"摘要: {paper.abstract[:2000]}\n"
            f"作者: {', '.join(paper.authors[:5])}\n\n"
            '请输出 JSON：{"title_zh": "...", "ai_summary": ["...", "...", "..."], "ai_practice_note": "..."}'
        )
        messages: list[MessageParam] = [{"role": "user", "content": prompt}]
        t_start = time.monotonic()
        primary: BaseException | None = None
        try:
            try:
                attempt = self._begin_attempt(
                    operation="summary.single",
                    request=self._provider_request(messages),
                )
            except ExternalCallRecoveryBlocked as exc:
                raise ExternalCallFailure(str(exc), state="unknown") from exc
            except ExternalCallFailure:
                raise
            except Exception as exc:
                raise DurableAttemptPersistenceFailure(
                    "durable Anthropic single attempt creation failed",
                    state="unknown",
                ) from exc
            if attempt is not None and attempt.response_payload is not None:
                response_text = attempt.response_payload
                try:
                    result = _extract_json_object(response_text)
                    if result:
                        _apply_summary(paper, result, self._model)
                        self._record_success(paper)
                    else:
                        self._record_failed()
                except ExternalCallFailure:
                    raise
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        attempt, exc, "local single response processing failed"
                    )
                return
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=messages,
                )
            except BaseException as exc:
                logger.error(
                    "single-paper summarization failed: paper_id=%s error=%s", paper.paper_id, exc
                )
                self._raise_provider_failure(attempt, exc)
            else:
                try:
                    response_text = self._text_from_message(message)
                    self._record_response(attempt, response_text)
                    usage = getattr(message, "usage", None)
                    self._record_generation(paper_ids=[paper.paper_id], usage=usage)
                except ExternalCallFailure:
                    raise
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        attempt, exc, "local Anthropic response processing failed"
                    )
                try:
                    result = _extract_json_object(response_text)
                    if result:
                        _apply_summary(paper, result, self._model)
                        self._record_success(paper)
                    else:
                        self._record_failed()
                except ExternalCallFailure:
                    raise
                except BaseException as exc:
                    self._raise_response_processing_failure(
                        attempt, exc, "local single response processing failed"
                    )
        except BaseException as exc:
            primary = exc
            raise
        finally:
            self._observe_duration_preserving(time.monotonic() - t_start, primary)

    def _begin_attempt(
        self,
        *,
        operation: str,
        request: dict[str, object],
    ) -> ExternalCallAttempt | None:
        if self._attempt_adapter is None:
            return None
        return self._attempt_adapter.begin(
            provider="anthropic",
            operation=operation,
            request=request,
        )

    def _record_response(self, attempt: ExternalCallAttempt | None, response_text: str) -> None:
        if attempt is None or self._attempt_adapter is None:
            return
        response_hash = hashlib.sha256(response_text.encode()).hexdigest()
        try:
            self._attempt_adapter.store.record_api_response(
                attempt.attempt_id,
                status_code=200,
                response_hash=response_hash,
                response_payload=response_text,
            )
        except BaseException as exc:
            secondary: BaseException | None = None
            try:
                current = self._attempt_adapter.fence_response_boundary(
                    attempt,
                    error_kind="response_record_error",
                    error_message=str(exc) or type(exc).__name__,
                )
            except BaseException as fence_error:
                current = attempt
                secondary = fence_error
                logger.warning(
                    "durable Anthropic response fence failed: %s", fence_error, exc_info=True
                )
            if not isinstance(exc, Exception):
                raise exc
            if secondary is not None:
                failure = DurableAttemptPersistenceFailure(
                    "durable Anthropic response recording failed",
                    state=current.state if current is not None else "unknown",
                )
                failure.add_note(f"primary response-record error: {str(exc)}")
                raise failure from secondary
            state = current.state if current is not None else "unknown"
            raise DurableAttemptPersistenceFailure(
                "durable Anthropic response recording failed",
                state=state,
            ) from exc

    def _mark_definitive(self, kind: str, message: str) -> None:
        if self._attempt_adapter is None or not self._attempt_adapter.attempts:
            return
        attempt = self._attempt_adapter.attempts[-1]
        try:
            self._attempt_adapter.store.mark_api_definitive_failure(
                attempt.attempt_id,
                error_kind=kind,
                error_message=message,
            )
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            raise DurableAttemptPersistenceFailure(
                "durable Anthropic definitive-failure recording failed",
                state="unknown",
            ) from exc

    def _mark_unknown(self, attempt: ExternalCallAttempt | None, kind: str, message: str) -> str:
        if attempt is None or self._attempt_adapter is None:
            return "unknown"
        self._attempt_adapter.store.mark_api_unknown(
            attempt.attempt_id,
            error_kind=kind,
            error_message=message,
            retry_after_seconds=60,
        )
        return "unknown"

    def _mark_exception(self, attempt: ExternalCallAttempt | None, exc: BaseException) -> str:
        message = str(exc) or type(exc).__name__
        if isinstance(exc, asyncio.CancelledError):
            return self._mark_unknown(attempt, "cancelled", message)
        if not isinstance(exc, Exception):
            return self._mark_unknown(attempt, "request_uncertain", message)
        if isinstance(
            exc,
            (
                TimeoutError,
                httpx.TimeoutException,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            ),
        ):
            error_kind = (
                "timeout"
                if isinstance(
                    exc, (TimeoutError, httpx.TimeoutException, anthropic.APITimeoutError)
                )
                else "connection_error"
            )
            return self._mark_unknown(attempt, error_kind, message)
        if attempt is None or self._attempt_adapter is None:
            return "retryable_failure"
        if isinstance(exc, anthropic.BadRequestError):
            self._attempt_adapter.store.mark_api_definitive_failure(
                attempt.attempt_id,
                error_kind="invalid_request",
                error_message=message,
                status_code=getattr(exc, "status_code", None),
            )
            return "definitive_failure"
        if isinstance(exc, anthropic.RateLimitError):
            retry_after_value = _retry_after_seconds(exc)
            retry_after = retry_after_value if retry_after_value is not None else 60
            self._attempt_adapter.store.mark_api_retryable_failure(
                attempt.attempt_id,
                error_kind="rate_limited",
                error_message=message,
                retry_after_seconds=retry_after,
                status_code=getattr(exc, "status_code", None),
            )
            return "retryable_failure"
        status_code = getattr(exc, "status_code", None)
        if isinstance(exc, anthropic.APIStatusError) and isinstance(status_code, int):
            if status_code < 500:
                if status_code == 429:
                    retry_after_value = _retry_after_seconds(exc)
                    self._attempt_adapter.store.mark_api_retryable_failure(
                        attempt.attempt_id,
                        error_kind="rate_limited",
                        error_message=message,
                        retry_after_seconds=(
                            retry_after_value if retry_after_value is not None else 60
                        ),
                        status_code=status_code,
                    )
                    return "retryable_failure"
                self._attempt_adapter.store.mark_api_definitive_failure(
                    attempt.attempt_id,
                    error_kind="http_error",
                    error_message=message,
                    status_code=status_code,
                )
                return "definitive_failure"
        retry_after_value = _retry_after_seconds(exc)
        self._attempt_adapter.store.mark_api_retryable_failure(
            attempt.attempt_id,
            error_kind="provider_error",
            error_message=message,
            retry_after_seconds=(retry_after_value if retry_after_value is not None else 60),
            status_code=status_code,
        )
        return "retryable_failure"

    def _record_success(self, paper: LiteraturePaper) -> None:
        from ainrf.telemetry.metrics import inc_counter

        try:
            inc_counter("ainrf_literature_summarize_total", {"status": "success"})
        except Exception as exc:
            logger.warning("Literature success metric recording failed: %s", exc, exc_info=True)

    def _record_failed(self) -> None:
        from ainrf.telemetry.metrics import inc_counter

        try:
            inc_counter("ainrf_literature_summarize_total", {"status": "failed"})
        except Exception as exc:
            logger.warning("Literature failure metric recording failed: %s", exc, exc_info=True)

    def _observe_duration(self, elapsed: float) -> None:
        from ainrf.telemetry.metrics import observe_histogram

        try:
            observe_histogram("ainrf_literature_summarize_duration_seconds", elapsed)
        except Exception as exc:
            logger.warning("Literature duration metric recording failed: %s", exc, exc_info=True)

    def _record_generation(
        self,
        paper_ids: list[str],
        usage: object,
    ) -> None:
        if self._reporter is None:
            return
        from ainrf.observability.protocol import NullReporter

        if isinstance(self._reporter, NullReporter):
            return

        usage_details: dict[str, int] = {}
        if usage is not None:
            for attr in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                value = getattr(usage, attr, None)
                if isinstance(value, int):
                    usage_details[attr] = value

        try:
            self._reporter.record_generation(
                trace_id=self._trace_id,
                name=f"summarize-batch-{self._trace_id}",
                model=self._model,
                usage_details=usage_details or None,
                input={"paper_ids": paper_ids},
                output={"model": self._model},
            )
        except Exception as exc:
            # The provider response and durable response boundary are already
            # accepted.  Local observability must not turn that accepted
            # response into a batch failure or trigger a second provider call.
            logger.warning("literature generation telemetry failed: %s", exc, exc_info=True)


def _retry_after_seconds(exc: object) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        try:
            retry_at = email.utils.parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0, int(retry_at.timestamp() - time.time()))

"""Anthropic SDK based paper summarizer with batching and cache-aware skipping."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

import anthropic
import json_repair

from ainrf.literature.models import LiteraturePaper

if TYPE_CHECKING:
    from ainrf.observability.protocol import ObservabilityReporter

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_MAX_TOKENS = 800
SUMMARY_PROMPT_VERSION = "v1"

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
    ) -> None:
        self._reporter = reporter
        self._trace_id = trace_id or "lit-unknown"
        self._batch_size = max(1, batch_size)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._max_tokens = max_tokens
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
        async with self._semaphore:
            t_start = time.monotonic()
            try:
                text = await self._call_llm_batch(batch)
            except Exception as exc:
                logger.warning(
                    "batch summarization failed; falling back to single-paper calls: %s", exc
                )
                await self._fallback_single(batch)
                return
            finally:
                self._observe_duration(time.monotonic() - t_start)

            results = _extract_json_list(text)
            if not results:
                logger.warning("batch summarization returned unparsable JSON; falling back")
                await self._fallback_single(batch)
                return

            result_by_id = {
                str(r.get("paper_id")): r
                for r in results
                if isinstance(r, dict) and r.get("paper_id")
            }
            missing = []
            for paper in batch:
                result = result_by_id.get(paper.paper_id)
                if result:
                    _apply_summary(paper, result, self._model)
                    self._record_success(paper)
                else:
                    missing.append(paper)
            if missing:
                logger.warning("%d papers missing from batch response; falling back", len(missing))
                await self._fallback_single(missing)

    @staticmethod
    def _text_from_message(message: object) -> str:
        content = getattr(message, "content", [])
        if not content:
            return ""
        return str(getattr(content[0], "text", ""))

    async def _call_llm_batch(self, batch: list[LiteraturePaper]) -> str:
        if self._client is None:
            raise RuntimeError("anthropic client is not configured")

        blocks = "\n---\n".join(
            _paper_prompt_block(idx, paper) for idx, paper in enumerate(batch, start=1)
        )
        prompt = BATCH_SUMMARIZE_PROMPT.format(papers=blocks)

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = getattr(message, "usage", None)
        self._record_generation(
            paper_ids=[p.paper_id for p in batch],
            usage=usage,
        )
        return self._text_from_message(message)

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
        t_start = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(message, "usage", None)
            self._record_generation(paper_ids=[paper.paper_id], usage=usage)
            result = _extract_json_object(self._text_from_message(message))
            if result:
                _apply_summary(paper, result, self._model)
                self._record_success(paper)
            else:
                self._record_failed()
        except Exception as exc:
            logger.error(
                "single-paper summarization failed: paper_id=%s error=%s", paper.paper_id, exc
            )
            self._record_failed()
        finally:
            self._observe_duration(time.monotonic() - t_start)

    def _record_success(self, paper: LiteraturePaper) -> None:
        from ainrf.api.routes.metrics import inc_counter

        inc_counter("ainrf_literature_summarize_total", {"status": "success"})

    def _record_failed(self) -> None:
        from ainrf.api.routes.metrics import inc_counter

        inc_counter("ainrf_literature_summarize_total", {"status": "failed"})

    def _observe_duration(self, elapsed: float) -> None:
        from ainrf.api.routes.metrics import observe_histogram

        observe_histogram("ainrf_literature_summarize_duration_seconds", elapsed)

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

        self._reporter.record_generation(
            trace_id=self._trace_id,
            name=f"summarize-batch-{self._trace_id}",
            model=self._model,
            usage_details=usage_details or None,
            input={"paper_ids": paper_ids},
            output={"model": self._model},
        )

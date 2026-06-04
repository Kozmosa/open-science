"""arXiv fetch + LLM summarization pipeline."""

from __future__ import annotations

import asyncio
import os
import random

import arxiv
import json_repair

from ainrf.literature.models import LiteraturePaper, LiteratureSubscription

_DEFAULT_MODEL = "deepseek-v4-flash"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_RATE_DELAY_MIN = 0.1  # seconds
_RATE_DELAY_MAX = 0.3  # seconds

SUMMARIZE_PROMPT = """你是一个学术文献摘要助手。请对以下论文做提炼：

1. 将标题翻译为中文（简洁准确，不超过 40 字）
2. 写 3 条"重点概要"（每条 1 句话，分别覆盖核心发现、方法创新、实践意义，用中文）
3. 写 1 条"实践提醒"（面向研究者的一句话行动建议，以"可以"开头，用中文）

论文标题: {title}
摘要: {abstract}
作者: {authors}

请用以下 JSON 格式回复（不要输出其他内容）：
{{"title_zh": "...", "ai_summary": ["...", "...", "..."], "ai_practice_note": "..."}}"""


def _get_api_config() -> tuple[str, str, str]:
    """Returns (api_key, base_url, model) from environment or defaults."""
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    )
    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or _DEFAULT_BASE_URL
    )
    model = (
        os.environ.get("AINRF_LITERATURE_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or _DEFAULT_MODEL
    )
    return api_key, base_url, model


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code fences and trailing commas."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        repaired = json_repair.repair_json(text, return_json=True)
    except Exception:
        return None
    return repaired if isinstance(repaired, dict) else None


async def _summarize_papers(papers: list[LiteraturePaper]) -> None:
    """Call LLM API to summarize papers. Reads config from environment."""
    import httpx

    api_key, base_url, model = _get_api_config()
    if not api_key:
        return  # no API key configured, skip summarization

    for paper in papers:
        prompt = SUMMARIZE_PROMPT.format(
            title=paper.title,
            abstract=paper.abstract[:2000],
            authors=", ".join(paper.authors[:5]),
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    json={
                        "model": model,
                        "max_tokens": 500,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["content"][0]["text"]
                    result = _extract_json(text)
                    if result:
                        paper.title_zh = result.get("title_zh")
                        bullet_points = result.get("ai_summary", [])
                        paper.ai_summary = "\n".join(f"- {s}" for s in bullet_points)
                        paper.ai_practice_note = result.get("ai_practice_note")
        except Exception:
            continue
        # Rate limiting: random delay between API calls
        await asyncio.sleep(random.uniform(_RATE_DELAY_MIN, _RATE_DELAY_MAX))


def _fetch_arxiv_papers(sub: LiteratureSubscription) -> list[LiteraturePaper]:
    client = arxiv.Client()
    query_parts: list[str] = []

    if sub.keywords:
        query_parts.append("(" + " AND ".join(f'"{kw}"' for kw in sub.keywords) + ")")
    if sub.arxiv_categories:
        query_parts.append("(" + " OR ".join(f"cat:{cat}" for cat in sub.arxiv_categories) + ")")

    query = " AND ".join(query_parts) if query_parts else "all:recent"
    search = arxiv.Search(
        query=query,
        max_results=10,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    papers: list[LiteraturePaper] = []
    try:
        results = list(client.results(search))
        for result in results:
            papers.append(
                LiteraturePaper(
                    paper_id=result.entry_id.split("/")[-1].split("v")[0],
                    subscription_id=sub.subscription_id,
                    title=result.title,
                    authors=[a.name for a in result.authors],
                    abstract=result.summary,
                    published_at=result.published.isoformat(),
                    arxiv_category=result.primary_category,
                )
            )
    except Exception:
        pass
    return papers


async def fetch_for_subscription(
    sub: LiteratureSubscription,
) -> list[LiteraturePaper]:
    """Fetch papers for a single subscription.

    Queries arXiv with the subscription's keywords and categories,
    then optionally summarizes each paper via the configured LLM API.
    API configuration is read from environment variables:
    - ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / DEEPSEEK_API_KEY
    - ANTHROPIC_BASE_URL / DEEPSEEK_BASE_URL (default: https://api.deepseek.com)
    - AINRF_LITERATURE_MODEL / ANTHROPIC_MODEL (default: deepseek-v4-flash)
    """
    papers = await asyncio.to_thread(_fetch_arxiv_papers, sub)

    if papers:
        await _summarize_papers(papers)

    return papers

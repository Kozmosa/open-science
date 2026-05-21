"""arXiv fetch + Claude summarization pipeline."""

from __future__ import annotations

import json

import arxiv

from ainrf.literature.models import LiteraturePaper, LiteratureSubscription

SUMMARIZE_PROMPT = """你是一个学术文献摘要助手。请对以下论文做提炼：

1. 将标题翻译为中文（简洁准确，不超过 40 字）
2. 写 3 条"重点概要"（每条 1 句话，分别覆盖核心发现、方法创新、实践意义，用中文）
3. 写 1 条"实践提醒"（面向研究者的一句话行动建议，以"可以"开头，用中文）

论文标题: {title}
摘要: {abstract}
作者: {authors}

请用以下 JSON 格式回复（不要输出其他内容）：
{{"title_zh": "...", "ai_summary": ["...", "...", "..."], "ai_practice_note": "..."}}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _summarize_papers(papers: list[LiteraturePaper], api_key: str, base_url: str) -> None:
    """Call Claude API to summarize papers."""
    import httpx

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
                        "model": "claude-sonnet-4-6",
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


async def fetch_for_subscription(
    sub: LiteratureSubscription,
    api_key: str,
    base_url: str,
) -> list[LiteraturePaper]:
    """Fetch papers for a single subscription.

    Queries arXiv with the subscription's keywords and categories,
    then optionally summarizes each paper via the Claude API.
    """
    client = arxiv.Client()
    query_parts: list[str] = []

    if sub.keywords:
        query_parts.append("(" + " OR ".join(f'("{kw}")' for kw in sub.keywords) + ")")
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

    if papers and api_key:
        await _summarize_papers(papers, api_key, base_url)

    return papers

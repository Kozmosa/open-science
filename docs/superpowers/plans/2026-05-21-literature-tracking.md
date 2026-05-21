# Literature Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a literature tracking page (`/literature`) with subscription-based arXiv paper fetching, Claude AI summarization, and one-click task conversion.

**Architecture:** New `src/ainrf/literature/` backend module (models + service + API routes + scheduler), new `frontend/src/pages/LiteraturePage.tsx` with sidebar + card feed layout.

**Tech Stack:** Python (FastAPI, apscheduler, arxiv), React (TypeScript, Tailwind v4), SQLite

---

### Task 1: Backend Models + Schema

**Files:**
- Create: `src/ainrf/literature/__init__.py`
- Create: `src/ainrf/literature/models.py`

- [ ] **Step 1: Write `src/ainrf/literature/__init__.py`**

```python
"""Literature tracking — subscription-based paper discovery and curation."""
```

- [ ] **Step 2: Write `src/ainrf/literature/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiteratureSubscription:
    subscription_id: str = field(default_factory=_new_id)
    user_id: str = ""
    label: str = ""              # display name for this subscription
    keywords: list[str] = field(default_factory=list)
    arxiv_categories: list[str] = field(default_factory=list)
    seed_paper_ids: list[str] = field(default_factory=list)
    frequency: str = "daily"     # "daily" | "twice_daily" | "weekly"
    is_active: bool = True
    created_at: str = field(default_factory=_now_iso)
    last_fetched_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "label": self.label,
            "keywords": self.keywords,
            "arxiv_categories": self.arxiv_categories,
            "seed_paper_ids": self.seed_paper_ids,
            "frequency": self.frequency,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_fetched_at": self.last_fetched_at,
        }


@dataclass
class LiteraturePaper:
    paper_id: str = ""
    subscription_id: str = ""
    title: str = ""
    title_zh: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    journal: str | None = None
    published_at: str = ""
    arxiv_category: str = ""
    ai_summary: str | None = None
    ai_practice_note: str | None = None
    is_read: bool = False
    is_converted_to_task: bool = False
    task_id: str | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "subscription_id": self.subscription_id,
            "title": self.title,
            "title_zh": self.title_zh,
            "authors": self.authors,
            "abstract": self.abstract,
            "journal": self.journal,
            "published_at": self.published_at,
            "arxiv_category": self.arxiv_category,
            "ai_summary": self.ai_summary,
            "ai_practice_note": self.ai_practice_note,
            "is_read": self.is_read,
            "is_converted_to_task": self.is_converted_to_task,
            "task_id": self.task_id,
            "created_at": self.created_at,
        }
```

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/literature/
git commit -m "feat(literature): add literature tracking data models"
```

---

### Task 2: Literature Service + SQLite

**Files:**
- Create: `src/ainrf/literature/service.py`

- [ ] **Step 1: Write `src/ainrf/literature/service.py`**

Create `LiteratureService` class with:
- `__init__(state_root)` — sets up `_db_path = state_root / "runtime" / "literature.sqlite3"`
- `initialize()` — creates `literature_subscriptions` and `literature_papers` tables with `CREATE TABLE IF NOT EXISTS`
- `create_subscription(user_id, label, keywords, arxiv_categories, frequency)` → `LiteratureSubscription`
- `list_subscriptions(user_id)` → `list[LiteratureSubscription]`
- `delete_subscription(subscription_id)` → None
- `update_subscription(subscription_id, is_active, frequency)` → `LiteratureSubscription`
- `list_papers(user_id, subscription_id, unread_only, limit, offset)` → `list[LiteraturePaper]`
- `mark_read(paper_id)` → None
- `convert_to_task(paper_id, task_id)` → `LiteraturePaper`
- `paper_exists(paper_id)` → bool
- `insert_papers(papers: list[LiteraturePaper])` → int (count inserted)
- `json.dumps` for list fields (keywords, authors, arxiv_categories) stored as TEXT in SQLite

- [ ] **Step 2: Register in `src/ainrf/api/app.py`**

Add `from ainrf.literature.service import LiteratureService` and create instance during `create_app()`:
```python
app.state.literature_service = LiteratureService(state_root=api_config.state_root)
```

Add `await _run_sync_in_lifespan(app.state.literature_service.initialize)` in lifespan.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/literature/service.py src/ainrf/api/app.py
git commit -m "feat(literature): add LiteratureService with SQLite persistence"
```

---

### Task 3: API Routes

**Files:**
- Create: `src/ainrf/api/routes/literature.py`
- Modify: `src/ainrf/api/app.py` (register router)

- [ ] **Step 1: Write `src/ainrf/api/routes/literature.py`**

```python
from fastapi import APIRouter, HTTPException, Query, Request
from ainrf.auth.permissions import get_current_user
from ainrf.literature.service import LiteratureService

router = APIRouter(prefix="/literature", tags=["literature"])

def _get_service(request: Request) -> LiteratureService:
    svc = getattr(request.app.state, "literature_service", None)
    if svc is None:
        raise HTTPException(500, "Literature service not initialized")
    return svc

@router.get("/subscriptions")
async def list_subscriptions(request: Request):
    user = get_current_user(request)
    return {"items": [s.to_dict() for s in _get_service(request).list_subscriptions(user["id"])]}

@router.post("/subscriptions", status_code=201)
async def create_subscription(payload: dict, request: Request):
    user = get_current_user(request)
    sub = _get_service(request).create_subscription(
        user_id=user["id"],
        label=payload.get("label", ""),
        keywords=payload.get("keywords", []),
        arxiv_categories=payload.get("arxiv_categories", []),
        frequency=payload.get("frequency", "daily"),
    )
    return sub.to_dict()

@router.patch("/subscriptions/{subscription_id}")
async def update_subscription(subscription_id: str, payload: dict, request: Request):
    _get_service(request).update_subscription(subscription_id, payload.get("is_active"), payload.get("frequency"))
    return {}

@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: str, request: Request):
    _get_service(request).delete_subscription(subscription_id)

@router.get("/papers")
async def list_papers(
    request: Request,
    subscription_id: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    user = get_current_user(request)
    papers = _get_service(request).list_papers(user["id"], subscription_id, unread_only, limit, offset)
    return {"items": [p.to_dict() for p in papers]}

@router.post("/papers/{paper_id}/read", status_code=204)
async def mark_read(paper_id: str, request: Request):
    _get_service(request).mark_read(paper_id)

@router.post("/papers/{paper_id}/convert", status_code=201)
async def convert_to_task(paper_id: str, payload: dict, request: Request):
    paper = _get_service(request).convert_to_task(paper_id, payload["task_id"])
    return paper.to_dict()
```

- [ ] **Step 2: Register router in `app.py`**

Add `from ainrf.api.routes.literature import router as literature_router` and add to `ROUTERS` tuple.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/api/routes/literature.py src/ainrf/api/app.py
git commit -m "feat(literature): add literature API routes"
```

---

### Task 4: arXiv Fetch + Claude Summarize Pipeline

**Files:**
- Create: `src/ainrf/literature/fetcher.py`

- [ ] **Step 1: Install arxiv and apscheduler**

```bash
uv add arxiv apscheduler
```

- [ ] **Step 2: Write `src/ainrf/literature/fetcher.py`**

```python
"""arXiv fetch + Claude summarization pipeline."""

import asyncio
import json
from datetime import datetime, timezone

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


async def _summarize_papers(papers: list[LiteraturePaper], api_key: str, base_url: str) -> None:
    """Call Claude API to summarize papers in batches of 5."""
    import httpx

    for i in range(0, len(papers), 5):
        batch = papers[i:i + 5]
        for paper in batch:
            prompt = SUMMARIZE_PROMPT.format(
                title=paper.title,
                abstract=paper.abstract[:2000],
                authors=", ".join(paper.authors[:5]),
            )
            try:
                async with httpx.AsyncClient(timeout=30) as client:
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
                        result = json.loads(text)
                        paper.title_zh = result.get("title_zh")
                        paper.ai_summary = "\n".join(f"- {s}" for s in result.get("ai_summary", []))
                        paper.ai_practice_note = result.get("ai_practice_note")
            except Exception:
                continue


async def fetch_for_subscription(sub, api_key: str, base_url: str):
    """Fetch papers for a single subscription."""
    client = arxiv.Client()
    query_parts = []

    if sub.keywords:
        query_parts.append("(" + " OR ".join(f'"{kw}"' for kw in sub.keywords) + ")")
    if sub.arxiv_categories:
        query_parts.append("(" + " OR ".join(f"cat:{cat}" for cat in sub.arxiv_categories) + ")")

    query = " AND ".join(query_parts) if query_parts else "all:recent"
    search = arxiv.Search(query=query, max_results=10, sort_by=arxiv.SortCriterion.SubmittedDate)

    papers = []
    async for result in client.results(search):
        papers.append(LiteraturePaper(
            paper_id=result.entry_id.split("/")[-1],
            subscription_id=sub.subscription_id,
            title=result.title,
            authors=[a.name for a in result.authors],
            abstract=result.summary,
            published_at=result.published.isoformat(),
            arxiv_category=result.primary_category,
        ))

    if papers:
        await _summarize_papers(papers, api_key, base_url)

    return papers


class LiteratureScheduler:
    """Manages scheduled literature fetching."""

    def __init__(self, service, api_key: str, base_url: str):
        self._service = service
        self._api_key = api_key
        self._base_url = base_url

    async def fetch_all_active(self):
        """Fetch for all active subscriptions."""
        subs = self._service.list_active_subscriptions()
        all_papers = []
        for sub in subs:
            papers = await fetch_for_subscription(sub, self._api_key, self._base_url)
            new = [p for p in papers if not self._service.paper_exists(p.paper_id)]
            if new:
                self._service.insert_papers(new)
                all_papers.extend(new)
            self._service.update_last_fetched(sub.subscription_id)
        return all_papers
```

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/literature/fetcher.py pyproject.toml uv.lock
git commit -m "feat(literature): add arXiv fetch + Claude summarization pipeline"
```

---

### Task 5: Frontend Page + Components

**Files:**
- Create: `frontend/src/pages/LiteraturePage.tsx`
- Create: `frontend/src/components/literature/SubscriptionSidebar.tsx`
- Create: `frontend/src/components/literature/PaperFeed.tsx`
- Create: `frontend/src/components/literature/PaperCard.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/components/common/Layout.tsx` (add nav item)
- Modify: `frontend/src/api/endpoints.ts` (add API functions)

- [ ] **Step 1: Add API functions to `endpoints.ts`**

```typescript
export const getLiteratureSubscriptions = (): Promise<{ items: LiteratureSubscription[] }> =>
  api.get('/literature/subscriptions')

export const createLiteratureSubscription = (payload: Partial<LiteratureSubscription>): Promise<LiteratureSubscription> =>
  api.post('/literature/subscriptions', payload)

export const deleteLiteratureSubscription = (id: string): Promise<void> =>
  api.delete(`/literature/subscriptions/${id}`)

export const getLiteraturePapers = (params: { subscription_id?: string; unread_only?: boolean; limit?: number }): Promise<{ items: LiteraturePaper[] }> =>
  api.get(`/literature/papers?${new URLSearchParams(params as any).toString()}`)

export const markPaperRead = (paperId: string): Promise<void> =>
  api.post(`/literature/papers/${paperId}/read`, {})

export const convertPaperToTask = (paperId: string, taskId: string): Promise<LiteraturePaper> =>
  api.post(`/literature/papers/${paperId}/convert`, { task_id: taskId })
```

- [ ] **Step 2: Write LiteraturePage + components**

`LiteraturePage.tsx`: SplitPane layout — SubscriptionSidebar on left, PaperFeed on right.

`SubscriptionSidebar.tsx`: Subscription list + "New Subscription" button → opens form modal with keyword inputs, arxiv category select, frequency select.

`PaperFeed.tsx`: Vertical card list with unread filter toggle and refresh button.

`PaperCard.tsx`: Card showing arxiv_category badge, title + title_zh, journal meta, AI practice note (highlighted), AI summary (collapsible bullet points), action bar (read/original/convert to task).

- [ ] **Step 3: Add route and nav**

In `App.tsx`: `const LiteraturePage = lazy(() => import('./pages/LiteraturePage'))` and route `<Route path="/literature" element={<LiteraturePage />} />`.

In `Layout.tsx`: Add nav item for `/literature` with book icon.

- [ ] **Step 4: Type check and build**

```bash
cd frontend && node_modules/.bin/tsc -b && npx vitest run
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LiteraturePage.tsx frontend/src/components/literature/ frontend/src/App.tsx frontend/src/components/common/Layout.tsx frontend/src/api/endpoints.ts frontend/src/types/index.ts frontend/src/i18n/messages.ts
git commit -m "feat(literature): add literature tracking page with subscription sidebar and paper feed"
```

---

### Task 6: Integration Verification

- [ ] **Step 1: Run backend tests**

```bash
uv run pytest tests/ -q --tb=short --deselect tests/test_cli.py::test_serve_rejects_malformed_config_with_validation_error
```

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 3: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

- [ ] **Step 4: mkdocs build**

```bash
uv run python scripts/build_html_notes.py build
```

- [ ] **Step 5: Commit**

```bash
git add docs/LLM-Working/worklog/2026-05-21.md
git commit -m "chore: update worklog with literature tracking verification"
```

---

## Verification Checklist

1. `uv run pytest tests/ -q` — backend tests pass
2. `cd frontend && npx vitest run` — frontend tests pass (133+)
3. `cd frontend && node_modules/.bin/tsc -b` — type check passes
4. `uv run python scripts/build_html_notes.py build` — mkdocs build passes

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
    label: str = ""
    keywords: list[str] = field(default_factory=list)
    arxiv_categories: list[str] = field(default_factory=list)
    seed_paper_ids: list[str] = field(default_factory=list)
    # TODO: seed paper diffusion not yet implemented
    frequency: str = "daily"
    max_results: int = 50
    is_active: bool = True
    created_at: str = field(default_factory=_now_iso)
    last_fetched_at: str | None = None
    next_fetch_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "label": self.label,
            "keywords": self.keywords,
            "arxiv_categories": self.arxiv_categories,
            "seed_paper_ids": self.seed_paper_ids,
            "frequency": self.frequency,
            "max_results": self.max_results,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_fetched_at": self.last_fetched_at,
            "next_fetch_at": self.next_fetch_at,
        }


@dataclass
class LiteraturePaper:
    paper_id: str = ""
    title: str = ""
    title_zh: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    journal: str | None = None
    published_at: str = ""
    arxiv_category: str = ""
    ai_summary: str | None = None
    ai_practice_note: str | None = None
    summary_version: str | None = None
    summary_model: str | None = None
    # Subscription-specific state is transient; populated by list_papers joins.
    is_read: bool = False
    is_converted_to_task: bool = False
    task_id: str | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "title_zh": self.title_zh,
            "authors": self.authors,
            "abstract": self.abstract,
            "journal": self.journal,
            "published_at": self.published_at,
            "arxiv_category": self.arxiv_category,
            "ai_summary": self.ai_summary,
            "ai_practice_note": self.ai_practice_note,
            "summary_version": self.summary_version,
            "summary_model": self.summary_model,
            "is_read": self.is_read,
            "is_converted_to_task": self.is_converted_to_task,
            "task_id": self.task_id,
            "created_at": self.created_at,
        }

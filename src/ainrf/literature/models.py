from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ainrf.literature.models import LiteraturePaper, LiteratureSubscription, _now_iso


class LiteratureService:
    def __init__(self, *, state_root: Path) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "literature.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        from ainrf.db.migration import run_pending

        with self._connect() as conn:
            run_pending(conn, "literature")
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        from ainrf.db.connection import connect

        return connect(str(self._db_path))

    def create_subscription(
        self, user_id, label="", keywords=None, arxiv_categories=None, frequency="daily"
    ):
        sub = LiteratureSubscription(
            user_id=user_id,
            label=label,
            keywords=keywords or [],
            arxiv_categories=arxiv_categories or [],
            frequency=frequency,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO literature_subscriptions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    sub.subscription_id,
                    sub.user_id,
                    sub.label,
                    json.dumps(sub.keywords),
                    json.dumps(sub.arxiv_categories),
                    json.dumps(sub.seed_paper_ids),
                    sub.frequency,
                    int(sub.is_active),
                    sub.created_at,
                    sub.last_fetched_at,
                ),
            )
            conn.commit()
        return sub

    def list_subscriptions(self, user_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM literature_subscriptions WHERE user_id = ?", (user_id,)
            ).fetchall()
        return [self._row_to_sub(row) for row in rows]

    def get_subscription(self, subscription_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
        return self._row_to_sub(row) if row else None

    def list_active_subscriptions(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM literature_subscriptions WHERE is_active = 1"
            ).fetchall()
        return [self._row_to_sub(row) for row in rows]

    def delete_subscription(self, subscription_id):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM literature_papers WHERE subscription_id = ?",
                (subscription_id,),
            )
            conn.execute(
                "DELETE FROM literature_subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            )
            conn.commit()

    def update_subscription(
        self,
        subscription_id,
        label=None,
        keywords=None,
        arxiv_categories=None,
        frequency=None,
        is_active=None,
    ):
        with self._connect() as conn:
            if label is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET label = ? WHERE subscription_id = ?",
                    (label, subscription_id),
                )
            if keywords is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET keywords_json = ? WHERE subscription_id = ?",
                    (json.dumps(keywords), subscription_id),
                )
            if arxiv_categories is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET arxiv_categories_json = ? WHERE subscription_id = ?",
                    (json.dumps(arxiv_categories), subscription_id),
                )
            if frequency is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET frequency = ? WHERE subscription_id = ?",
                    (frequency, subscription_id),
                )
            if is_active is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET is_active = ? WHERE subscription_id = ?",
                    (int(is_active), subscription_id),
                )
            conn.commit()
        return self.get_subscription(subscription_id)

    def update_last_fetched(self, subscription_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE literature_subscriptions SET last_fetched_at = ? WHERE subscription_id = ?",
                (_now_iso(), subscription_id),
            )
            conn.commit()

    def list_papers(self, user_id, subscription_id=None, unread_only=False, limit=20, offset=0):
        query = """SELECT p.* FROM literature_papers p
                   JOIN literature_subscriptions s ON p.subscription_id = s.subscription_id
                   WHERE s.user_id = ?"""
        params = [user_id]
        if subscription_id:
            query += " AND p.subscription_id = ?"
            params.append(subscription_id)
        if unread_only:
            query += " AND p.is_read = 0"
        query += " ORDER BY p.published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_paper(row) for row in rows]

    def user_owns_paper(self, user_id, paper_id):
        """Check if a paper belongs to a subscription owned by the user."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM literature_papers p
                   JOIN literature_subscriptions s ON p.subscription_id = s.subscription_id
                   WHERE p.paper_id = ? AND s.user_id = ?""",
                (paper_id, user_id),
            ).fetchone()
        return row is not None

    def mark_read(self, paper_id, subscription_id=None):
        """Mark a paper as read within a specific subscription, or all copies."""
        with self._connect() as conn:
            if subscription_id:
                conn.execute(
                    "UPDATE literature_papers SET is_read = 1 WHERE paper_id = ? AND subscription_id = ?",
                    (paper_id, subscription_id),
                )
            else:
                conn.execute(
                    "UPDATE literature_papers SET is_read = 1 WHERE paper_id = ?", (paper_id,)
                )
            conn.commit()

    def convert_to_task(self, paper_id, task_id, subscription_id=None):
        with self._connect() as conn:
            if subscription_id:
                conn.execute(
                    "UPDATE literature_papers SET is_converted_to_task = 1, task_id = ? WHERE paper_id = ? AND subscription_id = ?",
                    (task_id, paper_id, subscription_id),
                )
            else:
                conn.execute(
                    "UPDATE literature_papers SET is_converted_to_task = 1, task_id = ? WHERE paper_id = ?",
                    (task_id, paper_id),
                )
            conn.commit()
            row = (
                conn.execute(
                    "SELECT * FROM literature_papers WHERE paper_id = ? AND subscription_id = ?",
                    (paper_id, subscription_id or ""),
                ).fetchone()
                if subscription_id
                else conn.execute(
                    "SELECT * FROM literature_papers WHERE paper_id = ?", (paper_id,)
                ).fetchone()
            )
        return self._row_to_paper(row) if row else None

    def paper_exists(self, paper_id, subscription_id=None):
        with self._connect() as conn:
            if subscription_id:
                row = conn.execute(
                    "SELECT 1 FROM literature_papers WHERE paper_id = ? AND subscription_id = ?",
                    (paper_id, subscription_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM literature_papers WHERE paper_id = ?", (paper_id,)
                ).fetchone()
        return row is not None

    def insert_papers(self, papers):
        count = 0
        with self._connect() as conn:
            for p in papers:
                try:
                    conn.execute(
                        """INSERT INTO literature_papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            p.paper_id,
                            p.subscription_id,
                            p.title,
                            p.title_zh,
                            json.dumps(p.authors),
                            p.abstract,
                            p.journal,
                            p.published_at,
                            p.arxiv_category,
                            p.ai_summary,
                            p.ai_practice_note,
                            int(p.is_read),
                            int(p.is_converted_to_task),
                            p.task_id,
                            p.created_at,
                            p.summary_version,
                            p.summary_model,
                        ),
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        return count

    @staticmethod
    def _row_to_sub(row) -> LiteratureSubscription:
        d = dict(row)
        return LiteratureSubscription(
            subscription_id=d["subscription_id"],
            user_id=d["user_id"],
            label=d.get("label", ""),
            keywords=json.loads(d.get("keywords_json", "[]")),
            arxiv_categories=json.loads(d.get("arxiv_categories_json", "[]")),
            seed_paper_ids=json.loads(d.get("seed_paper_ids_json", "[]")),
            frequency=d.get("frequency", "daily"),
            is_active=bool(d.get("is_active", 1)),
            created_at=d.get("created_at", ""),
            last_fetched_at=d.get("last_fetched_at"),
        )

    @staticmethod
    def _row_to_paper(row) -> LiteraturePaper:
        d = dict(row)
        return LiteraturePaper(
            paper_id=d["paper_id"],
            subscription_id=d["subscription_id"],
            title=d.get("title", ""),
            title_zh=d.get("title_zh"),
            authors=json.loads(d.get("authors_json", "[]")),
            abstract=d.get("abstract", ""),
            journal=d.get("journal"),
            published_at=d.get("published_at", ""),
            arxiv_category=d.get("arxiv_category", ""),
            ai_summary=d.get("ai_summary"),
            ai_practice_note=d.get("ai_practice_note"),
            summary_version=d.get("summary_version"),
            summary_model=d.get("summary_model"),
            is_read=bool(d.get("is_read", 0)),
            is_converted_to_task=bool(d.get("is_converted_to_task", 0)),
            task_id=d.get("task_id"),
            created_at=d.get("created_at", ""),
        )

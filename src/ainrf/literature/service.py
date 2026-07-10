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
        self,
        user_id,
        label="",
        keywords=None,
        arxiv_categories=None,
        frequency="daily",
        max_results=50,
    ):
        sub = LiteratureSubscription(
            user_id=user_id,
            label=label,
            keywords=keywords or [],
            arxiv_categories=arxiv_categories or [],
            frequency=frequency,
            max_results=max_results,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO literature_subscriptions (
                    subscription_id, user_id, label, keywords_json, arxiv_categories_json,
                    seed_paper_ids_json, frequency, is_active, created_at, last_fetched_at,
                    max_results, next_fetch_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
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
                    sub.max_results,
                    sub.next_fetch_at,
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
                "DELETE FROM literature_subscription_papers WHERE subscription_id = ?",
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
        max_results=None,
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
            if max_results is not None:
                conn.execute(
                    "UPDATE literature_subscriptions SET max_results = ? WHERE subscription_id = ?",
                    (max_results, subscription_id),
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

    def set_next_fetch_at(self, subscription_id, next_fetch_at: str | None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE literature_subscriptions SET next_fetch_at = ? WHERE subscription_id = ?",
                (next_fetch_at, subscription_id),
            )
            conn.commit()

    def upsert_papers(self, subscription_id, papers) -> int:
        """Persist papers globally and associate them with the subscription.

        Returns the number of newly associated papers for this subscription.
        """
        count = 0
        with self._connect() as conn:
            for p in papers:
                conn.execute(
                    """
                    INSERT INTO literature_papers (
                        paper_id, title, title_zh, authors_json, abstract, journal,
                        published_at, arxiv_category, ai_summary, ai_practice_note,
                        summary_version, summary_model, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                        title = excluded.title,
                        title_zh = COALESCE(excluded.title_zh, title_zh),
                        authors_json = excluded.authors_json,
                        abstract = excluded.abstract,
                        journal = COALESCE(excluded.journal, journal),
                        published_at = excluded.published_at,
                        arxiv_category = excluded.arxiv_category,
                        ai_summary = COALESCE(excluded.ai_summary, ai_summary),
                        ai_practice_note = COALESCE(excluded.ai_practice_note, ai_practice_note),
                        summary_version = COALESCE(excluded.summary_version, summary_version),
                        summary_model = COALESCE(excluded.summary_model, summary_model)
                    """,
                    (
                        p.paper_id,
                        p.title,
                        p.title_zh,
                        json.dumps(p.authors),
                        p.abstract,
                        p.journal,
                        p.published_at,
                        p.arxiv_category,
                        p.ai_summary,
                        p.ai_practice_note,
                        p.summary_version,
                        p.summary_model,
                        p.created_at,
                    ),
                )
                # Count only papers that were not already associated with this subscription.
                exists = conn.execute(
                    "SELECT 1 FROM literature_subscription_papers WHERE subscription_id = ? AND paper_id = ?",
                    (subscription_id, p.paper_id),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """
                        INSERT INTO literature_subscription_papers (
                            subscription_id, paper_id, is_read, is_converted_to_task, task_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (subscription_id, p.paper_id, 0, 0, None, _now_iso()),
                    )
                    count += 1
            conn.commit()
        return count

    def list_papers(self, user_id, subscription_id=None, unread_only=False, limit=20, offset=0):
        query = """
            SELECT p.*, sp.is_read, sp.is_converted_to_task, sp.task_id
            FROM literature_papers p
            JOIN literature_subscription_papers sp ON p.paper_id = sp.paper_id
            JOIN literature_subscriptions s ON sp.subscription_id = s.subscription_id
            WHERE s.user_id = ?
        """
        params = [user_id]
        if subscription_id:
            query += " AND sp.subscription_id = ?"
            params.append(subscription_id)
        if unread_only:
            query += " AND sp.is_read = 0"
        query += " ORDER BY p.published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_paper(row) for row in rows]

    def user_owns_paper(self, user_id, paper_id):
        """Check if a paper belongs to a subscription owned by the user."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM literature_subscription_papers sp
                   JOIN literature_subscriptions s ON sp.subscription_id = s.subscription_id
                   WHERE sp.paper_id = ? AND s.user_id = ?""",
                (paper_id, user_id),
            ).fetchone()
        return row is not None

    def mark_read(self, paper_id, subscription_id=None):
        """Mark a paper as read within a specific subscription, or all associations."""
        with self._connect() as conn:
            if subscription_id:
                conn.execute(
                    "UPDATE literature_subscription_papers SET is_read = 1 WHERE paper_id = ? AND subscription_id = ?",
                    (paper_id, subscription_id),
                )
            else:
                conn.execute(
                    "UPDATE literature_subscription_papers SET is_read = 1 WHERE paper_id = ?",
                    (paper_id,),
                )
            conn.commit()

    def convert_to_task(self, paper_id, task_id, subscription_id=None):
        with self._connect() as conn:
            if subscription_id:
                conn.execute(
                    "UPDATE literature_subscription_papers SET is_converted_to_task = 1, task_id = ? WHERE paper_id = ? AND subscription_id = ?",
                    (task_id, paper_id, subscription_id),
                )
            else:
                conn.execute(
                    "UPDATE literature_subscription_papers SET is_converted_to_task = 1, task_id = ? WHERE paper_id = ?",
                    (task_id, paper_id),
                )
            conn.commit()
            row = self._fetch_paper_with_state(conn, paper_id, subscription_id)
        return self._row_to_paper(row) if row else None

    def paper_exists(self, paper_id, subscription_id=None):
        with self._connect() as conn:
            if subscription_id:
                row = conn.execute(
                    "SELECT 1 FROM literature_subscription_papers WHERE paper_id = ? AND subscription_id = ?",
                    (paper_id, subscription_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM literature_papers WHERE paper_id = ?", (paper_id,)
                ).fetchone()
        return row is not None

    @staticmethod
    def _fetch_paper_with_state(
        conn: sqlite3.Connection, paper_id: str, subscription_id: str | None
    ):
        if subscription_id:
            return conn.execute(
                """
                SELECT p.*, sp.is_read, sp.is_converted_to_task, sp.task_id
                FROM literature_papers p
                JOIN literature_subscription_papers sp ON p.paper_id = sp.paper_id
                WHERE p.paper_id = ? AND sp.subscription_id = ?
                """,
                (paper_id, subscription_id),
            ).fetchone()
        return conn.execute(
            """
            SELECT p.*, sp.is_read, sp.is_converted_to_task, sp.task_id
            FROM literature_papers p
            JOIN literature_subscription_papers sp ON p.paper_id = sp.paper_id
            WHERE p.paper_id = ?
            LIMIT 1
            """,
            (paper_id,),
        ).fetchone()

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
            max_results=int(d.get("max_results", 50)),
            is_active=bool(d.get("is_active", 1)),
            created_at=d.get("created_at", ""),
            last_fetched_at=d.get("last_fetched_at"),
            next_fetch_at=d.get("next_fetch_at"),
        )

    @staticmethod
    def _row_to_paper(row) -> LiteraturePaper:
        d = dict(row)
        return LiteraturePaper(
            paper_id=d["paper_id"],
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

from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "literature"


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            arxiv_categories_json TEXT NOT NULL DEFAULT '[]',
            seed_paper_ids_json TEXT NOT NULL DEFAULT '[]',
            frequency TEXT NOT NULL DEFAULT 'daily',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_fetched_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_papers (
            paper_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_zh TEXT,
            authors_json TEXT NOT NULL DEFAULT '[]',
            abstract TEXT NOT NULL DEFAULT '',
            journal TEXT,
            published_at TEXT NOT NULL DEFAULT '',
            arxiv_category TEXT NOT NULL DEFAULT '',
            ai_summary TEXT,
            ai_practice_note TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_converted_to_task INTEGER NOT NULL DEFAULT 0,
            task_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (paper_id, subscription_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_papers_sub ON literature_papers(subscription_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subs_user ON literature_subscriptions(user_id)"
    )


@registry.register(_DATABASE)
def migration_002_summary_cache_fields(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        ALTER TABLE literature_papers
        ADD COLUMN summary_version TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE literature_papers
        ADD COLUMN summary_model TEXT
        """
    )

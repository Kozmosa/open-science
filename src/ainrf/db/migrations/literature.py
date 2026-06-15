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


@registry.register(_DATABASE)
def migration_003_global_papers_and_scheduler_fields(conn: sqlite3.Connection) -> None:
    """Move to global papers table + subscription-paper association.

    Also adds scheduler-related columns to literature_subscriptions.
    """
    conn.execute(
        """
        ALTER TABLE literature_subscriptions
        ADD COLUMN max_results INTEGER NOT NULL DEFAULT 50
        """
    )
    conn.execute(
        """
        ALTER TABLE literature_subscriptions
        ADD COLUMN next_fetch_at TEXT
        """
    )

    # Rename the legacy composite-key table so we can migrate its data.
    conn.execute("ALTER TABLE literature_papers RENAME TO _old_literature_papers")

    # Global paper table: one row per arXiv paper_id.
    conn.execute(
        """
        CREATE TABLE literature_papers (
            paper_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            title_zh TEXT,
            authors_json TEXT NOT NULL DEFAULT '[]',
            abstract TEXT NOT NULL DEFAULT '',
            journal TEXT,
            published_at TEXT NOT NULL DEFAULT '',
            arxiv_category TEXT NOT NULL DEFAULT '',
            ai_summary TEXT,
            ai_practice_note TEXT,
            summary_version TEXT,
            summary_model TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # Migrate paper data. For duplicate paper_ids, prefer rows that have a
    # summary (MAX picks non-null over null for these text columns).
    conn.execute(
        """
        INSERT INTO literature_papers (
            paper_id, title, title_zh, authors_json, abstract, journal,
            published_at, arxiv_category, ai_summary, ai_practice_note,
            summary_version, summary_model, created_at
        )
        SELECT
            paper_id,
            MAX(title),
            MAX(title_zh),
            MAX(authors_json),
            MAX(abstract),
            MAX(journal),
            MAX(published_at),
            MAX(arxiv_category),
            MAX(ai_summary),
            MAX(ai_practice_note),
            MAX(summary_version),
            MAX(summary_model),
            MAX(created_at)
        FROM _old_literature_papers
        GROUP BY paper_id
        """
    )

    # Per-subscription state association.
    conn.execute(
        """
        CREATE TABLE literature_subscription_papers (
            subscription_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_converted_to_task INTEGER NOT NULL DEFAULT 0,
            task_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (subscription_id, paper_id),
            FOREIGN KEY (subscription_id) REFERENCES literature_subscriptions(subscription_id),
            FOREIGN KEY (paper_id) REFERENCES literature_papers(paper_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sub_papers_sub
        ON literature_subscription_papers(subscription_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sub_papers_paper
        ON literature_subscription_papers(paper_id)
        """
    )

    # Preserve existing per-subscription read/converted state.
    conn.execute(
        """
        INSERT INTO literature_subscription_papers (
            subscription_id, paper_id, is_read, is_converted_to_task, task_id, created_at
        )
        SELECT
            subscription_id, paper_id, is_read, is_converted_to_task, task_id, created_at
        FROM _old_literature_papers
        """
    )

    conn.execute("DROP TABLE _old_literature_papers")

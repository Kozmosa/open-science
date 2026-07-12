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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_sub ON literature_papers(subscription_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_user ON literature_subscriptions(user_id)")


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


@registry.register(_DATABASE)
def migration_004_tracking_redesign(conn: sqlite3.Connection) -> None:
    """Add the durable, provider-oriented literature tracking model.

    The original subscription tables remain in place for the compatibility
    routes.  New tables deliberately use their own names so an interrupted
    upgrade cannot destroy a user's existing reading data.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS literature_topics (
            topic_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            label TEXT NOT NULL,
            include_terms_json TEXT NOT NULL DEFAULT '[]',
            exclude_terms_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            is_active INTEGER NOT NULL DEFAULT 1,
            legacy_subscription_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_matched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS literature_catalog_papers (
            paper_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL DEFAULT '[]',
            primary_category TEXT NOT NULL DEFAULT '',
            categories_json TEXT NOT NULL DEFAULT '[]',
            abstract TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            pdf_url TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            updated_at TEXT,
            current_version_id TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(provider, external_id)
        );

        CREATE TABLE IF NOT EXISTS literature_paper_versions (
            version_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            provider_version TEXT NOT NULL,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL DEFAULT '[]',
            abstract TEXT NOT NULL DEFAULT '',
            categories_json TEXT NOT NULL DEFAULT '[]',
            published_at TEXT,
            updated_at TEXT,
            content_hash TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            UNIQUE(paper_id, provider_version),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        );

        CREATE TABLE IF NOT EXISTS literature_topic_matches (
            topic_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            reason_json TEXT NOT NULL DEFAULT '[]',
            matched_at TEXT NOT NULL,
            PRIMARY KEY(topic_id, paper_id),
            FOREIGN KEY (topic_id) REFERENCES literature_topics(topic_id),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        );

        CREATE TABLE IF NOT EXISTS literature_user_paper_states (
            user_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_saved INTEGER NOT NULL DEFAULT 0,
            is_ignored INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            latest_seen_version_id TEXT,
            PRIMARY KEY(user_id, paper_id),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        );

        CREATE TABLE IF NOT EXISTS literature_checks (
            check_id TEXT PRIMARY KEY,
            user_id TEXT,
            trigger TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            window_start TEXT,
            window_end TEXT,
            scheduled_for TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            next_attempt_at TEXT,
            last_error TEXT,
            UNIQUE(request_fingerprint)
        );

        CREATE TABLE IF NOT EXISTS literature_check_scopes (
            scope_id TEXT PRIMARY KEY,
            check_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            cursor TEXT,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            etag TEXT,
            last_modified TEXT,
            response_hash TEXT,
            next_attempt_at TEXT,
            last_error TEXT,
            UNIQUE(check_id, provider, scope_key),
            FOREIGN KEY (check_id) REFERENCES literature_checks(check_id)
        );

        CREATE TABLE IF NOT EXISTS literature_source_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            check_id TEXT NOT NULL,
            scope_id TEXT,
            provider TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            content_type TEXT NOT NULL,
            body BLOB NOT NULL,
            body_hash TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            received_at TEXT NOT NULL,
            FOREIGN KEY (check_id) REFERENCES literature_checks(check_id)
        );

        CREATE TABLE IF NOT EXISTS literature_api_attempts (
            attempt_id TEXT PRIMARY KEY,
            check_id TEXT,
            work_item_id TEXT,
            provider TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,
            status_code INTEGER,
            retry_after_seconds INTEGER,
            error_kind TEXT,
            error_message TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            response_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS literature_work_items (
            work_item_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            available_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_expires_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS literature_outbox (
            outbox_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            published_at TEXT,
            publish_attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id) REFERENCES literature_work_items(work_item_id)
        );

        CREATE TABLE IF NOT EXISTS literature_summaries (
            summary_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            recipe_version TEXT NOT NULL,
            model TEXT NOT NULL,
            language TEXT NOT NULL,
            status TEXT NOT NULL,
            summary_text TEXT,
            practice_note TEXT,
            work_item_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(version_id, content_hash, recipe_version, model, language),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id),
            FOREIGN KEY (version_id) REFERENCES literature_paper_versions(version_id)
        );

        CREATE TABLE IF NOT EXISTS literature_research_task_links (
            link_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            task_id TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            last_error TEXT,
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        );

        CREATE INDEX IF NOT EXISTS idx_lit_topics_user ON literature_topics(user_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_lit_catalog_provider ON literature_catalog_papers(provider, external_id);
        CREATE INDEX IF NOT EXISTS idx_lit_matches_paper ON literature_topic_matches(paper_id);
        CREATE INDEX IF NOT EXISTS idx_lit_states_user ON literature_user_paper_states(user_id, last_seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_lit_checks_status ON literature_checks(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_lit_work_available ON literature_work_items(status, available_at);
        CREATE INDEX IF NOT EXISTS idx_lit_outbox_pending ON literature_outbox(status, created_at);
        """
    )


@registry.register(_DATABASE)
def migration_005_task_conversion_saga(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_task_sagas (
            saga_id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            task_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('pending', 'task_created', 'completed', 'failed')),
            idempotency_key TEXT NOT NULL UNIQUE,
            error_detail TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(subscription_id, paper_id, project_id, workspace_id)
        )
        """
    )

    # Migrate old subscriptions without allowing category-less legacy rows to
    # turn into an unsafe all-arXiv query.  Existing IDs remain stable.
    conn.execute(
        """
        INSERT OR IGNORE INTO literature_topics (
            topic_id, user_id, label, include_terms_json, categories_json,
            status, is_active, legacy_subscription_id, created_at, updated_at
        )
        SELECT
            subscription_id, user_id, label, keywords_json, arxiv_categories_json,
            CASE WHEN json_array_length(arxiv_categories_json) = 0 THEN 'attention_needed' ELSE 'active' END,
            CASE WHEN json_array_length(arxiv_categories_json) = 0 THEN 0 ELSE is_active END,
            subscription_id, created_at, created_at
        FROM literature_subscriptions
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO literature_catalog_papers (
            paper_id, provider, external_id, title, authors_json, primary_category,
            categories_json, abstract, source_url, pdf_url, published_at, updated_at,
            first_seen_at, last_seen_at
        )
        SELECT
            'arxiv:' || paper_id, 'arxiv', paper_id, title, authors_json, arxiv_category,
            json_array(arxiv_category), abstract,
            'https://arxiv.org/abs/' || paper_id, 'https://arxiv.org/pdf/' || paper_id,
            published_at, published_at, created_at, created_at
        FROM literature_papers
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO literature_topic_matches (topic_id, paper_id, matched_at)
        SELECT subscription_id, 'arxiv:' || paper_id, created_at
        FROM literature_subscription_papers
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO literature_user_paper_states (
            user_id, paper_id, is_read, first_seen_at, last_seen_at
        )
        SELECT s.user_id, 'arxiv:' || sp.paper_id, MAX(sp.is_read), MIN(sp.created_at), MAX(sp.created_at)
        FROM literature_subscription_papers sp
        JOIN literature_subscriptions s ON s.subscription_id = sp.subscription_id
        GROUP BY s.user_id, sp.paper_id
        """
    )

-- Generated from the current fresh-install schema. Do not edit historical migrations here.
CREATE TABLE literature_api_attempts (
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
CREATE TABLE literature_catalog_papers (
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
CREATE TABLE literature_check_scopes (
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
CREATE TABLE literature_checks (
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
CREATE TABLE literature_idempotency_requests (
            user_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, scope, idempotency_key)
        );
CREATE TABLE literature_outbox (
            outbox_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            published_at TEXT,
            publish_attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id) REFERENCES literature_work_items(work_item_id)
        );
CREATE TABLE literature_paper_versions (
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
        );
CREATE TABLE literature_research_task_intents (
            intent_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            subscription_id TEXT,
            project_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            actor_role TEXT NOT NULL DEFAULT 'member',
            task_preset TEXT NOT NULL,
            title TEXT NOT NULL,
            request_input_json TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            task_idempotency_key TEXT NOT NULL UNIQUE,
            task_id TEXT,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'creating_task', 'task_created', 'completed', 'retryable_failed')
            ),
            work_item_id TEXT NOT NULL UNIQUE REFERENCES literature_work_items(work_item_id) ON DELETE RESTRICT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            next_retry_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(user_id, paper_id, idempotency_key)
        );
CREATE TABLE literature_research_task_links (
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
CREATE TABLE literature_source_snapshots (
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
        );
CREATE TABLE literature_subscriptions (
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
        , max_results INTEGER NOT NULL DEFAULT 50, next_fetch_at TEXT);
CREATE TABLE literature_summaries (
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
CREATE TABLE literature_task_sagas (
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
        );
CREATE TABLE literature_topic_matches (
            topic_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            reason_json TEXT NOT NULL DEFAULT '[]',
            matched_at TEXT NOT NULL,
            PRIMARY KEY(topic_id, paper_id),
            FOREIGN KEY (topic_id) REFERENCES literature_topics(topic_id),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        );
CREATE TABLE literature_topics (
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
CREATE TABLE literature_user_paper_states (
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
CREATE TABLE literature_work_items (
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
CREATE INDEX idx_subs_user ON literature_subscriptions(user_id);
CREATE INDEX idx_sub_papers_sub
        ON literature_subscription_papers(subscription_id)
        ;
CREATE INDEX idx_sub_papers_paper
        ON literature_subscription_papers(paper_id)
        ;
CREATE INDEX idx_lit_topics_user ON literature_topics(user_id, is_active);
CREATE INDEX idx_lit_catalog_provider ON literature_catalog_papers(provider, external_id);
CREATE INDEX idx_lit_matches_paper ON literature_topic_matches(paper_id);
CREATE INDEX idx_lit_states_user ON literature_user_paper_states(user_id, last_seen_at DESC);
CREATE INDEX idx_lit_checks_status ON literature_checks(status, next_attempt_at);
CREATE INDEX idx_lit_work_available ON literature_work_items(status, available_at);
CREATE INDEX idx_lit_outbox_pending ON literature_outbox(status, created_at);
CREATE INDEX idx_lit_research_task_intents_recovery
        ON literature_research_task_intents(status, next_retry_at, lease_expires_at, created_at);
CREATE INDEX idx_lit_research_task_intents_paper
        ON literature_research_task_intents(user_id, paper_id, created_at DESC);
CREATE INDEX idx_literature_idempotency_created
        ON literature_idempotency_requests(created_at);

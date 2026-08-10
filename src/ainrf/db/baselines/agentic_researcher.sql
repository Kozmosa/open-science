-- Generated from the current fresh-install schema. Do not edit historical migrations here.
CREATE TABLE context_snapshots (
            context_snapshot_id TEXT PRIMARY KEY,
            context_version_id TEXT REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            fingerprint TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        , source_manifest_json TEXT NOT NULL DEFAULT '[]', byte_budget INTEGER, truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)));
CREATE TABLE conversation_submission_intents (
            submission_id TEXT PRIMARY KEY
                REFERENCES turn_submissions(submission_id) ON DELETE RESTRICT,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('create', 'retry', 'next_turn')),
            retry_of_turn_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (submission_id, task_id)
                REFERENCES turn_submissions(submission_id, task_id) ON DELETE RESTRICT,
            FOREIGN KEY (retry_of_turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            CHECK (
                (kind = 'retry' AND retry_of_turn_id IS NOT NULL)
                OR (kind != 'retry' AND retry_of_turn_id IS NULL)
            )
        );
CREATE TABLE conversation_task_authorities (
            task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
            authority TEXT NOT NULL CHECK (authority = 'conversation_v3'),
            created_at TEXT NOT NULL
        );
CREATE TABLE conversation_task_states (
            task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
            work_status TEXT NOT NULL DEFAULT 'open'
                CHECK (work_status IN ('open', 'completed', 'cancelled')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
CREATE TABLE domain_audit_events (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
CREATE TABLE "domain_idempotency_requests" (
            actor_user_id TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(actor_user_id, scope, idempotency_key)
        );
CREATE TABLE domain_maintenance_mutations (
            mutation_id TEXT PRIMARY KEY,
            maintenance_epoch INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            source TEXT NOT NULL
        , participant_id TEXT);
CREATE TABLE domain_maintenance_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            maintenance_epoch INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
            actor_id TEXT,
            reason TEXT,
            entered_at TEXT,
            exited_at TEXT
        );
INSERT INTO "domain_maintenance_state" VALUES(1,0,0,NULL,NULL,NULL,NULL);
CREATE TABLE domain_write_participants (
            participant_id TEXT PRIMARY KEY,
            participant_type TEXT NOT NULL,
            process_id INTEGER,
            observed_epoch INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'draining', 'drained', 'stopped')),
            in_flight_mutations INTEGER NOT NULL DEFAULT 0 CHECK (in_flight_mutations >= 0),
            unflushed_output_count INTEGER NOT NULL DEFAULT 0 CHECK (unflushed_output_count >= 0),
            details_json TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            drained_at TEXT,
            stopped_at TEXT
        );
CREATE TABLE engine_conversation_bindings (
            binding_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            binding_seq INTEGER NOT NULL CHECK (binding_seq > 0),
            status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
            engine_family TEXT NOT NULL CHECK (engine_family IN ('codex', 'claude')),
            engine_driver TEXT NOT NULL CHECK (engine_driver IN (
                'codex-app-server', 'claude-code', 'agent-sdk'
            )),
            native_conversation_kind TEXT NOT NULL
                CHECK (trim(native_conversation_kind) != ''),
            native_conversation_ref TEXT NOT NULL
                CHECK (trim(native_conversation_ref) != ''),
            contract_version INTEGER NOT NULL CHECK (contract_version > 0),
            provider_profile_ref TEXT,
            provider_profile_version TEXT,
            provider_profile_fingerprint TEXT,
            provenance_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(provenance_json) AND json_type(provenance_json) = 'object'),
            validation_evidence_json TEXT NOT NULL DEFAULT '{}'
                CHECK (
                    json_valid(validation_evidence_json)
                    AND json_type(validation_evidence_json) = 'object'
                ),
            created_at TEXT NOT NULL,
            validated_at TEXT,
            superseded_at TEXT,
            UNIQUE (task_id, binding_seq),
            UNIQUE (binding_id, task_id),
            CHECK (
                (status = 'active' AND superseded_at IS NULL)
                OR (status = 'superseded' AND superseded_at IS NOT NULL)
            ),
            CHECK (
                (engine_family = 'codex' AND engine_driver = 'codex-app-server')
                OR (engine_family = 'claude'
                    AND engine_driver IN ('claude-code', 'agent-sdk'))
            )
        );
CREATE TABLE environments (
            environment_id TEXT PRIMARY KEY,
            alias TEXT NOT NULL UNIQUE,
            owner_user_id TEXT,
            display_name TEXT NOT NULL,
            description TEXT,
            connection_json TEXT NOT NULL DEFAULT '{}',
            credential_ref TEXT,
            is_seed INTEGER NOT NULL DEFAULT 0 CHECK (is_seed IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        , connection_fingerprint TEXT, disabled_at TEXT, disabled_reason TEXT);
CREATE TABLE fork_preview_receipts (
            preview_id TEXT PRIMARY KEY,
            preview_hash TEXT NOT NULL UNIQUE CHECK (trim(preview_hash) != ''),
            source_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            source_revision TEXT NOT NULL CHECK (trim(source_revision) != ''),
            source_engine_family TEXT NOT NULL CHECK (source_engine_family IN ('codex', 'claude')),
            target_engine_family TEXT NOT NULL CHECK (target_engine_family IN ('codex', 'claude')),
            transfer_mode TEXT NOT NULL CHECK (transfer_mode IN (
                'selected_turns', 'recent_turns', 'full_transcript', 'context_only'
            )),
            transfer_range_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(transfer_range_json)
                    AND json_type(transfer_range_json) = 'object'),
            message_count INTEGER NOT NULL CHECK (message_count >= 0),
            turn_count INTEGER NOT NULL CHECK (turn_count >= 0),
            item_count INTEGER NOT NULL CHECK (item_count >= 0),
            character_count INTEGER NOT NULL CHECK (character_count >= 0),
            utf8_byte_count INTEGER NOT NULL CHECK (utf8_byte_count >= 0),
            estimated_token_count INTEGER NOT NULL CHECK (estimated_token_count >= 0),
            token_estimator TEXT NOT NULL CHECK (trim(token_estimator) != ''),
            context_window_percent REAL CHECK (context_window_percent IS NULL
                OR (context_window_percent >= 0 AND context_window_percent <= 100)),
            tool_result_count INTEGER NOT NULL CHECK (tool_result_count >= 0),
            reasoning_count INTEGER NOT NULL CHECK (reasoning_count >= 0),
            binary_count INTEGER NOT NULL CHECK (binary_count >= 0),
            image_reference_count INTEGER NOT NULL CHECK (image_reference_count >= 0),
            cost_estimate_json TEXT CHECK (cost_estimate_json IS NULL
                OR (json_valid(cost_estimate_json)
                    AND json_type(cost_estimate_json) = 'object')),
            cost_unknown INTEGER NOT NULL CHECK (cost_unknown IN (0, 1)),
            truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
            disclosure_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(disclosure_json) AND json_type(disclosure_json) = 'object'),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, target_project_id TEXT, target_workspace_id TEXT, target_harness_engine TEXT, target_title TEXT,
            CHECK (source_engine_family != target_engine_family),
            CHECK ((cost_unknown = 1 AND cost_estimate_json IS NULL)
                OR (cost_unknown = 0 AND cost_estimate_json IS NOT NULL)),
            CHECK (expires_at > created_at)
        );
CREATE TABLE fork_transfer_receipts (
            transfer_id TEXT PRIMARY KEY,
            preview_id TEXT NOT NULL REFERENCES fork_preview_receipts(preview_id)
                ON DELETE RESTRICT,
            preview_hash TEXT NOT NULL,
            source_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            source_revision TEXT NOT NULL,
            transfer_mode TEXT NOT NULL CHECK (transfer_mode IN (
                'selected_turns', 'recent_turns', 'full_transcript', 'context_only'
            )),
            truncation_acknowledged INTEGER NOT NULL
                CHECK (truncation_acknowledged IN (0, 1)),
            full_transcript_confirmed INTEGER NOT NULL
                CHECK (full_transcript_confirmed IN (0, 1)),
            actor_user_id TEXT NOT NULL CHECK (trim(actor_user_id) != ''),
            idempotency_key TEXT NOT NULL CHECK (trim(idempotency_key) != ''),
            request_hash TEXT NOT NULL CHECK (trim(request_hash) != ''),
            status TEXT NOT NULL CHECK (status IN ('confirmed', 'transferred', 'failed')),
            target_task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
            evidence_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(evidence_json) AND json_type(evidence_json) = 'object'),
            failure_code TEXT,
            confirmed_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (preview_id),
            UNIQUE (actor_user_id, idempotency_key),
            CHECK ((transfer_mode = 'full_transcript' AND full_transcript_confirmed = 1)
                OR (transfer_mode != 'full_transcript' AND full_transcript_confirmed = 0)),
            CHECK ((status = 'confirmed' AND target_task_id IS NULL
                    AND completed_at IS NULL AND failure_code IS NULL)
                OR (status = 'transferred' AND target_task_id IS NOT NULL
                    AND completed_at IS NOT NULL AND failure_code IS NULL)
                OR (status = 'failed' AND completed_at IS NOT NULL
                    AND failure_code IS NOT NULL AND trim(failure_code) != ''))
        );
CREATE TABLE legacy_domain_records (
            legacy_record_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_path TEXT,
            source_record_id TEXT,
            source_payload_sha256 TEXT,
            reason TEXT
        );
CREATE TABLE next_turn_submissions (
            submission_id TEXT PRIMARY KEY
                REFERENCES turn_submissions(submission_id) ON DELETE RESTRICT,
            task_id TEXT NOT NULL,
            blocking_turn_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('waiting', 'ready', 'cancelled')),
            created_at TEXT NOT NULL,
            promoted_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (submission_id, task_id)
                REFERENCES turn_submissions(submission_id, task_id) ON DELETE RESTRICT,
            FOREIGN KEY (blocking_turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            CHECK (
                (status = 'waiting' AND promoted_at IS NULL)
                OR (status = 'ready' AND promoted_at IS NOT NULL)
                OR (status = 'cancelled' AND promoted_at IS NULL)
            )
        );
CREATE TABLE overview_planner_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            planner_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running', 'drained', 'stopped')),
            heartbeat_at TEXT NOT NULL,
            last_schedule_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        );
CREATE TABLE overview_refresh_card_states (
            owner_user_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            last_job_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'ok', 'partial', 'stale', 'unavailable', 'failed'
            )),
            data_json TEXT,
            data_cutoff_at TEXT NOT NULL,
            last_success_data_json TEXT,
            last_success_at TEXT,
            last_success_cutoff_at TEXT,
            error_summary TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, card_id),
            FOREIGN KEY (last_job_id) REFERENCES overview_refresh_jobs(job_id)
                ON DELETE RESTRICT
        );
CREATE TABLE overview_refresh_idempotency_requests (
            owner_user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES overview_refresh_jobs(job_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, idempotency_key)
        );
CREATE TABLE overview_refresh_jobs (
            job_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'catchup')),
            scheduled_for_date TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'retry_wait', 'running', 'succeeded', 'partial', 'failed'
            )),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            next_retry_at TEXT,
            last_failure_at TEXT,
            lease_owner TEXT,
            lease_token TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            snapshot_id TEXT,
            source_status TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (
                (trigger = 'manual' AND scheduled_for_date IS NULL)
                OR (trigger IN ('scheduled', 'catchup') AND scheduled_for_date IS NOT NULL)
            ),
            CHECK (
                (status = 'running' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
                 AND lease_expires_at IS NOT NULL)
                OR status != 'running'
            ),
            CHECK (
                (status = 'retry_wait' AND next_retry_at IS NOT NULL)
                OR status != 'retry_wait'
            )
        );
CREATE TABLE overview_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL, data_cutoff_at TEXT, source_status TEXT, attention_required INTEGER NOT NULL DEFAULT 0,
            UNIQUE(owner_user_id, snapshot_date)
        );
CREATE TABLE project_context_candidates (
                candidate_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'accepted', 'rejected')),
                created_at TEXT NOT NULL,
                created_by_user_id TEXT,
                source_metadata_json TEXT NOT NULL DEFAULT '{}',
                accepted_by_user_id TEXT,
                accepted_at TEXT,
                rejected_by_user_id TEXT,
                rejected_at TEXT,
                rejection_reason TEXT,
                source_task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
                source_message_start_seq INTEGER,
                source_message_end_seq INTEGER,
                source_output_start_seq INTEGER,
                source_output_end_seq INTEGER
            );
CREATE TABLE project_context_drafts (
            project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL DEFAULT '',
            updated_by_user_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
CREATE TABLE project_context_fragments (
            fragment_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            source_type TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        , source_version TEXT, source_fingerprint TEXT, sort_order INTEGER NOT NULL DEFAULT 0, byte_budget INTEGER, created_by_user_id TEXT, source_metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE project_context_version_provenance (
            context_version_id TEXT PRIMARY KEY
                REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            fragment_provenance_status TEXT NOT NULL
                CHECK (fragment_provenance_status IN ('verified', 'attention_needed')),
            evidence_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
CREATE TABLE project_context_versions (
            context_version_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            content TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
            created_by_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        , fragment_manifest_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE project_members (
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('viewer', 'editor')),
            can_publish INTEGER NOT NULL DEFAULT 0 CHECK (can_publish IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, user_id)
        );
CREATE TABLE project_workspace_links (
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, workspace_id)
        );
CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
            archived_at TEXT,
            archive_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
CREATE TABLE runtime_approval_requests (
            approval_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            runtime_execution_id TEXT NOT NULL,
            runtime_generation INTEGER NOT NULL CHECK (runtime_generation > 0),
            tool_call_ref TEXT NOT NULL CHECK (trim(tool_call_ref) != ''),
            status TEXT NOT NULL CHECK (status IN (
                'pending', 'approved', 'denied', 'expired', 'invalidated'
            )),
            request_json TEXT NOT NULL
                CHECK (json_valid(request_json) AND json_type(request_json) = 'object'),
            decision_json TEXT CHECK (decision_json IS NULL
                OR (json_valid(decision_json) AND json_type(decision_json) = 'object')),
            decision_actor_user_id TEXT,
            decision_idempotency_key TEXT,
            decision_request_hash TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            resolved_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (runtime_execution_id, runtime_generation, tool_call_ref),
            FOREIGN KEY (runtime_execution_id, turn_id, runtime_generation)
                REFERENCES runtime_executions(
                    runtime_execution_id, turn_id, runtime_generation
                ) ON DELETE RESTRICT,
            FOREIGN KEY (turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            CHECK ((status = 'pending' AND decision_json IS NULL
                    AND decision_actor_user_id IS NULL
                    AND decision_idempotency_key IS NULL
                    AND decision_request_hash IS NULL AND resolved_at IS NULL)
                OR (status != 'pending' AND decision_json IS NOT NULL
                    AND resolved_at IS NOT NULL)),
            CHECK ((decision_actor_user_id IS NULL AND decision_idempotency_key IS NULL
                    AND decision_request_hash IS NULL)
                OR (decision_actor_user_id IS NOT NULL
                    AND trim(decision_actor_user_id) != ''
                    AND decision_idempotency_key IS NOT NULL
                    AND trim(decision_idempotency_key) != ''
                    AND decision_request_hash IS NOT NULL
                    AND trim(decision_request_hash) != ''))
        );
CREATE TABLE runtime_executions (
            runtime_execution_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            execution_seq INTEGER NOT NULL CHECK (execution_seq > 0),
            runtime_generation INTEGER NOT NULL CHECK (runtime_generation > 0),
            binding_id TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'starting', 'running', 'reconciling', 'completed',
                'interrupted', 'failed', 'unknown'
            )),
            native_runtime_kind TEXT,
            native_runtime_ref TEXT,
            native_turn_kind TEXT,
            native_turn_ref TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(evidence_json) AND json_type(evidence_json) = 'object'),
            failure_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (turn_id, execution_seq),
            UNIQUE (turn_id, runtime_generation),
            UNIQUE (runtime_execution_id, turn_id, runtime_generation),
            FOREIGN KEY (turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            FOREIGN KEY (binding_id, task_id)
                REFERENCES engine_conversation_bindings(binding_id, task_id)
                ON DELETE RESTRICT,
            CHECK ((native_runtime_kind IS NULL AND native_runtime_ref IS NULL)
                OR (native_runtime_kind IS NOT NULL AND trim(native_runtime_kind) != ''
                    AND native_runtime_ref IS NOT NULL AND trim(native_runtime_ref) != '')),
            CHECK ((native_turn_kind IS NULL AND native_turn_ref IS NULL)
                OR (native_turn_kind IS NOT NULL AND trim(native_turn_kind) != ''
                    AND native_turn_ref IS NOT NULL AND trim(native_turn_ref) != '')),
            CHECK (
                (status IN ('starting', 'running', 'reconciling')
                    AND finished_at IS NULL AND failure_code IS NULL)
                OR (status IN ('completed', 'interrupted')
                    AND finished_at IS NOT NULL AND failure_code IS NULL)
                OR (status IN ('failed', 'unknown') AND finished_at IS NOT NULL
                    AND failure_code IS NOT NULL AND trim(failure_code) != '')
            )
        );
CREATE TABLE session_transcripts (
            project_key TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            subpath     TEXT NOT NULL DEFAULT '',
            seq         INTEGER NOT NULL,
            entry_json  TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (project_key, session_id, subpath, seq)
        );
CREATE TABLE task_context_update_previews (
            preview_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            context_version_id TEXT NOT NULL
                REFERENCES project_context_versions(context_version_id) ON DELETE RESTRICT,
            created_by_user_id TEXT NOT NULL,
            proposed_fingerprint TEXT NOT NULL,
            proposed_content TEXT NOT NULL,
            source_manifest_json TEXT NOT NULL,
            byte_budget INTEGER NOT NULL CHECK (byte_budget >= 0),
            truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            confirmed_snapshot_id TEXT
                REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT,
            confirmed_at TEXT
        );
CREATE TABLE task_relationships (
            source_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            target_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            relationship_type TEXT NOT NULL CHECK (relationship_type IN ('derived_from', 'depends_on', 'related_to')),
            created_at TEXT NOT NULL, relationship_id TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(source_task_id, target_task_id, relationship_type)
        );
CREATE TABLE task_turns (
            turn_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            turn_seq INTEGER NOT NULL CHECK (turn_seq > 0),
            status TEXT NOT NULL CHECK (status IN (
                'in_progress', 'completed', 'interrupted', 'failed'
            )),
            retry_of_turn_id TEXT REFERENCES task_turns(turn_id) ON DELETE RESTRICT,
            context_snapshot_ref TEXT,
            binding_id TEXT,
            engine_family TEXT NOT NULL CHECK (engine_family IN ('codex', 'claude')),
            engine_driver TEXT NOT NULL CHECK (engine_driver IN (
                'codex-app-server', 'claude-code', 'agent-sdk'
            )),
            contract_version INTEGER NOT NULL CHECK (contract_version > 0),
            provider_profile_ref TEXT,
            provider_profile_version TEXT,
            provider_profile_fingerprint TEXT,
            model TEXT,
            native_turn_kind TEXT,
            native_turn_ref TEXT,
            accepted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            failure_code TEXT,
            failure_metadata_json TEXT NOT NULL DEFAULT '{}'
                CHECK (
                    json_valid(failure_metadata_json)
                    AND json_type(failure_metadata_json) = 'object'
                ),
            UNIQUE (task_id, turn_seq),
            UNIQUE (turn_id, task_id),
            FOREIGN KEY (binding_id, task_id)
                REFERENCES engine_conversation_bindings(binding_id, task_id)
                ON DELETE RESTRICT,
            CHECK (retry_of_turn_id IS NULL OR retry_of_turn_id != turn_id),
            CHECK (
                (native_turn_kind IS NULL AND native_turn_ref IS NULL)
                OR (native_turn_kind IS NOT NULL AND trim(native_turn_kind) != ''
                    AND native_turn_ref IS NOT NULL AND trim(native_turn_ref) != '')
            ),
            CHECK (
                (status = 'in_progress' AND finished_at IS NULL AND failure_code IS NULL)
                OR (status IN ('completed', 'interrupted')
                    AND finished_at IS NOT NULL AND failure_code IS NULL)
                OR (status = 'failed' AND finished_at IS NOT NULL
                    AND failure_code IS NOT NULL AND trim(failure_code) != '')
            ),
            CHECK (
                (engine_family = 'codex' AND engine_driver = 'codex-app-server')
                OR (engine_family = 'claude'
                    AND engine_driver IN ('claude-code', 'agent-sdk'))
            )
        );
CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            researcher_type TEXT NOT NULL,
            harness_engine TEXT NOT NULL,
            user_skills TEXT,
            user_mcp_servers TEXT,
            title TEXT NOT NULL,
            prompt TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            latest_output_seq INTEGER NOT NULL DEFAULT 0,
            owner_user_id TEXT NOT NULL,
            exit_code INTEGER,
            error_summary TEXT,
            token_usage_json TEXT
        , api_base_url TEXT, api_key TEXT, codex_base_url TEXT, codex_api_key TEXT, codex_model TEXT, codex_app_server_command TEXT, codex_approval_policy TEXT, project_context_version_id TEXT, archived_at TEXT, archive_reason TEXT, stop_reason TEXT, latest_attempt_id TEXT, runtime_config_fingerprint TEXT, source_fingerprint TEXT, project_context_snapshot_id TEXT REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT);
CREATE TABLE turn_control_requests (
            control_request_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            expected_turn_id TEXT NOT NULL,
            runtime_execution_id TEXT NOT NULL,
            runtime_generation INTEGER NOT NULL CHECK (runtime_generation > 0),
            kind TEXT NOT NULL CHECK (kind IN ('steer', 'interrupt')),
            status TEXT NOT NULL CHECK (status IN (
                'requested', 'delivering', 'accepted', 'completed', 'rejected',
                'delivery_unknown'
            )),
            actor_user_id TEXT NOT NULL CHECK (trim(actor_user_id) != ''),
            idempotency_key TEXT NOT NULL CHECK (trim(idempotency_key) != ''),
            request_hash TEXT NOT NULL CHECK (trim(request_hash) != ''),
            payload_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
            evidence_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(evidence_json) AND json_type(evidence_json) = 'object'),
            failure_code TEXT,
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (actor_user_id, kind, idempotency_key),
            FOREIGN KEY (runtime_execution_id, expected_turn_id, runtime_generation)
                REFERENCES runtime_executions(
                    runtime_execution_id, turn_id, runtime_generation
                ) ON DELETE RESTRICT,
            FOREIGN KEY (expected_turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            CHECK (
                (status IN ('requested', 'delivering') AND accepted_at IS NULL
                    AND completed_at IS NULL AND failure_code IS NULL)
                OR (status = 'accepted' AND accepted_at IS NOT NULL
                    AND completed_at IS NULL AND failure_code IS NULL)
                OR (status = 'completed' AND kind = 'interrupt'
                    AND accepted_at IS NOT NULL AND completed_at IS NOT NULL
                    AND failure_code IS NULL)
                OR (status IN ('rejected', 'delivery_unknown')
                    AND completed_at IS NOT NULL AND failure_code IS NOT NULL
                    AND trim(failure_code) != '')
            )
        );
CREATE TABLE turn_items (
            item_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            task_item_seq INTEGER NOT NULL CHECK (task_item_seq > 0),
            turn_item_seq INTEGER NOT NULL CHECK (turn_item_seq > 0),
            envelope_type TEXT NOT NULL CHECK (trim(envelope_type) != ''),
            envelope_version INTEGER NOT NULL CHECK (envelope_version > 0),
            item_type TEXT NOT NULL CHECK (item_type IN (
                'user_message', 'agent_message', 'reasoning_summary',
                'command_execution', 'file_change', 'tool_call', 'tool_result',
                'approval_request', 'approval_result', 'system_notice',
                'plan_update', 'error'
            )),
            actor TEXT NOT NULL CHECK (actor IN ('user', 'agent', 'tool', 'system')),
            payload_json TEXT NOT NULL
                CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
            native_provenance_json TEXT NOT NULL DEFAULT '{}'
                CHECK (
                    json_valid(native_provenance_json)
                    AND json_type(native_provenance_json) = 'object'
                ),
            native_dedupe_scope TEXT,
            native_item_id TEXT,
            parent_item_id TEXT REFERENCES turn_items(item_id) ON DELETE RESTRICT,
            call_item_id TEXT REFERENCES turn_items(item_id) ON DELETE RESTRICT,
            occurred_at TEXT,
            ingested_at TEXT NOT NULL,
            persisted_at TEXT NOT NULL,
            UNIQUE (task_id, task_item_seq),
            UNIQUE (turn_id, turn_item_seq),
            UNIQUE (item_id, task_id),
            FOREIGN KEY (turn_id, task_id)
                REFERENCES task_turns(turn_id, task_id) ON DELETE RESTRICT,
            CHECK (parent_item_id IS NULL OR parent_item_id != item_id),
            CHECK (call_item_id IS NULL OR call_item_id != item_id),
            CHECK (
                (native_dedupe_scope IS NULL AND native_item_id IS NULL)
                OR (native_dedupe_scope IS NOT NULL AND trim(native_dedupe_scope) != ''
                    AND native_item_id IS NOT NULL AND trim(native_item_id) != '')
            )
        );
CREATE TABLE turn_submissions (
            submission_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
            reserved_turn_id TEXT NOT NULL UNIQUE CHECK (trim(reserved_turn_id) != ''),
            actor_user_id TEXT NOT NULL CHECK (trim(actor_user_id) != ''),
            idempotency_key TEXT NOT NULL CHECK (trim(idempotency_key) != ''),
            request_hash TEXT NOT NULL CHECK (trim(request_hash) != ''),
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'claimed', 'delivering', 'delivered', 'cancelled',
                'delivery_unknown', 'failed_delivery'
            )),
            input_json TEXT NOT NULL
                CHECK (json_valid(input_json) AND json_type(input_json) = 'object'),
            context_snapshot_ref TEXT,
            native_turn_kind TEXT,
            native_turn_ref TEXT,
            delivery_evidence_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(delivery_evidence_json)
                    AND json_type(delivery_evidence_json) = 'object'),
            failure_code TEXT,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            delivering_at TEXT,
            accepted_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (actor_user_id, task_id, idempotency_key),
            UNIQUE (submission_id, task_id),
            CHECK ((native_turn_kind IS NULL AND native_turn_ref IS NULL)
                OR (native_turn_kind IS NOT NULL AND trim(native_turn_kind) != ''
                    AND native_turn_ref IS NOT NULL AND trim(native_turn_ref) != '')),
            CHECK (
                (status IN ('queued', 'claimed', 'delivering')
                    AND finished_at IS NULL AND failure_code IS NULL)
                OR (status = 'delivered' AND accepted_at IS NOT NULL
                    AND finished_at IS NOT NULL AND failure_code IS NULL
                    AND native_turn_ref IS NOT NULL)
                OR (status = 'delivery_unknown' AND finished_at IS NULL
                    AND failure_code IS NOT NULL AND trim(failure_code) != '')
                OR (status IN ('cancelled', 'failed_delivery')
                    AND finished_at IS NOT NULL AND failure_code IS NOT NULL
                    AND trim(failure_code) != '')
            )
        );
CREATE TABLE workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            environment_id TEXT NOT NULL REFERENCES environments(environment_id) ON DELETE RESTRICT,
            canonical_path TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT,
            context_metadata_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unregistered')),
            legacy_project_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, workspace_context TEXT, canonical_path_fingerprint TEXT, unregistered_at TEXT, unregistered_reason TEXT, last_seen_at TEXT,
            UNIQUE(owner_user_id, environment_id, canonical_path)
        );
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_owner ON tasks(owner_user_id);
CREATE INDEX idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX idx_tasks_environment ON tasks(environment_id);
CREATE INDEX idx_tasks_created ON tasks(created_at);
CREATE INDEX idx_tasks_updated ON tasks(updated_at);
CREATE INDEX idx_session_transcripts_lookup
        ON session_transcripts(project_key, session_id, subpath)
        ;
CREATE INDEX idx_domain_maintenance_mutations_epoch
        ON domain_maintenance_mutations(maintenance_epoch)
        ;
CREATE UNIQUE INDEX idx_projects_one_default_per_owner
        ON projects(owner_user_id) WHERE is_default = 1 AND status = 'active';
CREATE UNIQUE INDEX idx_project_workspace_one_primary
        ON project_workspace_links(project_id) WHERE is_primary = 1 AND status = 'active';
CREATE UNIQUE INDEX idx_context_active_per_project
        ON project_context_versions(project_id) WHERE is_active = 1;
CREATE TRIGGER prevent_context_version_content_update
        BEFORE UPDATE OF content ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;
CREATE TRIGGER primary_link_must_be_active_insert
        BEFORE INSERT ON project_workspace_links WHEN NEW.is_primary = 1 AND NEW.status != 'active'
        BEGIN SELECT RAISE(ABORT, 'primary link must be active'); END;
CREATE TRIGGER primary_link_must_be_active_update
        BEFORE UPDATE OF is_primary, status ON project_workspace_links
        WHEN NEW.is_primary = 1 AND NEW.status != 'active'
        BEGIN SELECT RAISE(ABORT, 'primary link must be active'); END;
CREATE INDEX idx_domain_write_participants_type
        ON domain_write_participants(participant_type, heartbeat_at);
CREATE INDEX idx_domain_maintenance_mutations_participant
        ON domain_maintenance_mutations(participant_id);
CREATE UNIQUE INDEX idx_task_relationship_stable_id ON task_relationships(relationship_id) WHERE relationship_id IS NOT NULL;
CREATE INDEX idx_tasks_project_context_snapshot
        ON tasks(project_context_snapshot_id)
        WHERE project_context_snapshot_id IS NOT NULL;
CREATE INDEX idx_context_fragments_project_order
        ON project_context_fragments(project_id, sort_order, created_at, fragment_id);
CREATE INDEX idx_task_context_previews_task_actor
        ON task_context_update_previews(task_id, created_by_user_id, created_at);
CREATE TRIGGER project_context_version_delete_forbidden
        BEFORE DELETE ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are append-only'); END;
CREATE TRIGGER context_snapshot_immutable
        BEFORE UPDATE ON context_snapshots
        BEGIN SELECT RAISE(ABORT, 'context snapshots are immutable'); END;
CREATE TRIGGER context_snapshot_delete_forbidden
        BEFORE DELETE ON context_snapshots
        BEGIN SELECT RAISE(ABORT, 'context snapshots are append-only'); END;
CREATE TRIGGER context_fragment_immutable
        BEFORE UPDATE ON project_context_fragments
        BEGIN SELECT RAISE(ABORT, 'context fragments are immutable'); END;
CREATE TRIGGER context_fragment_delete_forbidden
        BEFORE DELETE ON project_context_fragments
        BEGIN SELECT RAISE(ABORT, 'context fragments are append-only'); END;
CREATE INDEX idx_tasks_project_lifecycle
        ON tasks(project_id, archived_at, updated_at, task_id);
CREATE UNIQUE INDEX idx_overview_refresh_jobs_schedule_slot
        ON overview_refresh_jobs(owner_user_id, scheduled_for_date)
        WHERE scheduled_for_date IS NOT NULL;
CREATE UNIQUE INDEX idx_overview_refresh_jobs_active_owner
        ON overview_refresh_jobs(owner_user_id)
        WHERE status IN ('queued', 'retry_wait', 'running');
CREATE INDEX idx_overview_refresh_jobs_claim
        ON overview_refresh_jobs(status, next_retry_at, created_at, job_id);
CREATE INDEX idx_overview_refresh_jobs_owner_updated
        ON overview_refresh_jobs(owner_user_id, updated_at DESC, job_id DESC);
CREATE INDEX idx_overview_refresh_jobs_lease_expiry
        ON overview_refresh_jobs(status, lease_expires_at)
        WHERE status = 'running';
CREATE INDEX idx_overview_refresh_card_states_owner_updated
        ON overview_refresh_card_states(owner_user_id, updated_at DESC, card_id);
CREATE INDEX idx_context_version_provenance_status
        ON project_context_version_provenance(fragment_provenance_status, recorded_at);
CREATE TRIGGER context_version_provenance_append_only_update
        BEFORE UPDATE ON project_context_version_provenance
        BEGIN SELECT RAISE(ABORT, 'context version provenance is append-only'); END;
CREATE TRIGGER context_version_provenance_append_only_delete
        BEFORE DELETE ON project_context_version_provenance
        BEGIN SELECT RAISE(ABORT, 'context version provenance is append-only'); END;
CREATE TRIGGER project_context_version_metadata_immutable
        BEFORE UPDATE OF project_id, content, fingerprint, fragment_manifest_json,
                         created_by_user_id, created_at
        ON project_context_versions
        BEGIN SELECT RAISE(ABORT, 'context versions are immutable'); END;
CREATE INDEX idx_context_candidates_project_status
        ON project_context_candidates(project_id, status, created_at);
CREATE TRIGGER context_candidate_provenance_immutable
        BEFORE UPDATE OF project_id, content, created_at, created_by_user_id,
                         source_metadata_json, source_task_id,
                         source_message_start_seq, source_message_end_seq,
                         source_output_start_seq, source_output_end_seq
        ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidate provenance is immutable'); END;
CREATE TRIGGER context_candidate_delete_forbidden
        BEFORE DELETE ON project_context_candidates
        BEGIN SELECT RAISE(ABORT, 'context candidates are append-only'); END;
CREATE TRIGGER context_candidate_source_required_insert
        BEFORE INSERT ON project_context_candidates
        WHEN NEW.created_by_user_id IS NULL
          OR trim(NEW.created_by_user_id) = ''
          OR NEW.source_task_id IS NULL
          OR trim(NEW.source_task_id) = ''
          OR (NEW.source_message_start_seq IS NULL
              AND NEW.source_output_start_seq IS NULL)
          OR ((NEW.source_message_start_seq IS NULL)
              != (NEW.source_message_end_seq IS NULL))
          OR ((NEW.source_output_start_seq IS NULL)
              != (NEW.source_output_end_seq IS NULL))
          OR (NEW.source_message_start_seq IS NOT NULL
              AND (NEW.source_message_start_seq < 0
                   OR NEW.source_message_end_seq < NEW.source_message_start_seq))
          OR (NEW.source_output_start_seq IS NOT NULL
              AND (NEW.source_output_start_seq < 0
                   OR NEW.source_output_end_seq < NEW.source_output_start_seq))
        BEGIN SELECT RAISE(ABORT, 'context candidate requires Task source provenance'); END;
CREATE TRIGGER context_candidate_source_task_project_insert
        BEFORE INSERT ON project_context_candidates
        WHEN NOT EXISTS (
            SELECT 1 FROM tasks
            WHERE task_id = NEW.source_task_id AND project_id = NEW.project_id
        )
        BEGIN SELECT RAISE(ABORT, 'context candidate source Task must belong to Project'); END;
CREATE INDEX idx_overview_refresh_idempotency_job
        ON overview_refresh_idempotency_requests(job_id);
CREATE UNIQUE INDEX idx_engine_bindings_one_active_task
        ON engine_conversation_bindings(task_id)
        WHERE status = 'active';
CREATE UNIQUE INDEX idx_engine_bindings_native_identity
        ON engine_conversation_bindings(
            engine_family,
            engine_driver,
            native_conversation_kind,
            native_conversation_ref
        );
CREATE UNIQUE INDEX idx_task_turns_one_active_task
        ON task_turns(task_id)
        WHERE status = 'in_progress';
CREATE INDEX idx_task_turns_task_order
        ON task_turns(task_id, turn_seq);
CREATE UNIQUE INDEX idx_task_turns_native_identity
        ON task_turns(binding_id, native_turn_kind, native_turn_ref)
        WHERE binding_id IS NOT NULL AND native_turn_ref IS NOT NULL;
CREATE INDEX idx_turn_items_turn_order
        ON turn_items(turn_id, turn_item_seq);
CREATE INDEX idx_turn_items_task_order
        ON turn_items(task_id, task_item_seq);
CREATE UNIQUE INDEX idx_turn_items_native_dedupe
        ON turn_items(native_dedupe_scope, native_item_id)
        WHERE native_dedupe_scope IS NOT NULL;
CREATE TRIGGER engine_binding_identity_immutable
        BEFORE UPDATE OF binding_id, task_id, binding_seq, engine_family, engine_driver,
                         native_conversation_kind, native_conversation_ref, contract_version,
                         provider_profile_ref, provider_profile_version,
                         provider_profile_fingerprint, provenance_json, created_at
        ON engine_conversation_bindings
        BEGIN
            SELECT RAISE(ABORT, 'engine conversation binding identity is immutable');
        END;
CREATE TRIGGER engine_binding_transition_guard
        BEFORE UPDATE OF status, validated_at, superseded_at, validation_evidence_json
        ON engine_conversation_bindings
        WHEN OLD.status != 'active' OR NEW.status != 'superseded'
        BEGIN
            SELECT RAISE(ABORT, 'invalid engine conversation binding transition');
        END;
CREATE TRIGGER engine_binding_delete_forbidden
        BEFORE DELETE ON engine_conversation_bindings
        BEGIN
            SELECT RAISE(ABORT, 'engine conversation bindings are append-only');
        END;
CREATE TRIGGER task_turn_retry_task_guard_insert
        BEFORE INSERT ON task_turns
        WHEN NEW.retry_of_turn_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM task_turns AS prior
            WHERE prior.turn_id = NEW.retry_of_turn_id
              AND prior.task_id = NEW.task_id
              AND prior.turn_seq < NEW.turn_seq
        )
        BEGIN
            SELECT RAISE(ABORT, 'retry Turn must reference an earlier Turn in the same Task');
        END;
CREATE TRIGGER task_turn_binding_lineage_guard_insert
        BEFORE INSERT ON task_turns
        WHEN NEW.binding_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM engine_conversation_bindings AS binding
            WHERE binding.binding_id = NEW.binding_id
              AND binding.task_id = NEW.task_id
              AND binding.engine_family = NEW.engine_family
              AND binding.engine_driver = NEW.engine_driver
        )
        BEGIN
            SELECT RAISE(ABORT, 'Turn binding must match Task and engine lineage');
        END;
CREATE TRIGGER task_turn_identity_immutable
        BEFORE UPDATE OF turn_id, task_id, turn_seq, retry_of_turn_id,
                         context_snapshot_ref, binding_id, engine_family, engine_driver,
                         contract_version, provider_profile_ref, provider_profile_version,
                         provider_profile_fingerprint, model, native_turn_kind,
                         native_turn_ref, accepted_at
        ON task_turns
        BEGIN
            SELECT RAISE(ABORT, 'Task Turn identity is immutable');
        END;
CREATE TRIGGER task_turn_transition_guard
        BEFORE UPDATE OF status ON task_turns
        WHEN OLD.status != 'in_progress'
          OR NEW.status NOT IN ('completed', 'interrupted', 'failed')
        BEGIN
            SELECT RAISE(ABORT, 'invalid Task Turn state transition');
        END;
CREATE TRIGGER task_turn_terminal_immutable
        BEFORE UPDATE ON task_turns
        WHEN OLD.status IN ('completed', 'interrupted', 'failed')
        BEGIN
            SELECT RAISE(ABORT, 'terminal Task Turns are immutable');
        END;
CREATE TRIGGER task_turn_delete_forbidden
        BEFORE DELETE ON task_turns
        BEGIN
            SELECT RAISE(ABORT, 'Task Turns are append-only');
        END;
CREATE TRIGGER turn_item_parent_task_guard_insert
        BEFORE INSERT ON turn_items
        WHEN NEW.parent_item_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM turn_items AS parent
            WHERE parent.item_id = NEW.parent_item_id
              AND parent.task_id = NEW.task_id
              AND parent.task_item_seq < NEW.task_item_seq
        )
        BEGIN
            SELECT RAISE(ABORT, 'parent Item must be an earlier Item in the same Task');
        END;
CREATE TRIGGER turn_item_call_turn_guard_insert
        BEFORE INSERT ON turn_items
        WHEN NEW.call_item_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM turn_items AS call_item
            WHERE call_item.item_id = NEW.call_item_id
              AND call_item.turn_id = NEW.turn_id
              AND call_item.turn_item_seq < NEW.turn_item_seq
              AND call_item.item_type = 'tool_call'
        )
        BEGIN
            SELECT RAISE(ABORT, 'result Item must reference an earlier tool call in the same Turn');
        END;
CREATE TRIGGER turn_item_update_forbidden
        BEFORE UPDATE ON turn_items
        BEGIN
            SELECT RAISE(ABORT, 'Turn Items are append-only');
        END;
CREATE TRIGGER turn_item_delete_forbidden
        BEFORE DELETE ON turn_items
        BEGIN
            SELECT RAISE(ABORT, 'Turn Items are append-only');
        END;
CREATE INDEX idx_turn_submissions_task_created
        ON turn_submissions(task_id, created_at, submission_id);
CREATE UNIQUE INDEX idx_turn_submissions_native_identity
        ON turn_submissions(task_id, native_turn_kind, native_turn_ref)
        WHERE native_turn_ref IS NOT NULL;
CREATE UNIQUE INDEX idx_runtime_executions_one_active_turn
        ON runtime_executions(turn_id)
        WHERE status IN ('starting', 'running', 'reconciling');
CREATE UNIQUE INDEX idx_runtime_executions_native_identity
        ON runtime_executions(native_runtime_kind, native_runtime_ref)
        WHERE native_runtime_ref IS NOT NULL;
CREATE INDEX idx_turn_controls_turn_created
        ON turn_control_requests(expected_turn_id, created_at, control_request_id);
CREATE UNIQUE INDEX idx_runtime_approvals_decision_idempotency
        ON runtime_approval_requests(decision_actor_user_id, decision_idempotency_key)
        WHERE decision_idempotency_key IS NOT NULL;
CREATE TRIGGER turn_submission_identity_immutable
        BEFORE UPDATE OF submission_id, task_id, reserved_turn_id, actor_user_id,
                         idempotency_key, request_hash, input_json,
                         created_at ON turn_submissions
        BEGIN SELECT RAISE(ABORT, 'Turn Submission identity is immutable'); END;
CREATE TRIGGER turn_submission_context_snapshot_guard
        BEFORE UPDATE OF context_snapshot_ref ON turn_submissions
        WHEN OLD.status <> 'queued'
        BEGIN SELECT RAISE(ABORT, 'started Turn Submission context is immutable'); END;
CREATE TRIGGER turn_submission_transition_guard
        BEFORE UPDATE OF status ON turn_submissions
        WHEN NOT ((OLD.status = 'queued' AND NEW.status IN ('claimed', 'cancelled'))
            OR (OLD.status = 'claimed' AND NEW.status IN ('delivering', 'cancelled'))
            OR (OLD.status = 'delivering' AND NEW.status IN ('delivered', 'delivery_unknown'))
            OR (OLD.status = 'delivery_unknown'
                AND NEW.status IN ('delivered', 'failed_delivery')))
        BEGIN SELECT RAISE(ABORT, 'invalid Turn Submission state transition'); END;
CREATE TRIGGER turn_submission_delivered_turn_guard
        BEFORE UPDATE OF status ON turn_submissions
        WHEN NEW.status = 'delivered' AND NOT EXISTS (
            SELECT 1 FROM task_turns AS turn
            WHERE turn.turn_id = NEW.reserved_turn_id AND turn.task_id = NEW.task_id
              AND turn.native_turn_kind = NEW.native_turn_kind
              AND turn.native_turn_ref = NEW.native_turn_ref)
        BEGIN SELECT RAISE(ABORT, 'delivered submission requires its accepted Turn'); END;
CREATE TRIGGER turn_submission_terminal_immutable
        BEFORE UPDATE ON turn_submissions
        WHEN OLD.status IN ('delivered', 'cancelled', 'failed_delivery')
        BEGIN SELECT RAISE(ABORT, 'terminal Turn Submissions are immutable'); END;
CREATE TRIGGER turn_submission_delete_forbidden
        BEFORE DELETE ON turn_submissions
        BEGIN SELECT RAISE(ABORT, 'Turn Submissions are append-only'); END;
CREATE TRIGGER runtime_execution_binding_guard_insert
        BEFORE INSERT ON runtime_executions
        WHEN NEW.binding_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM task_turns AS turn
            WHERE turn.turn_id = NEW.turn_id AND turn.task_id = NEW.task_id
              AND turn.binding_id = NEW.binding_id)
        BEGIN SELECT RAISE(ABORT, 'Runtime Execution binding must match its Turn'); END;
CREATE TRIGGER runtime_execution_identity_immutable
        BEFORE UPDATE OF runtime_execution_id, task_id, turn_id, execution_seq,
                         runtime_generation, binding_id, native_runtime_kind,
                         native_runtime_ref, native_turn_kind, native_turn_ref, created_at
        ON runtime_executions
        BEGIN SELECT RAISE(ABORT, 'Runtime Execution identity is immutable'); END;
CREATE TRIGGER runtime_execution_transition_guard
        BEFORE UPDATE OF status ON runtime_executions
        WHEN NOT ((OLD.status = 'starting'
                AND NEW.status IN ('running', 'reconciling', 'failed'))
            OR (OLD.status = 'running'
                AND NEW.status IN ('reconciling', 'completed', 'interrupted', 'failed'))
            OR (OLD.status = 'reconciling'
                AND NEW.status IN ('running', 'completed', 'interrupted', 'failed', 'unknown')))
        BEGIN SELECT RAISE(ABORT, 'invalid Runtime Execution state transition'); END;
CREATE TRIGGER runtime_execution_terminal_immutable
        BEFORE UPDATE ON runtime_executions
        WHEN OLD.status IN ('completed', 'interrupted', 'failed', 'unknown')
        BEGIN SELECT RAISE(ABORT, 'terminal Runtime Executions are immutable'); END;
CREATE TRIGGER runtime_execution_delete_forbidden
        BEFORE DELETE ON runtime_executions
        BEGIN SELECT RAISE(ABORT, 'Runtime Executions are append-only'); END;
CREATE TRIGGER turn_control_active_turn_guard_insert
        BEFORE INSERT ON turn_control_requests
        WHEN NOT EXISTS (SELECT 1 FROM task_turns AS turn
            WHERE turn.turn_id = NEW.expected_turn_id AND turn.task_id = NEW.task_id
              AND turn.status = 'in_progress')
        BEGIN SELECT RAISE(ABORT, 'control request expected Turn is stale'); END;
CREATE TRIGGER turn_control_runtime_guard_insert
        BEFORE INSERT ON turn_control_requests
        WHEN NOT EXISTS (SELECT 1 FROM runtime_executions AS execution
            WHERE execution.runtime_execution_id = NEW.runtime_execution_id
              AND execution.turn_id = NEW.expected_turn_id
              AND execution.runtime_generation = NEW.runtime_generation
              AND execution.status IN ('starting', 'running', 'reconciling'))
        BEGIN SELECT RAISE(ABORT, 'control request runtime scope is stale'); END;
CREATE TRIGGER turn_control_identity_immutable
        BEFORE UPDATE OF control_request_id, task_id, expected_turn_id,
                         runtime_execution_id, runtime_generation, kind,
                         actor_user_id, idempotency_key, request_hash, payload_json, created_at
        ON turn_control_requests
        BEGIN SELECT RAISE(ABORT, 'Turn Control Request identity is immutable'); END;
CREATE TRIGGER turn_control_transition_guard
        BEFORE UPDATE OF status ON turn_control_requests
        WHEN NOT ((OLD.kind = 'steer' AND OLD.status = 'requested'
                AND NEW.status IN ('delivering', 'rejected'))
            OR (OLD.kind = 'steer' AND OLD.status = 'delivering'
                AND NEW.status IN ('accepted', 'rejected', 'delivery_unknown'))
            OR (OLD.kind = 'interrupt' AND OLD.status = 'requested'
                AND NEW.status IN ('accepted', 'rejected', 'delivery_unknown'))
            OR (OLD.kind = 'interrupt' AND OLD.status = 'accepted'
                AND NEW.status = 'completed'))
        BEGIN SELECT RAISE(ABORT, 'invalid Turn Control Request state transition'); END;
CREATE TRIGGER turn_control_delete_forbidden
        BEFORE DELETE ON turn_control_requests
        BEGIN SELECT RAISE(ABORT, 'Turn Control Requests are append-only'); END;
CREATE TRIGGER runtime_approval_active_scope_guard_insert
        BEFORE INSERT ON runtime_approval_requests
        WHEN NOT EXISTS (SELECT 1 FROM task_turns AS turn
            JOIN runtime_executions AS execution ON execution.turn_id = turn.turn_id
            WHERE turn.turn_id = NEW.turn_id AND turn.task_id = NEW.task_id
              AND turn.status = 'in_progress'
              AND execution.runtime_execution_id = NEW.runtime_execution_id
              AND execution.runtime_generation = NEW.runtime_generation
              AND execution.status IN ('starting', 'running', 'reconciling'))
        BEGIN SELECT RAISE(ABORT, 'approval runtime scope is stale'); END;
CREATE TRIGGER runtime_approval_identity_immutable
        BEFORE UPDATE OF approval_id, task_id, turn_id, runtime_execution_id,
                         runtime_generation, tool_call_ref, request_json, created_at, expires_at
        ON runtime_approval_requests
        BEGIN SELECT RAISE(ABORT, 'Runtime Approval identity is immutable'); END;
CREATE TRIGGER runtime_approval_transition_guard
        BEFORE UPDATE OF status ON runtime_approval_requests
        WHEN OLD.status != 'pending'
          OR NEW.status NOT IN ('approved', 'denied', 'expired', 'invalidated')
        BEGIN SELECT RAISE(ABORT, 'invalid Runtime Approval state transition'); END;
CREATE TRIGGER runtime_approval_delete_forbidden
        BEFORE DELETE ON runtime_approval_requests
        BEGIN SELECT RAISE(ABORT, 'Runtime Approvals are append-only'); END;
CREATE TRIGGER fork_preview_update_forbidden
        BEFORE UPDATE ON fork_preview_receipts
        BEGIN SELECT RAISE(ABORT, 'Fork preview receipts are append-only'); END;
CREATE TRIGGER fork_preview_delete_forbidden
        BEFORE DELETE ON fork_preview_receipts
        BEGIN SELECT RAISE(ABORT, 'Fork preview receipts are append-only'); END;
CREATE TRIGGER fork_transfer_preview_guard_insert
        BEFORE INSERT ON fork_transfer_receipts
        WHEN NOT EXISTS (SELECT 1 FROM fork_preview_receipts AS preview
            WHERE preview.preview_id = NEW.preview_id
              AND preview.preview_hash = NEW.preview_hash
              AND preview.source_task_id = NEW.source_task_id
              AND preview.source_revision = NEW.source_revision
              AND preview.transfer_mode = NEW.transfer_mode
              AND julianday(NEW.confirmed_at) <= julianday(preview.expires_at)
              AND (preview.truncated = 0 OR NEW.truncation_acknowledged = 1))
        BEGIN SELECT RAISE(ABORT, 'Fork confirmation does not match its preview'); END;
CREATE TRIGGER fork_transfer_identity_immutable
        BEFORE UPDATE OF transfer_id, preview_id, preview_hash, source_task_id,
                         source_revision, transfer_mode, truncation_acknowledged,
                         full_transcript_confirmed, actor_user_id, idempotency_key,
                         request_hash, confirmed_at ON fork_transfer_receipts
        BEGIN SELECT RAISE(ABORT, 'Fork transfer identity is immutable'); END;
CREATE TRIGGER fork_transfer_transition_guard
        BEFORE UPDATE OF status ON fork_transfer_receipts
        WHEN OLD.status != 'confirmed' OR NEW.status NOT IN ('transferred', 'failed')
        BEGIN SELECT RAISE(ABORT, 'invalid Fork transfer state transition'); END;
CREATE TRIGGER fork_transfer_terminal_immutable
        BEFORE UPDATE ON fork_transfer_receipts
        WHEN OLD.status IN ('transferred', 'failed')
        BEGIN SELECT RAISE(ABORT, 'terminal Fork transfers are immutable'); END;
CREATE TRIGGER fork_transfer_delete_forbidden
        BEFORE DELETE ON fork_transfer_receipts
        BEGIN SELECT RAISE(ABORT, 'Fork transfer receipts are append-only'); END;
CREATE TRIGGER conversation_task_authority_update_forbidden
        BEFORE UPDATE ON conversation_task_authorities
        BEGIN SELECT RAISE(ABORT, 'conversation Task authority is immutable'); END;
CREATE TRIGGER conversation_task_authority_delete_forbidden
        BEFORE DELETE ON conversation_task_authorities
        BEGIN SELECT RAISE(ABORT, 'conversation Task authority is immutable'); END;
CREATE TRIGGER engine_binding_v3_authority_guard_insert
        BEFORE INSERT ON engine_conversation_bindings
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER task_turn_v3_authority_guard_insert
        BEFORE INSERT ON task_turns
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER turn_item_v3_authority_guard_insert
        BEFORE INSERT ON turn_items
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER turn_submission_v3_authority_guard_insert
        BEFORE INSERT ON turn_submissions
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER runtime_execution_v3_authority_guard_insert
        BEFORE INSERT ON runtime_executions
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER turn_control_v3_authority_guard_insert
        BEFORE INSERT ON turn_control_requests
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER runtime_approval_v3_authority_guard_insert
        BEFORE INSERT ON runtime_approval_requests
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER fork_preview_v3_authority_guard_insert
        BEFORE INSERT ON fork_preview_receipts
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.source_task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER fork_transfer_v3_authority_guard_insert
        BEFORE INSERT ON fork_transfer_receipts
        WHEN NOT EXISTS (SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.source_task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER runtime_approval_active_scope_guard_resolve
        BEFORE UPDATE OF status ON runtime_approval_requests
        WHEN NEW.status IN ('approved', 'denied') AND NOT EXISTS (
            SELECT 1 FROM task_turns AS turn
            JOIN runtime_executions AS execution ON execution.turn_id = turn.turn_id
            WHERE turn.turn_id = OLD.turn_id AND turn.task_id = OLD.task_id
              AND turn.status = 'in_progress'
              AND execution.runtime_execution_id = OLD.runtime_execution_id
              AND execution.runtime_generation = OLD.runtime_generation
              AND execution.status IN ('starting', 'running', 'reconciling'))
        BEGIN SELECT RAISE(ABORT, 'approval runtime scope is stale'); END;
CREATE TRIGGER turn_item_result_call_required_insert
        BEFORE INSERT ON turn_items
        WHEN NEW.item_type = 'tool_result' AND NEW.call_item_id IS NULL
        BEGIN SELECT RAISE(ABORT, 'tool result requires its tool call'); END;
CREATE TRIGGER fork_transfer_confirmation_time_guard_insert
        BEFORE INSERT ON fork_transfer_receipts
        WHEN NOT EXISTS (SELECT 1 FROM fork_preview_receipts AS preview
            WHERE preview.preview_id = NEW.preview_id
              AND julianday(NEW.confirmed_at) >= julianday(preview.created_at)
              AND julianday(NEW.confirmed_at) <= julianday(preview.expires_at))
        BEGIN SELECT RAISE(ABORT, 'Fork confirmation timestamp is outside preview validity'); END;
CREATE TRIGGER runtime_execution_active_turn_guard_insert
        BEFORE INSERT ON runtime_executions
        WHEN NEW.native_turn_kind IS NULL
          OR NEW.native_turn_ref IS NULL
          OR NOT EXISTS (SELECT 1 FROM task_turns AS turn
              WHERE turn.turn_id = NEW.turn_id AND turn.task_id = NEW.task_id
                AND turn.status = 'in_progress'
                AND turn.native_turn_kind = NEW.native_turn_kind
                AND turn.native_turn_ref = NEW.native_turn_ref)
        BEGIN SELECT RAISE(ABORT, 'Runtime Execution Turn scope is stale'); END;
CREATE TRIGGER runtime_approval_resolved_immutable
        BEFORE UPDATE ON runtime_approval_requests
        WHEN OLD.status != 'pending'
        BEGIN SELECT RAISE(ABORT, 'resolved Runtime Approvals are immutable'); END;
CREATE TRIGGER fork_transfer_target_v3_authority_guard
        BEFORE UPDATE OF status, target_task_id ON fork_transfer_receipts
        WHEN NEW.status = 'transferred' AND NOT EXISTS (
            SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.target_task_id
              AND authority.authority = 'conversation_v3')
        BEGIN SELECT RAISE(ABORT, 'Fork target requires conversation_v3 authority'); END;
CREATE TRIGGER conversation_task_state_v3_authority_guard_insert
        BEFORE INSERT ON conversation_task_states
        WHEN NOT EXISTS (
            SELECT 1 FROM conversation_task_authorities AS authority
            WHERE authority.task_id = NEW.task_id
              AND authority.authority = 'conversation_v3'
        )
        BEGIN SELECT RAISE(ABORT, 'Task requires conversation_v3 authority'); END;
CREATE TRIGGER conversation_task_state_identity_immutable
        BEFORE UPDATE OF task_id, created_at ON conversation_task_states
        BEGIN SELECT RAISE(ABORT, 'conversation Task state identity is immutable'); END;
CREATE TRIGGER conversation_task_state_transition_guard
        BEFORE UPDATE OF work_status ON conversation_task_states
        WHEN NOT (
            (OLD.work_status = 'open' AND NEW.work_status IN ('completed', 'cancelled'))
            OR (OLD.work_status IN ('completed', 'cancelled') AND NEW.work_status = 'open')
        )
        BEGIN SELECT RAISE(ABORT, 'invalid conversation Task work-status transition'); END;
CREATE TRIGGER conversation_task_state_revision_guard
        BEFORE UPDATE ON conversation_task_states
        WHEN NEW.revision != OLD.revision + 1
        BEGIN SELECT RAISE(ABORT, 'conversation Task revision must advance exactly once'); END;
CREATE TRIGGER conversation_task_state_delete_forbidden
        BEFORE DELETE ON conversation_task_states
        BEGIN SELECT RAISE(ABORT, 'conversation Task state cannot be deleted'); END;
CREATE TRIGGER conversation_submission_intent_delete_forbidden
        BEFORE DELETE ON conversation_submission_intents
        BEGIN SELECT RAISE(ABORT, 'conversation submission intents are append-only'); END;
CREATE TRIGGER conversation_submission_intent_update_forbidden
        BEFORE UPDATE ON conversation_submission_intents
        BEGIN SELECT RAISE(ABORT, 'conversation submission intents are immutable'); END;
CREATE UNIQUE INDEX idx_next_turn_one_pending_task
        ON next_turn_submissions(task_id)
        WHERE status IN ('waiting', 'ready');
CREATE TRIGGER next_turn_active_blocker_guard_insert
        BEFORE INSERT ON next_turn_submissions
        WHEN NOT EXISTS (
            SELECT 1 FROM task_turns AS turn
            JOIN turn_submissions AS submission
              ON submission.submission_id = NEW.submission_id
             AND submission.task_id = NEW.task_id
            JOIN conversation_submission_intents AS intent
              ON intent.submission_id = NEW.submission_id
             AND intent.task_id = NEW.task_id
             AND intent.kind = 'next_turn'
            WHERE turn.turn_id = NEW.blocking_turn_id
              AND turn.task_id = NEW.task_id
              AND turn.status = 'in_progress'
              AND submission.status = 'queued'
        )
        BEGIN SELECT RAISE(ABORT, 'next-Turn submission requires its active blocking Turn'); END;
CREATE TRIGGER next_turn_transition_guard
        BEFORE UPDATE OF status ON next_turn_submissions
        WHEN OLD.status != 'waiting' OR NEW.status NOT IN ('ready', 'cancelled')
        BEGIN SELECT RAISE(ABORT, 'invalid next-Turn submission transition'); END;
CREATE TRIGGER next_turn_ready_blocker_terminal_guard
        BEFORE UPDATE OF status ON next_turn_submissions
        WHEN NEW.status = 'ready' AND EXISTS (
            SELECT 1 FROM task_turns AS turn
            WHERE turn.turn_id = OLD.blocking_turn_id
              AND turn.task_id = OLD.task_id
              AND turn.status = 'in_progress'
        )
        BEGIN SELECT RAISE(ABORT, 'next-Turn blocker is still active'); END;
CREATE TRIGGER next_turn_waiting_submission_claim_guard
        BEFORE UPDATE OF status ON turn_submissions
        WHEN OLD.status = 'queued' AND NEW.status = 'claimed' AND EXISTS (
            SELECT 1 FROM next_turn_submissions AS next_turn
            WHERE next_turn.submission_id = OLD.submission_id
              AND next_turn.task_id = OLD.task_id
              AND next_turn.status = 'waiting'
        )
        BEGIN SELECT RAISE(ABORT, 'waiting next-Turn submission cannot be claimed'); END;
CREATE TRIGGER next_turn_identity_immutable
        BEFORE UPDATE OF submission_id, task_id, blocking_turn_id, created_at
        ON next_turn_submissions
        BEGIN SELECT RAISE(ABORT, 'next-Turn submission identity is immutable'); END;
CREATE TRIGGER next_turn_delete_forbidden
        BEFORE DELETE ON next_turn_submissions
        BEGIN SELECT RAISE(ABORT, 'next-Turn submissions are append-only'); END;

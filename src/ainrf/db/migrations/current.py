"""Fresh-install schema baselines for the current product shape."""

from __future__ import annotations

from importlib.resources import files
import sqlite3

from ainrf.db.migration import _has_table, registry


_BASELINE_VERSIONS = {
    "agentic_researcher": 33,
    "auth": 7,
    "literature": 7,
    "terminal": 1,
}
_RETIRED_LITERATURE_TABLES = ("literature_task_sagas",)
_TASK_RESEARCHER_TYPE_CHECK = "researcher_type IN ('vanilla', 'aris-researcher')"
_TASK_HARNESS_ENGINE_CHECK = "harness_engine IN ('claude-code', 'agent-sdk', 'codex-app-server')"
_AUTH_USER_ROLE_CHECK = "role IN ('admin', 'member')"
_AUTH_USER_STATUS_CHECK = "status IN ('pending', 'active', 'disabled')"


def _apply_baseline(conn: sqlite3.Connection, database_name: str) -> None:
    """Execute baseline statements without ``executescript``'s implicit commit."""

    resource = files("ainrf.db.baselines").joinpath(f"{database_name}.sql")
    script = resource.read_text(encoding="utf-8")
    statement: list[str] = []
    for character in script:
        statement.append(character)
        if character != ";":
            continue
        candidate = "".join(statement)
        if not sqlite3.complete_statement(candidate):
            continue
        conn.execute(candidate)
        statement.clear()
    trailing = "".join(statement)
    if trailing.strip():
        conn.execute(trailing)


@registry.register("agentic_researcher")
def migration_034_conversation_cancellation_guards(conn: sqlite3.Connection) -> None:
    """Allow promoted next-Turn reservations to transition from ready to cancelled."""

    conn.execute("DROP TRIGGER IF EXISTS next_turn_transition_guard")
    conn.execute(
        """
        CREATE TRIGGER next_turn_transition_guard
            BEFORE UPDATE OF status ON next_turn_submissions
            WHEN NOT (
                (OLD.status = 'waiting' AND NEW.status IN ('ready', 'cancelled'))
                OR (OLD.status = 'ready' AND NEW.status = 'cancelled')
            )
            BEGIN SELECT RAISE(ABORT, 'invalid next-Turn submission transition'); END
        """
    )


@registry.register("agentic_researcher")
def migration_035_context_snapshot_provenance(conn: sqlite3.Connection) -> None:
    """Persist whether a queued submission inherited or overrode its Task pin."""

    columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(turn_submissions)").fetchall()
    }
    if "context_snapshot_source" in columns:
        return
    conn.execute(
        """ALTER TABLE turn_submissions
           ADD COLUMN context_snapshot_source TEXT NOT NULL DEFAULT 'task_pin'
           CHECK (context_snapshot_source IN ('task_pin', 'submission_override'))"""
    )


@registry.register("agentic_researcher")
def migration_036_retire_legacy_task_status(conn: sqlite3.Connection) -> None:
    """Remove the superseded Task lifecycle shadow after Conversation cutover."""

    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
    if "status" not in columns:
        return
    missing_authority = conn.execute(
        """
        SELECT task.task_id
        FROM tasks AS task
        LEFT JOIN conversation_task_authorities AS authority
          ON authority.task_id = task.task_id AND authority.authority = 'conversation_v3'
        LEFT JOIN conversation_task_states AS state ON state.task_id = task.task_id
        WHERE authority.task_id IS NULL OR state.task_id IS NULL
        ORDER BY task.task_id
        LIMIT 1
        """
    ).fetchone()
    if missing_authority is not None:
        raise RuntimeError(
            "agentic_researcher migration 036 refuses to drop tasks.status before "
            f"Conversation authority is complete: {missing_authority[0]}"
        )

    conn.execute("DROP INDEX IF EXISTS idx_tasks_status")
    conn.execute("DROP INDEX IF EXISTS idx_tasks_project_status")
    conn.execute("DROP INDEX IF EXISTS idx_tasks_project_lifecycle")
    conn.execute("ALTER TABLE tasks DROP COLUMN status")
    conn.execute(
        """
        CREATE INDEX idx_tasks_project_lifecycle
        ON tasks(project_id, archived_at, updated_at, task_id)
        """
    )


@registry.register("agentic_researcher")
def migration_037_retire_unproduced_runtime_approvals(conn: sqlite3.Connection) -> None:
    """Remove the disconnected approval table after proving it has no records."""

    if not _has_table(conn, "runtime_approval_requests"):
        return
    if conn.execute("SELECT 1 FROM runtime_approval_requests LIMIT 1").fetchone() is not None:
        raise RuntimeError(
            "agentic_researcher migration 037 refuses to drop non-empty runtime_approval_requests"
        )
    conn.execute("DROP TABLE runtime_approval_requests")


def _tasks_have_canonical_runtime_type_checks(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
    ).fetchone()
    if row is None or row[0] is None:
        return False
    table_sql = str(row[0])
    return _TASK_RESEARCHER_TYPE_CHECK in table_sql and _TASK_HARNESS_ENGINE_CHECK in table_sql


def _task_runtime_type_rebuild_requires_foreign_keys_off(conn: sqlite3.Connection) -> bool:
    return _has_table(conn, "tasks") and not _tasks_have_canonical_runtime_type_checks(conn)


def _schema_objects_referencing_table(
    conn: sqlite3.Connection,
    table_name: str,
) -> list[tuple[str, str, str]]:
    return [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE type IN ('trigger', 'view')
              AND sql IS NOT NULL
              AND (instr(lower(sql), ?) > 0 OR instr(lower(sql), ?) > 0)
            ORDER BY type, name
            """,
            (f" {table_name.lower()}", f'"{table_name.lower()}"'),
        )
    ]


def _table_index_statements(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL
            ORDER BY name
            """,
            (table_name,),
        )
    ]


def _drop_preserved_schema_objects(
    conn: sqlite3.Connection,
    objects: list[tuple[str, str, str]],
) -> None:
    for object_type, name, _statement in sorted(
        objects,
        key=lambda item: (item[0] != "trigger", item[1]),
    ):
        quoted_name = '"' + name.replace('"', '""') + '"'
        conn.execute(f"DROP {object_type.upper()} {quoted_name}")


def _restore_preserved_schema_objects(
    conn: sqlite3.Connection,
    objects: list[tuple[str, str, str]],
) -> None:
    for _object_type, _name, statement in sorted(
        objects,
        key=lambda item: (item[0] != "view", item[1]),
    ):
        conn.execute(statement)


@registry.register(
    "agentic_researcher",
    requires_foreign_keys_off=_task_runtime_type_rebuild_requires_foreign_keys_off,
)
def migration_038_constrain_task_runtime_types(conn: sqlite3.Connection) -> None:
    """Make the durable Task runtime type columns match their Domain contracts."""

    if _tasks_have_canonical_runtime_type_checks(conn):
        return
    if not _has_table(conn, "tasks"):
        raise RuntimeError("agentic_researcher migration 038 requires the tasks table")

    invalid = conn.execute(
        """
        SELECT task_id, researcher_type, harness_engine
        FROM tasks
        WHERE researcher_type NOT IN ('vanilla', 'aris-researcher')
           OR harness_engine NOT IN ('claude-code', 'agent-sdk', 'codex-app-server')
        ORDER BY task_id
        LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(
            "agentic_researcher migration 038 refuses non-canonical Task runtime types: "
            f"task_id={invalid[0]}, researcher_type={invalid[1]}, harness_engine={invalid[2]}"
        )

    dependent_objects = _schema_objects_referencing_table(conn, "tasks")
    index_statements = _table_index_statements(conn, "tasks")
    _drop_preserved_schema_objects(conn, dependent_objects)
    conn.execute(
        """
        CREATE TABLE tasks_migration_038 (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            researcher_type TEXT NOT NULL
                CHECK (researcher_type IN ('vanilla', 'aris-researcher')),
            harness_engine TEXT NOT NULL
                CHECK (harness_engine IN ('claude-code', 'agent-sdk', 'codex-app-server')),
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
            token_usage_json TEXT,
            api_base_url TEXT,
            api_key TEXT,
            codex_base_url TEXT,
            codex_api_key TEXT,
            codex_model TEXT,
            codex_app_server_command TEXT,
            codex_approval_policy TEXT,
            project_context_version_id TEXT,
            archived_at TEXT,
            archive_reason TEXT,
            stop_reason TEXT,
            latest_attempt_id TEXT,
            runtime_config_fingerprint TEXT,
            source_fingerprint TEXT,
            project_context_snapshot_id TEXT
                REFERENCES context_snapshots(context_snapshot_id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tasks_migration_038 (
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, user_skills, user_mcp_servers, title, prompt, created_at,
            updated_at, started_at, completed_at, latest_output_seq, owner_user_id,
            exit_code, error_summary, token_usage_json, api_base_url, api_key,
            codex_base_url, codex_api_key, codex_model, codex_app_server_command,
            codex_approval_policy, project_context_version_id, archived_at,
            archive_reason, stop_reason, latest_attempt_id, runtime_config_fingerprint,
            source_fingerprint, project_context_snapshot_id
        )
        SELECT
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, user_skills, user_mcp_servers, title, prompt, created_at,
            updated_at, started_at, completed_at, latest_output_seq, owner_user_id,
            exit_code, error_summary, token_usage_json, api_base_url, api_key,
            codex_base_url, codex_api_key, codex_model, codex_app_server_command,
            codex_approval_policy, project_context_version_id, archived_at,
            archive_reason, stop_reason, latest_attempt_id, runtime_config_fingerprint,
            source_fingerprint, project_context_snapshot_id
        FROM tasks
        """
    )
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_migration_038 RENAME TO tasks")
    for statement in index_statements:
        conn.execute(statement)
    _restore_preserved_schema_objects(conn, dependent_objects)


@registry.register("literature")
def migration_008_retire_unused_literature_task_saga(conn: sqlite3.Connection) -> None:
    """Retire the empty Literature saga artifact left by the original v7 baseline.

    The saga table was superseded by the durable research-task intent, work
    item, and outbox records. A non-empty artifact is treated as an explicit
    migration blocker so no data is silently discarded and the schema version
    remains unchanged.
    """

    non_empty = [
        table_name
        for table_name in _RETIRED_LITERATURE_TABLES
        if _has_table(conn, table_name)
        and conn.execute(f'SELECT 1 FROM "{table_name}" LIMIT 1').fetchone() is not None
    ]
    if non_empty:
        tables = ", ".join(non_empty)
        raise RuntimeError(
            "literature migration 008 refuses to retire non-empty unused tables: " + tables
        )

    for table_name in _RETIRED_LITERATURE_TABLES:
        if _has_table(conn, table_name):
            conn.execute(f'DROP TABLE "{table_name}"')


@registry.register("literature")
def migration_009_harden_literature_api_attempts(conn: sqlite3.Connection) -> None:
    """Add durable lifecycle columns and guards to external-call attempts.

    Version 8 databases already have the table but predate operation identity,
    response evidence, and response boundary timestamps.  ``ALTER TABLE``
    keeps existing rows.  A historical ``succeeded`` row without the new
    evidence is conservatively retained as ``legacy_state=succeeded`` while
    moving its active state to ``unknown``; it must be reconciled explicitly.
    """

    if not _has_table(conn, "literature_api_attempts"):
        raise RuntimeError("literature API attempt table is required by migration 009")

    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(literature_api_attempts)")}
    additions = {
        "operation": "TEXT NOT NULL DEFAULT 'external'",
        "attempt_number": "INTEGER NOT NULL DEFAULT 1",
        "response_received_at": "TEXT",
        "response_persisted_at": "TEXT",
        "response_payload": "TEXT",
        "legacy_state": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE literature_api_attempts ADD COLUMN "{name}" {definition}')

    if _has_table(conn, "literature_source_snapshots"):
        snapshot_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(literature_source_snapshots)")
        }
        snapshot_additions = {
            "attempt_id": "TEXT",
            "status_code": "INTEGER",
            "cache_control": "TEXT",
        }
        for name, definition in snapshot_additions.items():
            if name not in snapshot_columns:
                conn.execute(
                    f'ALTER TABLE literature_source_snapshots ADD COLUMN "{name}" {definition}'
                )

    conn.execute(
        """
        UPDATE literature_api_attempts
        SET state = 'unknown', legacy_state = 'succeeded',
            error_kind = 'legacy_unreconciled',
            error_message = 'Legacy succeeded row lacks response persistence evidence'
        WHERE state = 'succeeded' AND response_persisted_at IS NULL
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS literature_api_attempts_request_idx
            ON literature_api_attempts (request_fingerprint, work_item_id, attempt_number)
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS literature_api_attempts_state_insert_guard
            BEFORE INSERT ON literature_api_attempts
            WHEN NEW.state NOT IN (
                'started', 'response_received', 'response_persisted', 'succeeded',
                'retryable_failure', 'definitive_failure', 'unknown'
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid Literature API attempt state');
            END
        """
    )
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_insert_evidence_guard")
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_insert_evidence_guard
            BEFORE INSERT ON literature_api_attempts
            WHEN NEW.state IN ('response_persisted', 'succeeded')
              AND length(trim(COALESCE(NEW.response_hash, ''))) = 0
              AND length(trim(COALESCE(NEW.response_payload, ''))) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM literature_source_snapshots AS snapshot
                  WHERE snapshot.attempt_id = NEW.attempt_id
                    AND length(snapshot.body) > 0
                    AND length(trim(COALESCE(snapshot.body_hash, ''))) > 0
              )
            BEGIN
                SELECT RAISE(ABORT, 'Literature API attempt lacks durable response evidence');
            END
        """
    )
    # Recreate the guards on every migration invocation so a database created
    # by an earlier implementation cannot retain the unsafe started-to-
    # response_persisted shortcut or permit success without evidence.
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_state_transition_guard")
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_response_evidence_guard")
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_state_transition_guard
            BEFORE UPDATE OF state ON literature_api_attempts
            WHEN OLD.state != NEW.state AND NOT (
                (OLD.state = 'started' AND NEW.state IN (
                    'response_received', 'retryable_failure',
                    'definitive_failure', 'unknown'
                ))
                OR (OLD.state = 'response_received' AND NEW.state IN (
                    'response_persisted', 'retryable_failure',
                    'definitive_failure', 'unknown'
                ))
                OR (OLD.state = 'response_persisted' AND NEW.state IN (
                    'succeeded', 'unknown', 'retryable_failure',
                    'definitive_failure'
                ))
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid Literature API attempt transition');
            END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_response_evidence_guard
            BEFORE UPDATE OF state ON literature_api_attempts
            WHEN NEW.state IN ('response_persisted', 'succeeded')
              AND length(trim(COALESCE(NEW.response_hash, ''))) = 0
              AND length(trim(COALESCE(NEW.response_payload, ''))) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM literature_source_snapshots AS snapshot
                  WHERE snapshot.attempt_id = NEW.attempt_id
                    AND length(snapshot.body) > 0
                    AND length(trim(COALESCE(snapshot.body_hash, ''))) > 0
              )
            BEGIN
                SELECT RAISE(ABORT, 'Literature API attempt lacks durable response evidence');
            END
        """
    )


@registry.register("literature")
def migration_010_retire_legacy_topic_mapping(conn: sqlite3.Connection) -> None:
    """Remove the unused subscription-to-topic mapping without losing topic matches."""

    if not _has_table(conn, "literature_topics"):
        raise RuntimeError("literature topics table is required by migration 010")
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(literature_topics)")}
    if "legacy_subscription_id" not in columns:
        return
    if not _has_table(conn, "literature_topic_matches"):
        raise RuntimeError("literature topic matches table is required by migration 010")

    conn.execute(
        """
        CREATE TEMP TABLE literature_topics_v10_backup AS
        SELECT topic_id, user_id, label, include_terms_json, exclude_terms_json,
               categories_json, status, is_active, created_at, updated_at, last_matched_at
        FROM literature_topics
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE literature_topic_matches_v10_backup AS
        SELECT topic_id, paper_id, reason_json, matched_at
        FROM literature_topic_matches
        """
    )
    conn.execute("DROP TABLE literature_topic_matches")
    conn.execute("DROP TABLE literature_topics")
    conn.execute(
        """
        CREATE TABLE literature_topics (
            topic_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            label TEXT NOT NULL,
            include_terms_json TEXT NOT NULL DEFAULT '[]',
            exclude_terms_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_matched_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO literature_topics (
            topic_id, user_id, label, include_terms_json, exclude_terms_json,
            categories_json, status, is_active, created_at, updated_at, last_matched_at
        )
        SELECT topic_id, user_id, label, include_terms_json, exclude_terms_json,
               categories_json, status, is_active, created_at, updated_at, last_matched_at
        FROM literature_topics_v10_backup
        """
    )
    conn.execute(
        """
        CREATE TABLE literature_topic_matches (
            topic_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            reason_json TEXT NOT NULL DEFAULT '[]',
            matched_at TEXT NOT NULL,
            PRIMARY KEY(topic_id, paper_id),
            FOREIGN KEY (topic_id) REFERENCES literature_topics(topic_id),
            FOREIGN KEY (paper_id) REFERENCES literature_catalog_papers(paper_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO literature_topic_matches (topic_id, paper_id, reason_json, matched_at)
        SELECT topic_id, paper_id, reason_json, matched_at
        FROM literature_topic_matches_v10_backup
        """
    )
    conn.execute("DROP TABLE literature_topics_v10_backup")
    conn.execute("DROP TABLE literature_topic_matches_v10_backup")
    conn.execute("CREATE INDEX idx_lit_topics_user ON literature_topics(user_id, is_active)")
    conn.execute("CREATE INDEX idx_lit_matches_paper ON literature_topic_matches(paper_id)")


@registry.register("literature")
def migration_011_retire_duplicate_research_task_links(conn: sqlite3.Connection) -> None:
    """Drop the write-only Task link mirror after proving intent equivalence."""

    if not _has_table(conn, "literature_research_task_links"):
        return
    if not _has_table(conn, "literature_research_task_intents"):
        raise RuntimeError("literature research Task intents are required by migration 011")

    mismatch = conn.execute(
        """
        SELECT link.link_id
        FROM literature_research_task_links AS link
        LEFT JOIN literature_research_task_intents AS intent
          ON intent.task_idempotency_key = link.idempotency_key
        WHERE intent.intent_id IS NULL
           OR link.link_id IS NOT ('research-link:' || intent.intent_id)
           OR link.user_id IS NOT intent.user_id
           OR link.paper_id IS NOT intent.paper_id
           OR link.task_id IS NOT intent.task_id
           OR link.status IS NOT 'completed'
           OR intent.status IS NOT 'completed'
           OR link.payload_json IS NOT intent.request_input_json
           OR link.created_at IS NOT intent.created_at
           OR link.completed_at IS NOT intent.completed_at
           OR link.last_error IS NOT NULL
           OR intent.last_error IS NOT NULL
        ORDER BY link.link_id
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "literature migration 011 refuses to drop a non-canonical research Task link: "
            f"{mismatch[0]}"
        )
    conn.execute("DROP TABLE literature_research_task_links")


@registry.register("auth")
def migration_008_retire_environment_access_audit_events(conn: sqlite3.Connection) -> None:
    """Drop the write-only grant event ledger after proving current authority alignment."""

    if not _has_table(conn, "environment_access_audit_events"):
        return
    if not _has_table(conn, "environment_access"):
        raise RuntimeError("auth migration 008 requires environment access authority")

    orphan = conn.execute(
        """
        SELECT event.event_id
        FROM environment_access_audit_events AS event
        LEFT JOIN environment_access AS access
          ON access.environment_id = event.environment_id
         AND access.user_id = event.user_id
        WHERE access.environment_id IS NULL
        ORDER BY event.event_id
        LIMIT 1
        """
    ).fetchone()
    if orphan is not None:
        raise RuntimeError(
            f"auth migration 008 refuses to drop an orphan Environment access event: {orphan[0]}"
        )

    mismatch = conn.execute(
        """
        WITH history AS (
            SELECT environment_id, user_id,
                   COUNT(*) AS event_count,
                   COUNT(DISTINCT grant_version) AS distinct_versions,
                   MIN(grant_version) AS first_version,
                   MAX(grant_version) AS last_version
            FROM environment_access_audit_events
            GROUP BY environment_id, user_id
        )
        SELECT access.environment_id || '/' || access.user_id
        FROM environment_access AS access
        LEFT JOIN history
          ON history.environment_id = access.environment_id
         AND history.user_id = access.user_id
        LEFT JOIN environment_access_audit_events AS latest
          ON latest.environment_id = access.environment_id
         AND latest.user_id = access.user_id
         AND latest.grant_version = access.grant_version
        WHERE history.environment_id IS NULL
           OR history.first_version != 1
           OR history.last_version != access.grant_version
           OR history.event_count != access.grant_version
           OR history.distinct_versions != access.grant_version
           OR latest.event_id IS NULL
           OR latest.event_type IS NOT CASE
                WHEN access.status = 'active' THEN 'granted'
                WHEN access.status = 'revoked' THEN 'revoked'
                ELSE NULL
              END
           OR latest.actor_user_id IS NOT CASE
                WHEN access.status = 'active' THEN access.granted_by_user_id
                WHEN access.status = 'revoked' THEN access.revoked_by_user_id
                ELSE NULL
              END
           OR latest.max_concurrent_tasks IS NOT access.max_concurrent_tasks
           OR latest.reason IS NOT CASE
                WHEN access.status = 'active' THEN access.grant_reason
                WHEN access.status = 'revoked' THEN access.revocation_reason
                ELSE NULL
              END
           OR latest.occurred_at IS NOT CASE
                WHEN access.status = 'active' THEN access.granted_at
                WHEN access.status = 'revoked' THEN access.revoked_at
                ELSE NULL
              END
        ORDER BY access.environment_id, access.user_id
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "auth migration 008 refuses to drop non-canonical Environment access history: "
            f"{mismatch[0]}"
        )

    conn.execute("DROP TABLE environment_access_audit_events")
    conn.execute("DROP TRIGGER IF EXISTS trg_env_access_prevent_delete")
    conn.execute(
        """
        CREATE TRIGGER trg_env_access_prevent_delete
        BEFORE DELETE ON environment_access
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant authority must be revoked, not deleted');
        END
        """
    )


@registry.register("auth")
def migration_009_retire_legacy_project_collaborators(conn: sqlite3.Connection) -> None:
    """Drop the superseded auth collaborator table only when it has no rows."""

    if not _has_table(conn, "project_collaborators"):
        return
    if conn.execute("SELECT 1 FROM project_collaborators LIMIT 1").fetchone() is not None:
        raise RuntimeError(
            "auth migration 009 refuses to drop non-empty legacy project_collaborators"
        )
    conn.execute("DROP TABLE project_collaborators")


def _users_have_canonical_role_status_checks(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None or row[0] is None:
        return False
    table_sql = str(row[0])
    return _AUTH_USER_ROLE_CHECK in table_sql and _AUTH_USER_STATUS_CHECK in table_sql


def _auth_user_rebuild_requires_foreign_keys_off(conn: sqlite3.Connection) -> bool:
    return _has_table(conn, "users") and not _users_have_canonical_role_status_checks(conn)


@registry.register(
    "auth",
    requires_foreign_keys_off=_auth_user_rebuild_requires_foreign_keys_off,
)
def migration_010_constrain_user_role_status(conn: sqlite3.Connection) -> None:
    """Make durable user role and status columns match Auth Domain contracts."""

    if _users_have_canonical_role_status_checks(conn):
        return
    if not _has_table(conn, "users"):
        raise RuntimeError("auth migration 010 requires the users table")

    invalid = conn.execute(
        """
        SELECT id, role, status
        FROM users
        WHERE role NOT IN ('admin', 'member')
           OR status NOT IN ('pending', 'active', 'disabled')
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(
            "auth migration 010 refuses non-canonical user role/status: "
            f"user_id={invalid[0]}, role={invalid[1]}, status={invalid[2]}"
        )

    dependent_objects = _schema_objects_referencing_table(conn, "users")
    index_statements = _table_index_statements(conn, "users")
    _drop_preserved_schema_objects(conn, dependent_objects)
    conn.execute(
        """
        CREATE TABLE users_migration_010 (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('admin', 'member')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
            created_at TEXT NOT NULL,
            activated_at TEXT,
            last_login_at TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO users_migration_010 (
            id, username, password_hash, display_name, role, status, created_at,
            activated_at, last_login_at, must_change_password
        )
        SELECT
            id, username, password_hash, display_name, role, status, created_at,
            activated_at, last_login_at, must_change_password
        FROM users
        """
    )
    conn.execute("DROP TABLE users")
    conn.execute("ALTER TABLE users_migration_010 RENAME TO users")
    for statement in index_statements:
        conn.execute(statement)
    _restore_preserved_schema_objects(conn, dependent_objects)


@registry.register_baseline("agentic_researcher", _BASELINE_VERSIONS["agentic_researcher"])
def agentic_researcher_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "agentic_researcher")


@registry.register_baseline("auth", _BASELINE_VERSIONS["auth"])
def auth_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "auth")


@registry.register_baseline("literature", _BASELINE_VERSIONS["literature"])
def literature_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "literature")


@registry.register_baseline("terminal", _BASELINE_VERSIONS["terminal"])
def terminal_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "terminal")

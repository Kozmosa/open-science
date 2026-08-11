from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from ainrf.db.migration import SchemaBaselineError, current_version, run_pending
from ainrf.db.migrations.current import (
    migration_009_harden_literature_api_attempts,
    migration_034_conversation_cancellation_guards,
    migration_035_context_snapshot_provenance,
    migration_036_retire_legacy_task_status,
)
from ainrf.domain.conversation_projection import ConversationProjectionService
from ainrf.db.retire_legacy import migrate, preflight, verify
from ainrf.literature.tracking import LiteratureTrackingService


pytestmark = [pytest.mark.unit]


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _build_v33_artifact(path: Path) -> None:
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('agentic_researcher', 33)")
        connection.commit()


def _build_v7_literature_artifact(
    path: Path,
    *,
    include_task_sagas: bool = True,
) -> None:
    """Build the prior v7 shape with the removed saga DDL explicitly restored."""

    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    with _connect(path) as connection:
        connection.executescript(baseline)
        if include_task_sagas:
            connection.execute("CREATE TABLE literature_task_sagas (saga_id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 7)")
        connection.commit()


def _build_v9_literature_artifact(path: Path) -> None:
    """Build the prior topic schema with its unused legacy mapping column."""

    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    with _connect(path) as connection:
        connection.executescript(baseline)
        migration_009_harden_literature_api_attempts(connection)
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE literature_topic_matches")
        connection.execute("DROP TABLE literature_topics")
        connection.execute(
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
                legacy_subscription_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_matched_at TEXT
            )
            """
        )
        connection.execute(
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
        connection.execute(
            "CREATE INDEX idx_lit_topics_user ON literature_topics(user_id, is_active)"
        )
        connection.execute(
            "CREATE INDEX idx_lit_matches_paper ON literature_topic_matches(paper_id)"
        )
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 9)")
        connection.commit()


def _build_v10_literature_artifact(path: Path) -> None:
    """Build the prior schema with its write-only research Task link mirror."""

    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 10)")
        connection.commit()


def _seed_completed_research_task_link(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO literature_catalog_papers (
            paper_id, provider, external_id, title, first_seen_at, last_seen_at
        ) VALUES ('paper-1', 'arxiv', '2401.00001', 'Paper', 'created', 'seen')
        """
    )
    connection.execute(
        """
        INSERT INTO literature_work_items (
            work_item_id, kind, idempotency_key, status, payload_json,
            available_at, created_at, updated_at
        ) VALUES (
            'work-1', 'research_task', 'research-task:intent-1', 'completed',
            '{"intent_id":"intent-1"}', 'created', 'created', 'completed'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO literature_research_task_intents (
            intent_id, user_id, paper_id, project_id, workspace_id, actor_role,
            task_preset, title, request_input_json, request_hash, idempotency_key,
            task_idempotency_key, task_id, status, work_item_id, created_at,
            updated_at, completed_at
        ) VALUES (
            'intent-1', 'owner', 'paper-1', 'project-1', 'workspace-1', 'member',
            'raw_prompt', 'Research Paper', '{"prompt":"inspect"}', 'request-hash',
            'request-key', 'task-key', 'task-1', 'completed', 'work-1',
            'created', 'completed', 'completed'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO literature_research_task_links (
            link_id, user_id, paper_id, task_id, idempotency_key, status,
            payload_json, created_at, completed_at, last_error
        ) VALUES (
            'research-link:intent-1', 'owner', 'paper-1', 'task-1', 'task-key',
            'completed', '{"prompt":"inspect"}', 'created', 'completed', NULL
        )
        """
    )
    connection.commit()


def _schema_objects(connection: sqlite3.Connection) -> set[tuple[str, str, str | None]]:
    return {
        (str(row["type"]), str(row["name"]), row["sql"])
        for row in connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name != '_schema_version'"
        )
    }


def _build_v34_artifact(path: Path) -> None:
    _build_v33_artifact(path)
    with _connect(path) as connection:
        migration_034_conversation_cancellation_guards(connection)
        connection.execute(
            "UPDATE _schema_version SET version = 34 WHERE database = 'agentic_researcher'"
        )
        connection.commit()


def _build_v35_artifact(path: Path) -> None:
    _build_v34_artifact(path)
    with _connect(path) as connection:
        migration_035_context_snapshot_provenance(connection)
        connection.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
        connection.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
        connection.execute("CREATE INDEX idx_tasks_project_status ON tasks(project_id, status)")
        connection.execute("DROP INDEX idx_tasks_project_lifecycle")
        connection.execute(
            """
            CREATE INDEX idx_tasks_project_lifecycle
            ON tasks(project_id, archived_at, status, updated_at, task_id)
            """
        )
        connection.execute(
            "UPDATE _schema_version SET version = 35 WHERE database = 'agentic_researcher'"
        )
        connection.commit()


def _build_v36_approval_artifact(path: Path) -> None:
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        migration_034_conversation_cancellation_guards(connection)
        migration_035_context_snapshot_provenance(connection)
        migration_036_retire_legacy_task_status(connection)
        connection.execute("CREATE TABLE runtime_approval_requests (approval_id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('agentic_researcher', 36)")
        connection.commit()


@pytest.mark.parametrize(
    ("database", "version"),
    [("auth", 7), ("agentic_researcher", 37), ("literature", 11), ("terminal", 1)],
)
def test_fresh_install_uses_current_baseline(tmp_path: Path, database: str, version: int) -> None:
    path = tmp_path / f"{database}.sqlite3"
    with _connect(path) as connection:
        assert run_pending(connection, database) >= 1
        assert current_version(connection, database) == version
        assert run_pending(connection, database) == 0


def test_fresh_literature_schema_retires_superseded_saga_and_keeps_current_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "literature.sqlite3"
    with _connect(path) as connection:
        assert run_pending(connection, "literature") == 5
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert current_version(connection, "literature") == 11

    assert {
        "literature_research_task_intents",
        "literature_work_items",
        "literature_outbox",
    } <= tables
    assert "literature_api_attempts" in tables
    assert "literature_task_sagas" not in tables
    assert "literature_research_task_links" not in tables


def test_literature_v7_empty_artifact_migrates_to_fresh_schema(tmp_path: Path) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    artifact_path = tmp_path / "v7-artifact.sqlite3"
    with _connect(fresh_path) as connection:
        assert run_pending(connection, "literature") == 5
        fresh_schema = _schema_objects(connection)

    _build_v7_literature_artifact(artifact_path)
    with _connect(artifact_path) as connection:
        assert run_pending(connection, "literature") == 4
        assert current_version(connection, "literature") == 11
        artifact_schema = _schema_objects(connection)

    assert artifact_schema == fresh_schema


def test_literature_v7_artifact_without_retired_tables_advances(tmp_path: Path) -> None:
    path = tmp_path / "v7-without-retired-tables.sqlite3"
    _build_v7_literature_artifact(
        path,
        include_task_sagas=False,
    )
    with _connect(path) as connection:
        assert run_pending(connection, "literature") == 4
        assert current_version(connection, "literature") == 11


def test_literature_v9_topic_mapping_migrates_without_losing_topics_or_matches(
    tmp_path: Path,
) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    artifact_path = tmp_path / "v9-topic-mapping.sqlite3"
    with _connect(fresh_path) as connection:
        run_pending(connection, "literature")
        fresh_schema = _schema_objects(connection)

    _build_v9_literature_artifact(artifact_path)
    with _connect(artifact_path) as connection:
        connection.execute(
            """
            INSERT INTO literature_catalog_papers (
                paper_id, provider, external_id, title, first_seen_at, last_seen_at
            ) VALUES ('paper-1', 'arxiv', '2401.00001', 'Paper', 'created', 'seen')
            """
        )
        connection.execute(
            """
            INSERT INTO literature_topics (
                topic_id, user_id, label, include_terms_json, exclude_terms_json,
                categories_json, status, is_active, legacy_subscription_id,
                created_at, updated_at, last_matched_at
            ) VALUES (
                'topic-1', 'owner', 'Agents', '["agent"]', '["legacy"]',
                '["cs.AI"]', 'active', 1, 'subscription-1',
                'created', 'updated', 'matched'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO literature_topic_matches (topic_id, paper_id, reason_json, matched_at)
            VALUES ('topic-1', 'paper-1', '["category"]', 'matched')
            """
        )
        connection.commit()

        assert run_pending(connection, "literature") == 2
        assert current_version(connection, "literature") == 11
        assert "legacy_subscription_id" not in {
            str(row[1]) for row in connection.execute("PRAGMA table_info(literature_topics)")
        }
        assert tuple(
            connection.execute(
                """
                SELECT topic_id, user_id, label, include_terms_json, exclude_terms_json,
                       categories_json, status, is_active, created_at, updated_at, last_matched_at
                FROM literature_topics
                """
            ).fetchone()
        ) == (
            "topic-1",
            "owner",
            "Agents",
            '["agent"]',
            '["legacy"]',
            '["cs.AI"]',
            "active",
            1,
            "created",
            "updated",
            "matched",
        )
        assert tuple(
            connection.execute(
                "SELECT topic_id, paper_id, reason_json, matched_at FROM literature_topic_matches"
            ).fetchone()
        ) == ("topic-1", "paper-1", '["category"]', "matched")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert _schema_objects(connection) == fresh_schema


def test_literature_v9_topic_mapping_drop_failure_rolls_back_data_and_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v9-topic-mapping-failure.sqlite3"
    _build_v9_literature_artifact(path)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO literature_topics (
                topic_id, user_id, label, legacy_subscription_id, created_at, updated_at
            ) VALUES ('topic-1', 'owner', 'Agents', 'subscription-1', 'created', 'updated')
            """
        )
        connection.commit()

        def deny_topic_drop(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_DROP_TABLE and arg1 == "literature_topics"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_topic_drop)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "literature")
        connection.set_authorizer(None)

        assert current_version(connection, "literature") == 9
        assert "legacy_subscription_id" in {
            str(row[1]) for row in connection.execute("PRAGMA table_info(literature_topics)")
        }
        assert tuple(
            connection.execute(
                "SELECT topic_id, legacy_subscription_id FROM literature_topics"
            ).fetchone()
        ) == ("topic-1", "subscription-1")
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'literature_topic_matches'"
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "SELECT name FROM temp.sqlite_master "
                "WHERE name IN ('literature_topics_v10_backup', "
                "'literature_topic_matches_v10_backup')"
            ).fetchall()
            == []
        )

        assert run_pending(connection, "literature") == 2
        assert current_version(connection, "literature") == 11


def test_literature_v10_retires_canonical_research_task_link_mirror(tmp_path: Path) -> None:
    path = tmp_path / "v10-research-task-links.sqlite3"
    _build_v10_literature_artifact(path)
    with _connect(path) as connection:
        _seed_completed_research_task_link(connection)

        assert run_pending(connection, "literature") == 1
        assert current_version(connection, "literature") == 11
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'literature_research_task_links'"
            ).fetchone()
            is None
        )
        intent = connection.execute(
            "SELECT status, task_id, request_input_json FROM literature_research_task_intents"
        ).fetchone()
        assert intent is not None
        assert tuple(intent) == ("completed", "task-1", '{"prompt":"inspect"}')


def test_literature_v10_research_task_link_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "v10-research-task-link-mismatch.sqlite3"
    _build_v10_literature_artifact(path)
    with _connect(path) as connection:
        _seed_completed_research_task_link(connection)
        connection.execute("UPDATE literature_research_task_links SET task_id = 'conflicting-task'")
        connection.commit()

        with pytest.raises(RuntimeError, match="non-canonical research Task link"):
            run_pending(connection, "literature")

        assert current_version(connection, "literature") == 10
        link = connection.execute("SELECT task_id FROM literature_research_task_links").fetchone()
        assert link is not None and link["task_id"] == "conflicting-task"

        connection.execute("UPDATE literature_research_task_links SET task_id = 'task-1'")
        connection.commit()
        assert run_pending(connection, "literature") == 1
        assert current_version(connection, "literature") == 11


@pytest.mark.parametrize(
    ("table_name", "value"),
    [("literature_task_sagas", "saga-1")],
)
def test_literature_v7_non_empty_retired_table_fails_closed(
    tmp_path: Path, table_name: str, value: str
) -> None:
    path = tmp_path / f"non-empty-{table_name}.sqlite3"
    _build_v7_literature_artifact(path)
    column = "saga_id"
    with _connect(path) as connection:
        connection.execute(f'INSERT INTO "{table_name}" ("{column}") VALUES (?)', (value,))
        connection.commit()
        with pytest.raises(RuntimeError, match="refuses to retire non-empty"):
            run_pending(connection, "literature")

        assert current_version(connection, "literature") == 7
        assert connection.execute(f'SELECT "{column}" FROM "{table_name}"').fetchone()[0] == value
        table_names = {
            name
            for object_type, name, _sql in _schema_objects(connection)
            if object_type == "table"
        }
        assert {"literature_api_attempts", "literature_task_sagas"} <= table_names


def test_literature_saga_retirement_drop_failure_rolls_back_tables_and_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "drop-failure.sqlite3"
    _build_v7_literature_artifact(path)
    with _connect(path) as connection:

        def deny_saga_drop(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_DROP_TABLE and arg1 == "literature_task_sagas"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_saga_drop)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "literature")
        connection.set_authorizer(None)

        assert current_version(connection, "literature") == 7
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('literature_api_attempts', 'literature_task_sagas')"
            ).fetchone()[0]
            == 2
        )


def test_literature_saga_retirement_version_failure_rolls_back_tables_and_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version-failure.sqlite3"
    _build_v7_literature_artifact(path)
    with _connect(path) as connection:

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "literature")
        connection.set_authorizer(None)

        assert current_version(connection, "literature") == 7
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('literature_api_attempts', 'literature_task_sagas')"
            ).fetchone()[0]
            == 2
        )


def test_literature_api_attempt_migration_upgrades_v8_shape_and_adds_guards(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v8-attempts.sqlite3"
    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    old_attempt_table = """
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
        )
    """
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute("DROP TABLE literature_api_attempts")
        connection.execute(old_attempt_table)
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 8)")
        connection.commit()

    with _connect(path) as connection:
        assert run_pending(connection, "literature") == 3
        assert current_version(connection, "literature") == 11
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(literature_api_attempts)")
        }
        assert {
            "operation",
            "attempt_number",
            "response_received_at",
            "response_persisted_at",
        } <= columns
        trigger_names = {
            str(row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        assert {
            "literature_api_attempts_state_insert_guard",
            "literature_api_attempts_insert_evidence_guard",
            "literature_api_attempts_state_transition_guard",
            "literature_api_attempts_response_evidence_guard",
        } <= trigger_names


def test_literature_api_attempt_migration_rolls_back_on_alter_failure(tmp_path: Path) -> None:
    path = tmp_path / "v8-attempts-failure.sqlite3"
    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute("DROP TABLE literature_api_attempts")
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 8)")
        connection.commit()

        def deny_alter(
            action: int,
            _arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_alter)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "literature")
        connection.set_authorizer(None)
        assert current_version(connection, "literature") == 8


def test_literature_api_attempt_migration_quarantines_legacy_succeeded_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v8-legacy-succeeded.sqlite3"
    baseline = files("ainrf.db.baselines").joinpath("literature.sql").read_text(encoding="utf-8")
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            """
            INSERT INTO literature_api_attempts (
                attempt_id, provider, request_fingerprint, state, started_at,
                completed_at, response_hash
            ) VALUES ('legacy-1', 'anthropic', 'request-1', 'succeeded',
                      '2026-01-01T00:00:00+00:00', '2026-01-01T00:01:00+00:00', 'hash-1')
            """
        )
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('literature', 8)")
        connection.commit()

    with _connect(path) as connection:
        assert run_pending(connection, "literature") == 3
        row = connection.execute(
            "SELECT state, legacy_state, response_hash, completed_at FROM literature_api_attempts WHERE attempt_id = 'legacy-1'"
        ).fetchone()
        assert tuple(row) == (
            "unknown",
            "succeeded",
            "hash-1",
            "2026-01-01T00:01:00+00:00",
        )


@pytest.mark.parametrize("reconcile_kind", ["stale", "expired"])
def test_migrated_literature_attempt_reconciliation_honors_response_guard(
    tmp_path: Path, reconcile_kind: str
) -> None:
    root = tmp_path / "migrated-root"
    path = root / "runtime" / "literature.sqlite3"
    path.parent.mkdir(parents=True)
    _build_v7_literature_artifact(path)
    service = LiteratureTrackingService(root)
    service.initialize()
    topic = service.create_topic(
        user_id="owner",
        label="Agents",
        include_terms=[],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    service.create_check(user_id="owner", topic_ids=[topic["topic_id"]])
    item = service.claim_work_item_by_id(
        service.pending_outbox_work_ids()[0], worker_id="migration-recovery"
    )
    assert item is not None
    attempt = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"]},
        check_id=str(item.payload["check_id"]),
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    snapshot = service.persist_rss_snapshot(
        attempt_id=attempt.attempt_id,
        check_id=str(item.payload["check_id"]),
        scope_id=str(item.payload["scope_id"]),
        body=b"migrated raw rss evidence",
        etag=None,
        last_modified=None,
        cache_control=None,
        status_code=200,
    )
    with service._connect() as conn:
        if reconcile_kind == "stale":
            conn.execute(
                "UPDATE literature_api_attempts SET started_at = '2020-01-01T00:00:00+00:00' WHERE attempt_id = ?",
                (attempt.attempt_id,),
            )
        else:
            conn.execute(
                "UPDATE literature_work_items SET lease_expires_at = '2020-01-01T00:00:00+00:00' WHERE work_item_id = ?",
                (item.work_item_id,),
            )

    if reconcile_kind == "stale":
        service.reconcile_stale_api_attempts(stale_after_seconds=0)
    else:
        service.reconcile_expired_work_items()

    recovered = service.api_attempt(attempt.attempt_id)
    assert recovered is not None
    assert recovered.state == "response_persisted"
    assert recovered.response_received_at is not None
    assert recovered.response_persisted_at is not None
    assert recovered.status_code == 200
    assert recovered.response_hash == snapshot["body_hash"]


def test_fresh_domain_baseline_contains_current_authority_only(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    with _connect(path) as connection:
        run_pending(connection, "agentic_researcher")
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        task_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)")}
    assert {"tasks", "task_turns", "turn_items", "runtime_executions"} <= tables
    assert "status" not in task_columns
    assert not tables & {
        "agent_task_attempts",
        "agent_runtime_sessions",
        "task_dispatch_outbox",
        "task_outputs",
        "domain_cutover_state",
        "domain_migration_runs",
    }


def test_fresh_baseline_version_write_failure_rolls_back_all_schema(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    with _connect(path) as connection:
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        denied = False

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version":
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert denied
        assert not connection.in_transaction
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name != '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version

    with _connect(path) as reopened:
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name != '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == before_user_version


def test_fresh_baseline_honors_caller_transaction_success_and_failure(tmp_path: Path) -> None:
    success_path = tmp_path / "success.sqlite3"
    with _connect(success_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (1)")
        assert run_pending(connection, "agentic_researcher") == 5
        assert connection.in_transaction
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (2)")
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 1
        connection.commit()

    with _connect(success_path) as connection:
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 2
        assert current_version(connection, "agentic_researcher") == 37

    failure_path = tmp_path / "failure.sqlite3"
    with _connect(failure_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (3)")
        denied = False

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version":
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert denied
        assert connection.in_transaction
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'tasks'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (4)")
        connection.commit()

    with _connect(failure_path) as connection:
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 4
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'tasks'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = '_schema_version'"
            ).fetchone()[0]
            == 0
        )


def test_existing_v33_domain_migrates_cancellation_guards(tmp_path: Path) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    artifact_path = tmp_path / "v33-artifact.sqlite3"
    with _connect(fresh_path) as fresh:
        assert run_pending(fresh, "agentic_researcher") == 5
        assert current_version(fresh, "agentic_researcher") == 37
        assert fresh.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        fresh_schema = {
            (str(row["type"]), str(row["name"])): str(row["sql"])
            for row in fresh.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name IN ('turn_submissions', 'next_turn_transition_guard')"
            )
        }
    _build_v33_artifact(artifact_path)
    with _connect(artifact_path) as connection:
        assert run_pending(connection, "agentic_researcher") == 4
        assert current_version(connection, "agentic_researcher") == 37
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        artifact_schema = {
            (str(row["type"]), str(row["name"])): str(row["sql"])
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name IN ('turn_submissions', 'next_turn_transition_guard')"
            )
        }
    assert artifact_schema == fresh_schema
    assert (
        "status = 'delivery_unknown' AND finished_at IS NULL"
        in artifact_schema[("table", "turn_submissions")]
    )
    assert (
        "OLD.status = 'ready' AND NEW.status = 'cancelled'"
        in artifact_schema[("trigger", "next_turn_transition_guard")]
    )
    assert "context_snapshot_source" in fresh_schema[("table", "turn_submissions")]
    assert "context_snapshot_source" in artifact_schema[("table", "turn_submissions")]

    v34_path = tmp_path / "v34-artifact.sqlite3"
    _build_v34_artifact(v34_path)
    with _connect(v34_path) as connection:
        assert run_pending(connection, "agentic_researcher") == 3
        assert current_version(connection, "agentic_researcher") == 37
        v34_schema = {
            (str(row["type"]), str(row["name"])): str(row["sql"])
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name IN ('turn_submissions', 'next_turn_transition_guard')"
            )
        }
    assert v34_schema == fresh_schema


def test_run_pending_rolls_back_when_nested_savepoint_release_is_denied(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    _build_v33_artifact(path)
    with _connect(path) as connection:
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_version = current_version(connection, "agentic_researcher")
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE caller_ordinary (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_ordinary VALUES (1)")
        connection.execute("CREATE TEMP TABLE caller_temp (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO caller_temp VALUES (2)")

        def deny_release(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_SAVEPOINT and arg1 == "RELEASE"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_release)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert connection.in_transaction
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 2
        assert current_version(connection, "agentic_researcher") == before_version == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )
        assert run_pending(connection, "agentic_researcher") == 4
        assert current_version(connection, "agentic_researcher") == 37
        assert connection.execute("SELECT * FROM caller_ordinary").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM caller_temp").fetchone()[0] == 2
        connection.commit()


def test_run_pending_rolls_back_when_schema_version_write_is_denied(tmp_path: Path) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    _build_v33_artifact(path)
    with _connect(path) as connection:
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_version = current_version(connection, "agentic_researcher")
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        before_user_version = connection.execute("PRAGMA user_version").fetchone()[0]

        def deny_schema_version_insert(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and arg1 == "_schema_version"
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_schema_version_insert)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)

        assert current_version(connection, "agentic_researcher") == before_version == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_user_version
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )


def test_migration_034_rolls_back_trigger_and_version_on_injected_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agentic_researcher.sqlite3"
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        connection.execute(
            "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO _schema_version VALUES ('agentic_researcher', 33)")
        connection.commit()
        before_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'next_turn_transition_guard'"
        ).fetchone()[0]
        before_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
        ).fetchone()[0]
        before_foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

        def deny_trigger_creation(
            action: int,
            _arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_CREATE_TRIGGER
                else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_trigger_creation)
        with pytest.raises(sqlite3.DatabaseError):
            try:
                run_pending(connection, "agentic_researcher")
            except BaseException:
                connection.rollback()
                raise
        connection.set_authorizer(None)
        assert current_version(connection, "agentic_researcher") == 33
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == before_foreign_keys
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'next_turn_transition_guard'"
            ).fetchone()[0]
            == before_trigger
        )
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'turn_submissions'"
            ).fetchone()[0]
            == before_table
        )


def test_migration_035_rolls_back_provenance_column_and_version_on_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v34-artifact.sqlite3"
    _build_v34_artifact(path)
    with _connect(path) as connection:

        def deny_alter_table(
            action: int,
            _arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _source: str | None,
        ) -> int:
            return (
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK
            )

        connection.set_authorizer(deny_alter_table)
        with pytest.raises(sqlite3.DatabaseError):
            run_pending(connection, "agentic_researcher")
        connection.set_authorizer(None)
        assert current_version(connection, "agentic_researcher") == 34
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(turn_submissions)")
        }
        assert "context_snapshot_source" not in columns
        assert run_pending(connection, "agentic_researcher") == 3
        assert current_version(connection, "agentic_researcher") == 37
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(turn_submissions)")
        }
        assert "context_snapshot_source" in columns


def test_migration_036_drops_legacy_task_status_after_conversation_cutover(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v35-task-status.sqlite3"
    _build_v35_artifact(path)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-shadow', 'project-1', 'workspace-1', 'environment-1', 'general',
                'codex-app-server', 'failed', 'Shadow', 'test', 'now', 'now', 'user-1'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO conversation_task_authorities (task_id, authority, created_at)
            VALUES ('task-shadow', 'conversation_v3', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO conversation_task_states (task_id, created_at, updated_at)
            VALUES ('task-shadow', 'now', 'now')
            """
        )
        connection.commit()

        assert run_pending(connection, "agentic_researcher") == 2
        assert current_version(connection, "agentic_researcher") == 37
        columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)")}
        assert "status" not in columns
        indexes = {
            str(row["name"]): str(row["sql"])
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tasks'"
            )
        }
        assert "idx_tasks_status" not in indexes
        assert "idx_tasks_project_status" not in indexes
        assert "status" not in indexes["idx_tasks_project_lifecycle"]
        projection = ConversationProjectionService().projections_for_tasks(
            connection, ["task-shadow"]
        )["task-shadow"]
        assert projection.status == "queued"


def test_migration_036_refuses_incomplete_conversation_authority(tmp_path: Path) -> None:
    path = tmp_path / "v35-incomplete-authority.sqlite3"
    _build_v35_artifact(path)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-incomplete', 'project-1', 'workspace-1', 'environment-1', 'general',
                'codex-app-server', 'queued', 'Incomplete', 'test', 'now', 'now', 'user-1'
            )
            """
        )
        connection.commit()

        with pytest.raises(RuntimeError, match="Conversation authority is complete"):
            run_pending(connection, "agentic_researcher")
        assert current_version(connection, "agentic_researcher") == 35
        assert "status" in {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)")
        }


def test_migration_037_retires_empty_unproduced_runtime_approval_table(
    tmp_path: Path,
) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    artifact_path = tmp_path / "v36-runtime-approvals.sqlite3"
    with _connect(fresh_path) as connection:
        run_pending(connection, "agentic_researcher")
        fresh_schema = _schema_objects(connection)

    _build_v36_approval_artifact(artifact_path)
    with _connect(artifact_path) as connection:
        assert run_pending(connection, "agentic_researcher") == 1
        assert current_version(connection, "agentic_researcher") == 37
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'runtime_approval_requests'"
            ).fetchone()
            is None
        )
        assert _schema_objects(connection) == fresh_schema


def test_migration_037_refuses_non_empty_runtime_approval_table(tmp_path: Path) -> None:
    path = tmp_path / "v36-non-empty-runtime-approvals.sqlite3"
    _build_v36_approval_artifact(path)
    with _connect(path) as connection:
        connection.execute(
            "INSERT INTO runtime_approval_requests (approval_id) VALUES ('approval-1')"
        )
        connection.commit()

        with pytest.raises(RuntimeError, match="refuses to drop non-empty"):
            run_pending(connection, "agentic_researcher")

        assert current_version(connection, "agentic_researcher") == 36
        assert (
            connection.execute("SELECT approval_id FROM runtime_approval_requests").fetchone()[0]
            == "approval-1"
        )


def test_prebaseline_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "prebaseline.sqlite3"
    with _connect(path) as connection:
        connection.execute("CREATE TABLE legacy_table (id TEXT PRIMARY KEY)")
        connection.commit()
        with pytest.raises(SchemaBaselineError, match="pre-baseline schema"):
            run_pending(connection, "agentic_researcher")


def _make_retiring_state(state_root: Path, *, active_runtime: bool = False) -> Path:
    database = state_root / "runtime" / "agentic_researcher.sqlite3"
    database.parent.mkdir(parents=True)
    with _connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL);
            INSERT INTO _schema_version VALUES ('agentic_researcher', 32);
            CREATE TABLE domain_maintenance_state (
                singleton INTEGER PRIMARY KEY, is_active INTEGER NOT NULL
            );
            INSERT INTO domain_maintenance_state VALUES (1, 1);
            CREATE TABLE domain_cutover_state (
                singleton INTEGER PRIMARY KEY, state TEXT NOT NULL, first_v2_write_at TEXT
            );
            INSERT INTO domain_cutover_state VALUES (1, 'v2', '2026-08-05T00:00:00+00:00');
            CREATE TABLE agent_runtime_sessions (runtime_session_id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE agent_task_attempts (attempt_id TEXT PRIMARY KEY, task_id TEXT);
            CREATE TABLE task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY);
            CREATE TABLE task_outputs (output_id TEXT PRIMARY KEY);
            CREATE TABLE task_attempt_control_requests (control_request_id TEXT PRIMARY KEY);
            CREATE TABLE domain_cutover_events (event_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_issues (issue_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_record_results (result_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_resolutions (resolution_id TEXT PRIMARY KEY);
            CREATE TABLE domain_migration_runs (run_id TEXT PRIMARY KEY);
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
            """
        )
        if active_runtime:
            connection.execute("INSERT INTO agent_runtime_sessions VALUES ('runtime-1', 'running')")
        connection.execute(
            "INSERT INTO legacy_domain_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-1",
                "run-1",
                "task",
                "{}",
                "2026-08-05T00:00:00+00:00",
                None,
                None,
                None,
                "audit",
            ),
        )
        connection.commit()
    return database


def test_retirement_migration_drops_legacy_tables_and_keeps_audit(tmp_path: Path) -> None:
    database = _make_retiring_state(tmp_path)
    report = migrate(tmp_path)
    assert report.ready
    assert verify(tmp_path).ready
    with _connect(database) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "legacy_domain_records" in tables
        assert "agent_task_attempts" not in tables
        assert (
            connection.execute("SELECT legacy_record_id FROM legacy_domain_records").fetchone()[0]
            == "legacy-1"
        )


def test_retirement_migration_removes_retired_telemetry_payloads(tmp_path: Path) -> None:
    _make_retiring_state(tmp_path)
    runtime_root = tmp_path / "runtime"
    telemetry_path = runtime_root / "domain_telemetry.sqlite3"
    with _connect(telemetry_path) as connection:
        connection.executescript(
            """
            CREATE TABLE domain_telemetry_counter_totals (
                metric_name TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                value REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(metric_name, labels_json)
            );
            CREATE TABLE domain_telemetry_snapshots (
                singleton INTEGER PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            INSERT INTO domain_telemetry_counter_totals VALUES (
                'ainrf_domain_legacy_write_attempts_total', '{"source":"legacy_json"}',
                1, '2026-08-05T00:00:00+00:00'
            );
            INSERT INTO domain_telemetry_counter_totals VALUES (
                'ainrf_domain_idempotency_requests_total', '{"outcome":"accepted"}',
                2, '2026-08-05T00:00:00+00:00'
            );
            INSERT INTO domain_telemetry_snapshots VALUES (
                1, 2, '2026-08-05T00:00:00+00:00', '{"schema_version":2}'
            );
            """
        )
        connection.commit()
    anchor_path = runtime_root / "domain_telemetry_anchor.json"
    anchor_path.write_text('{"schema_version":2}\n', encoding="utf-8")

    assert migrate(tmp_path).ready

    with _connect(telemetry_path) as connection:
        metric_names = {
            str(row[0])
            for row in connection.execute("SELECT metric_name FROM domain_telemetry_counter_totals")
        }
        snapshot_count = int(
            connection.execute("SELECT COUNT(*) FROM domain_telemetry_snapshots").fetchone()[0]
        )
    assert metric_names == {"ainrf_domain_idempotency_requests_total"}
    assert snapshot_count == 0
    assert not anchor_path.exists()

    with _connect(telemetry_path) as connection:
        connection.execute(
            "INSERT INTO domain_telemetry_counter_totals VALUES (?, ?, ?, ?)",
            (
                "ainrf_domain_legacy_write_attempts_total",
                '{"source":"legacy_json"}',
                1,
                "2026-08-05T00:00:00+00:00",
            ),
        )
        connection.commit()
    report = verify(tmp_path)
    assert not report.ready
    assert "retired telemetry counter remains" in report.blockers


def test_retirement_preflight_blocks_active_runtime(tmp_path: Path) -> None:
    _make_retiring_state(tmp_path, active_runtime=True)
    report = preflight(tmp_path)
    assert not report.ready
    assert "legacy runtime sessions are still active" in report.blockers[0]

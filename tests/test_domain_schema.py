"""Domain v2 additive schema and database-constraint tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect, run_pending
from ainrf.db.migration import registry
from ainrf.db.migrations.agentic_researcher import migration_012_harden_domain_control_plane

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _domain_db(tmp_path: Path) -> sqlite3.Connection:
    database = connect(tmp_path / "domain.sqlite3")
    run_pending(database, "agentic_researcher")
    return database


def _column_definitions(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {str(row["name"]): row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _seed_task(conn: sqlite3.Connection, task_id: str = "task-1") -> None:
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
        ) VALUES (?, 'project-legacy', 'workspace-legacy', 'environment-legacy', 'general',
            'claude_code', 'queued', 'Schema task', 'test',
            '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00', 'user-1')
        """,
        (task_id,),
    )


def test_domain_schema_has_core_control_tables(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "projects",
        "environments",
        "workspaces",
        "project_workspace_links",
        "domain_cutover_state",
    } <= tables


def test_domain_schema_enforces_one_active_primary(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        conn.execute(
            "INSERT INTO projects VALUES ('p', 'u', 'P', NULL, 'active', 0, NULL, NULL, 't', 't')"
        )
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, credential_ref, is_seed, status, created_at, updated_at
            ) VALUES ('e', 'env', NULL, 'Env', NULL, '{}', NULL, 0, 'active', 't', 't')
            """
        )
        for workspace_id in ("w1", "w2"):
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, owner_user_id, environment_id, canonical_path, label,
                    description, context_metadata_json, status, legacy_project_id, created_at, updated_at
                ) VALUES (?, 'u', 'e', ?, ?, NULL, '{}', 'active', NULL, 't', 't')
                """,
                (workspace_id, f"/tmp/{workspace_id}", workspace_id),
            )
        conn.execute(
            "INSERT INTO project_workspace_links VALUES ('p', 'w1', 'active', 1, 'u', 't', 't')"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO project_workspace_links VALUES ('p', 'w2', 'active', 1, 'u', 't', 't')"
            )


def test_final_task_reference_guard_requires_an_active_project_workspace_link(
    tmp_path: Path,
) -> None:
    """The final v2 equivalent FK guard rejects cross-Project Task writes."""

    with closing(_domain_db(tmp_path)) as conn:
        conn.execute("UPDATE domain_cutover_state SET constraints_ready = 1 WHERE singleton = 1")
        for project_id in ("project-linked", "project-unlinked"):
            conn.execute(
                """
                INSERT INTO projects (
                    project_id, owner_user_id, name, status, is_default, created_at, updated_at
                ) VALUES (?, 'user-1', ?, 'active', 0, 't', 't')
                """,
                (project_id, project_id),
            )
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, credential_ref, is_seed, status, created_at, updated_at
            ) VALUES ('environment-1', 'guard-env', 'user-1', 'Guard environment', NULL,
                '{}', NULL, 0, 'active', 't', 't')
            """
        )
        conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                description, context_metadata_json, status, legacy_project_id, created_at, updated_at
            ) VALUES ('workspace-1', 'user-1', 'environment-1', '/tmp/task-guard', 'Guard',
                NULL, '{}', 'active', NULL, 't', 't')
            """
        )
        conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-linked', 'workspace-1', 'active', 1, 'user-1', 't', 't')
            """
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('task-linked', 'project-linked', 'workspace-1', 'environment-1',
                'general', 'claude_code', 'queued', 'Linked task', 'test', 't', 't', 'user-1')
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="active workspace link"):
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, workspace_id, environment_id, researcher_type,
                    harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
                ) VALUES ('task-cross-project', 'project-unlinked', 'workspace-1', 'environment-1',
                    'general', 'claude_code', 'queued', 'Cross project task', 'test', 't', 't',
                    'user-1')
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="active workspace link"):
            conn.execute(
                "UPDATE tasks SET project_id = 'project-unlinked' WHERE task_id = 'task-linked'"
            )


def test_migration_012_upgrades_idempotency_to_actor_scoped_keys(tmp_path: Path) -> None:
    """Existing idempotency records survive the actor-scoped primary-key rebuild."""
    with closing(connect(tmp_path / "domain.sqlite3")) as conn:
        for migration in registry.get_pending("agentic_researcher", 0)[:11]:
            migration(conn)
        conn.execute(
            """
            INSERT INTO domain_idempotency_requests (
                scope, idempotency_key, request_hash, response_json, created_at
            ) VALUES ('task.create', 'legacy-key', 'legacy-hash', '{}', '2026-07-12T00:00:00+00:00')
            """
        )
        migration_012_harden_domain_control_plane(conn)

        columns = _column_definitions(conn, "domain_idempotency_requests")
        assert {"actor_user_id", "scope", "idempotency_key", "request_hash"} <= columns.keys()
        assert columns["actor_user_id"]["notnull"] == 1
        assert columns["request_hash"]["notnull"] == 1
        primary_key_columns = [
            str(row["name"])
            for row in sorted(columns.values(), key=lambda row: int(row["pk"]))
            if row["pk"]
        ]
        assert primary_key_columns == ["actor_user_id", "scope", "idempotency_key"]
        legacy = conn.execute(
            "SELECT actor_user_id, request_hash FROM domain_idempotency_requests "
            "WHERE scope = 'task.create' AND idempotency_key = 'legacy-key'"
        ).fetchone()
        assert legacy is not None
        assert tuple(legacy) == ("", "legacy-hash")

        for actor_user_id in ("user-a", "user-b"):
            conn.execute(
                """
                INSERT INTO domain_idempotency_requests (
                    actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
                ) VALUES (?, 'task.create', 'shared-key', 'request-hash', '{}', '2026-07-12T00:00:00+00:00')
                """,
                (actor_user_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_idempotency_requests (
                    actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
                ) VALUES ('user-a', 'task.create', 'shared-key', 'different-hash', '{}',
                    '2026-07-12T00:00:00+00:00')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO domain_idempotency_requests (
                    actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
                ) VALUES ('user-c', 'task.create', 'missing-hash', NULL, '{}',
                    '2026-07-12T00:00:00+00:00')
                """
            )


def test_migration_012_adds_attempt_runtime_and_outbox_recovery_metadata(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        attempt_columns = _column_definitions(conn, "agent_task_attempts")
        runtime_columns = _column_definitions(conn, "agent_runtime_sessions")
        outbox_columns = _column_definitions(conn, "task_dispatch_outbox")

        assert {
            "message_start_seq",
            "message_end_seq",
            "output_start_seq",
            "output_end_seq",
            "artifact_refs_json",
            "code_refs_json",
            "data_refs_json",
            "token_usage_json",
            "cost_usd",
            "failure_reason",
            "stop_reason",
        } <= attempt_columns.keys()
        assert {
            "engine_name",
            "engine_session_key",
            "runtime_metadata_json",
            "started_at",
            "finished_at",
            "last_probe_at",
            "adopted_at",
            "failure_reason",
        } <= runtime_columns.keys()
        assert {
            "claimed_at",
            "claim_heartbeat_at",
            "launch_state",
            "dispatch_attempt_count",
            "last_error",
            "next_attempt_at",
            "updated_at",
        } <= outbox_columns.keys()
        assert attempt_columns["artifact_refs_json"]["notnull"] == 1
        assert runtime_columns["runtime_metadata_json"]["notnull"] == 1
        assert outbox_columns["launch_state"]["notnull"] == 1

        _seed_task(conn)
        conn.execute(
            """
            INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
            ) VALUES ('attempt-1', 'task-1', 1, 'initial', 'queued', NULL,
                '2026-07-12T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO task_dispatch_outbox (
                dispatch_id, task_id, attempt_id, status, created_at
            ) VALUES ('dispatch-1', 'task-1', 'attempt-1', 'pending', '2026-07-12T00:00:00+00:00')
            """
        )
        dispatch = conn.execute(
            "SELECT launch_state, dispatch_attempt_count FROM task_dispatch_outbox "
            "WHERE dispatch_id = 'dispatch-1'"
        ).fetchone()
        assert dispatch is not None
        assert tuple(dispatch) == ("none", 0)
        with pytest.raises(sqlite3.IntegrityError, match="invalid dispatch launch state"):
            conn.execute(
                "UPDATE task_dispatch_outbox SET launch_state = 'restart-anyway' "
                "WHERE dispatch_id = 'dispatch-1'"
            )


def test_domain_cutover_state_requires_prepare_and_cannot_rollback_v2(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        state = conn.execute(
            "SELECT state FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
        assert state is not None
        assert state["state"] == "legacy"

        with pytest.raises(sqlite3.IntegrityError, match="invalid domain cutover state transition"):
            conn.execute("UPDATE domain_cutover_state SET state = 'v2' WHERE singleton = 1")

        with pytest.raises(sqlite3.IntegrityError, match="invalid domain cutover state transition"):
            conn.execute("UPDATE domain_cutover_state SET state = 'prepared' WHERE singleton = 1")


def test_domain_control_plane_uses_unique_and_restrict_constraints(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        _seed_task(conn)
        conn.execute(
            """
            INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
            ) VALUES ('attempt-1', 'task-1', 1, 'initial', 'queued', NULL,
                '2026-07-12T00:00:00+00:00')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
                ) VALUES ('attempt-duplicate', 'task-1', 1, 'retry', 'queued', NULL,
                    '2026-07-12T00:00:00+00:00')
                """
            )
        conn.execute(
            """
            INSERT INTO agent_runtime_sessions (
                runtime_session_id, attempt_id, launch_key, status, created_at
            ) VALUES ('runtime-1', 'attempt-1', 'launch-1', 'starting',
                '2026-07-12T00:00:00+00:00')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO agent_runtime_sessions (
                    runtime_session_id, attempt_id, launch_key, status, created_at
                ) VALUES ('runtime-2', 'attempt-1', 'launch-2', 'running',
                    '2026-07-12T00:00:00+00:00')
                """
            )
        conn.execute(
            """
            INSERT INTO task_dispatch_outbox (
                dispatch_id, task_id, attempt_id, status, created_at
            ) VALUES ('dispatch-1', 'task-1', 'attempt-1', 'pending', '2026-07-12T00:00:00+00:00')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO task_dispatch_outbox (
                    dispatch_id, task_id, attempt_id, status, created_at
                ) VALUES ('dispatch-duplicate', 'task-1', 'attempt-1', 'claimed',
                    '2026-07-12T00:00:00+00:00')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM tasks WHERE task_id = 'task-1'")

        runtime_foreign_keys = {
            str(row["from"]): str(row["on_delete"])
            for row in conn.execute("PRAGMA foreign_key_list(agent_runtime_sessions)").fetchall()
        }
        outbox_foreign_keys = {
            str(row["from"]): str(row["on_delete"])
            for row in conn.execute("PRAGMA foreign_key_list(task_dispatch_outbox)").fetchall()
        }
        assert runtime_foreign_keys["attempt_id"] == "RESTRICT"
        assert outbox_foreign_keys == {"attempt_id": "RESTRICT", "task_id": "RESTRICT"}


def test_migration_017_persists_attempt_control_requests_and_guards_archived_parents(
    tmp_path: Path,
) -> None:
    now = "2026-07-12T00:00:00+00:00"
    with closing(_domain_db(tmp_path)) as conn:
        columns = _column_definitions(conn, "task_attempt_control_requests")
        assert {
            "control_request_id",
            "task_id",
            "attempt_id",
            "action",
            "status",
            "actor_user_id",
            "idempotency_key",
            "request_hash",
            "reason",
            "payload_json",
            "created_at",
            "updated_at",
            "acknowledged_at",
            "completed_at",
            "failure_reason",
        } <= columns.keys()
        assert columns["attempt_id"]["notnull"] == 1
        assert columns["payload_json"]["notnull"] == 1

        conn.execute(
            "INSERT INTO projects VALUES ('project-1', 'user-1', 'Project', NULL, "
            "'active', 0, NULL, NULL, ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('task-1', 'project-1', 'workspace-legacy', 'environment-legacy', 'general',
                'claude_code', 'queued', 'Schema task', 'test', ?, ?, 'user-1')
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
            ) VALUES ('attempt-1', 'task-1', 1, 'initial', 'queued', NULL, ?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO task_dispatch_outbox (
                dispatch_id, task_id, attempt_id, status, created_at
            ) VALUES ('dispatch-1', 'task-1', 'attempt-1', 'pending', ?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO task_attempt_control_requests (
                control_request_id, task_id, attempt_id, action, status, actor_user_id,
                idempotency_key, request_hash, reason, payload_json, created_at, updated_at
            ) VALUES ('control-1', 'task-1', 'attempt-1', 'pause', 'requested', 'user-1',
                'pause-key', 'request-hash', 'user requested pause', '{}', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            UPDATE task_attempt_control_requests
            SET status = 'acknowledged', acknowledged_at = ?, updated_at = ?
            WHERE control_request_id = 'control-1'
            """,
            (now, now),
        )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            conn.execute(
                "UPDATE task_attempt_control_requests SET action = 'stop' "
                "WHERE control_request_id = 'control-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM task_attempt_control_requests WHERE control_request_id = 'control-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="must match its Task"):
            conn.execute(
                """
                INSERT INTO task_attempt_control_requests (
                    control_request_id, task_id, attempt_id, action, status, actor_user_id,
                    payload_json, created_at, updated_at
                ) VALUES ('control-wrong-task', 'task-1', 'missing-attempt', 'pause',
                    'requested', 'user-1', '{}', ?, ?)
                """,
                (now, now),
            )

        conn.execute(
            "UPDATE projects SET status = 'archived', archived_at = ? WHERE project_id = 'project-1'",
            (now,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="cannot create an Attempt"):
            conn.execute(
                """
                INSERT INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
                ) VALUES ('attempt-2', 'task-1', 2, 'retry', 'queued', NULL, ?)
                """,
                (now,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot create a dispatch"):
            conn.execute(
                """
                INSERT INTO task_dispatch_outbox (
                    dispatch_id, task_id, attempt_id, status, created_at
                ) VALUES ('dispatch-2', 'task-1', 'attempt-1', 'cancelled', ?)
                """,
                (now,),
            )

        conn.execute(
            "UPDATE task_dispatch_outbox SET status = 'cancelled' WHERE dispatch_id = 'dispatch-1'"
        )
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'cancelled' WHERE attempt_id = 'attempt-1'"
        )

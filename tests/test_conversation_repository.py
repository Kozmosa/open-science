"""Focused persistence tests for canonical conversation records."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_execution_repository import (
    SqliteConversationExecutionRepository,
)
from ainrf.domain.conversation_repository import SqliteConversationRepository

pytestmark = [pytest.mark.unit, pytest.mark.db_race]

_NOW = "2026-07-18T00:00:00+00:00"


def _database(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "conversation.sqlite3")
    run_pending(conn, "agentic_researcher")
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, title, prompt, created_at, updated_at, owner_user_id
        ) VALUES ('task-1', 'project-legacy', 'workspace-legacy', 'environment-legacy',
            'general', 'codex-app-server', 'Conversation', 'test', ?, ?, 'user-1')
        """,
        (_NOW, _NOW),
    )
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, title, prompt, created_at, updated_at, owner_user_id
        ) VALUES ('task-2', 'project-legacy', 'workspace-legacy', 'environment-legacy',
            'general', 'codex-app-server', 'Other', 'test', ?, ?, 'user-1')
        """,
        (_NOW, _NOW),
    )
    repository = SqliteConversationRepository(conn)
    repository.insert_task_authority(task_id="task-1", created_at=_NOW)
    repository.insert_task_authority(task_id="task-2", created_at=_NOW)
    return conn


def _insert_binding(
    repository: SqliteConversationRepository,
    *,
    binding_id: str = "binding-1",
    task_id: str = "task-1",
    native_ref: str = "thread-1",
) -> None:
    repository.insert_binding(
        binding_id=binding_id,
        task_id=task_id,
        binding_seq=repository.next_binding_seq(task_id),
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref=native_ref,
        contract_version=1,
        provider_profile_ref="profile-1",
        provider_profile_version="1",
        provider_profile_fingerprint="fingerprint-1",
        provenance_json='{"source":"driver_receipt"}',
        validation_evidence_json='{"confidence":"proven"}',
        created_at=_NOW,
        validated_at=_NOW,
    )


def _insert_turn(
    repository: SqliteConversationRepository,
    *,
    turn_id: str = "turn-1",
    task_id: str = "task-1",
    binding_id: str = "binding-1",
    retry_of_turn_id: str | None = None,
    native_ref: str = "native-turn-1",
) -> None:
    repository.insert_turn(
        turn_id=turn_id,
        task_id=task_id,
        turn_seq=repository.next_turn_seq(task_id),
        status="in_progress",
        retry_of_turn_id=retry_of_turn_id,
        context_snapshot_ref=None,
        binding_id=binding_id,
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        provider_profile_ref="profile-1",
        provider_profile_version="1",
        provider_profile_fingerprint="fingerprint-1",
        model="gpt-5.5",
        native_turn_kind="turn",
        native_turn_ref=native_ref,
        accepted_at=_NOW,
        started_at=_NOW,
        updated_at=_NOW,
    )


def _insert_item(
    repository: SqliteConversationRepository,
    *,
    item_id: str,
    turn_id: str,
    item_type: str,
    actor: str,
    payload: str,
    native_item_id: str,
    parent_item_id: str | None = None,
    call_item_id: str | None = None,
) -> None:
    repository.insert_turn_item(
        item_id=item_id,
        task_id="task-1",
        turn_id=turn_id,
        task_item_seq=repository.next_task_item_seq("task-1"),
        turn_item_seq=repository.next_turn_item_seq(turn_id),
        envelope_type="conversation.item",
        envelope_version=1,
        item_type=item_type,
        actor=actor,
        payload_json=payload,
        native_provenance_json='{"binding_id":"binding-1"}',
        native_dedupe_scope="binding-1",
        native_item_id=native_item_id,
        parent_item_id=parent_item_id,
        call_item_id=call_item_id,
        occurred_at=_NOW,
        ingested_at=_NOW,
        persisted_at=_NOW,
    )


def test_repository_orders_turns_and_items_without_committing(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        _insert_binding(repository)
        _insert_turn(repository)
        _insert_item(
            repository,
            item_id="item-user",
            turn_id="turn-1",
            item_type="user_message",
            actor="user",
            payload='{"text":"hello"}',
            native_item_id="native-item-1",
        )
        assert conn.in_transaction
        binding = repository.active_binding("task-1")
        turn = repository.active_turn("task-1")
        assert binding is not None and binding["binding_id"] == "binding-1"
        assert turn is not None and turn["turn_id"] == "turn-1"
        assert repository.next_turn_seq("task-1") == 2
        assert repository.next_task_item_seq("task-1") == 2
        assert repository.next_turn_item_seq("turn-1") == 2

        assert (
            repository.finish_turn(
                turn_id="turn-1",
                status="completed",
                finished_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="terminal Task Turns"):
            conn.execute("UPDATE task_turns SET updated_at = 'later' WHERE turn_id = 'turn-1'")
        _insert_turn(
            repository,
            turn_id="turn-2",
            retry_of_turn_id="turn-1",
            native_ref="native-turn-2",
        )
        _insert_item(
            repository,
            item_id="item-retry",
            turn_id="turn-2",
            item_type="user_message",
            actor="user",
            payload='{"text":"retry"}',
            native_item_id="native-item-2",
            parent_item_id="item-user",
        )

        assert [row["turn_id"] for row in repository.list_turns("task-1")] == [
            "turn-1",
            "turn-2",
        ]
        assert [row["item_id"] for row in repository.list_task_items("task-1")] == [
            "item-user",
            "item-retry",
        ]


def test_database_rejects_second_active_turn_and_cross_task_retry(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        _insert_binding(repository)
        _insert_turn(repository)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_turn(repository, turn_id="turn-duplicate", native_ref="native-turn-2")

        assert (
            repository.finish_turn(
                turn_id="turn-1",
                status="failed",
                finished_at=_NOW,
                updated_at=_NOW,
                failure_code="runtime_lost",
            )
            == 1
        )
        _insert_binding(
            repository,
            binding_id="binding-2",
            task_id="task-2",
            native_ref="thread-2",
        )
        with pytest.raises(sqlite3.IntegrityError, match="same Task"):
            _insert_turn(
                repository,
                turn_id="turn-cross-task",
                task_id="task-2",
                binding_id="binding-2",
                retry_of_turn_id="turn-1",
                native_ref="native-turn-3",
            )


def test_binding_lineage_is_append_only_and_superseded_one_way(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        _insert_binding(repository)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_binding(
                repository,
                binding_id="binding-duplicate-active",
                native_ref="thread-other",
            )

        assert (
            repository.supersede_binding(
                binding_id="binding-1",
                superseded_at=_NOW,
                validation_evidence_json='{"reason":"native_fork"}',
            )
            == 1
        )
        _insert_binding(repository, binding_id="binding-2", native_ref="thread-2")
        active = repository.active_binding("task-1")
        assert active is not None and active["binding_id"] == "binding-2"

        with pytest.raises(sqlite3.IntegrityError, match="invalid engine"):
            conn.execute(
                "UPDATE engine_conversation_bindings SET status = 'active', superseded_at = NULL "
                "WHERE binding_id = 'binding-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            conn.execute(
                "UPDATE engine_conversation_bindings SET native_conversation_ref = 'repointed' "
                "WHERE binding_id = 'binding-2'"
            )


def test_turn_items_are_append_only_causal_and_provider_scoped(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        _insert_binding(repository)
        _insert_turn(repository)
        with pytest.raises(sqlite3.IntegrityError, match="requires its tool call"):
            _insert_item(
                repository,
                item_id="orphan-tool-result",
                turn_id="turn-1",
                item_type="tool_result",
                actor="tool",
                payload='{"result":"orphan"}',
                native_item_id="native-orphan-result",
            )
        _insert_item(
            repository,
            item_id="tool-call",
            turn_id="turn-1",
            item_type="tool_call",
            actor="agent",
            payload='{"tool":"search"}',
            native_item_id="native-call",
        )
        _insert_item(
            repository,
            item_id="tool-result",
            turn_id="turn-1",
            item_type="tool_result",
            actor="tool",
            payload='{"result":"ok"}',
            native_item_id="native-result",
            call_item_id="tool-call",
        )

        with pytest.raises(sqlite3.IntegrityError):
            _insert_item(
                repository,
                item_id="duplicate-native",
                turn_id="turn-1",
                item_type="system_notice",
                actor="system",
                payload='{"notice":"duplicate"}',
                native_item_id="native-result",
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE turn_items SET payload_json = '{\"changed\":true}' "
                "WHERE item_id = 'tool-result'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            repository.insert_turn_item(
                item_id="bad-payload",
                task_id="task-1",
                turn_id="turn-1",
                task_item_seq=3,
                turn_item_seq=3,
                envelope_type="conversation.item",
                envelope_version=1,
                item_type="agent_message",
                actor="agent",
                payload_json="not-json",
                native_provenance_json="{}",
                native_dedupe_scope=None,
                native_item_id=None,
                parent_item_id=None,
                call_item_id=None,
                occurred_at=None,
                ingested_at=_NOW,
                persisted_at=_NOW,
            )


def test_task_without_current_authority_rejects_conversation_writes(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('task-legacy', 'project-legacy', 'workspace-legacy',
                'environment-legacy', 'general', 'codex_app_server',
                'Legacy', 'test', ?, ?, 'user-1')
            """,
            (_NOW, _NOW),
        )
        with pytest.raises(sqlite3.IntegrityError, match="conversation_v3 authority"):
            _insert_binding(repository, task_id="task-legacy", binding_id="legacy-binding")


def test_task_state_requires_current_authority_and_guards_transitions(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationRepository(conn)
        repository.insert_task_state(task_id="task-1", created_at=_NOW)
        state = repository.task_state("task-1")
        assert state is not None
        assert (state["work_status"], state["revision"]) == ("open", 1)

        assert (
            repository.update_work_status(
                task_id="task-1",
                expected_status="open",
                status="completed",
                updated_at=_NOW,
            )
            == 1
        )
        assert (
            repository.update_work_status(
                task_id="task-1",
                expected_status="completed",
                status="open",
                updated_at=_NOW,
            )
            == 1
        )
        state = repository.task_state("task-1")
        assert state is not None and state["revision"] == 3

        with pytest.raises(sqlite3.IntegrityError, match="invalid conversation Task"):
            conn.execute(
                "UPDATE conversation_task_states "
                "SET work_status = 'open', revision = revision + 1 "
                "WHERE task_id = 'task-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="advance exactly once"):
            conn.execute(
                "UPDATE conversation_task_states SET updated_at = 'later' WHERE task_id = 'task-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            conn.execute(
                "UPDATE conversation_task_states "
                "SET created_at = 'later', revision = revision + 1 "
                "WHERE task_id = 'task-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM conversation_task_states WHERE task_id = 'task-1'")

        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('task-legacy-state', 'project-legacy', 'workspace-legacy',
                'environment-legacy', 'general', 'codex-app-server',
                'Legacy state', 'test', ?, ?, 'user-1')
            """,
            (_NOW, _NOW),
        )
        with pytest.raises(sqlite3.IntegrityError, match="conversation_v3 authority"):
            repository.insert_task_state(task_id="task-legacy-state", created_at=_NOW)


def test_submission_intent_and_next_turn_guards_are_durable(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        conversations = SqliteConversationRepository(conn)
        executions = SqliteConversationExecutionRepository(conn)
        _insert_binding(conversations)
        _insert_turn(conversations)

        def insert_submission(submission_id: str, reserved_turn_id: str) -> None:
            executions.insert_submission(
                submission_id=submission_id,
                task_id="task-1",
                reserved_turn_id=reserved_turn_id,
                actor_user_id="user-1",
                idempotency_key=submission_id,
                request_hash=f"hash-{submission_id}",
                input_json='{"text":"next"}',
                context_snapshot_ref=None,
                created_at=_NOW,
                updated_at=_NOW,
            )

        insert_submission("submission-next", "turn-next")
        executions.insert_submission_intent(
            submission_id="submission-next",
            task_id="task-1",
            kind="next_turn",
            retry_of_turn_id=None,
            created_at=_NOW,
        )
        executions.insert_next_turn(
            submission_id="submission-next",
            task_id="task-1",
            blocking_turn_id="turn-1",
            created_at=_NOW,
        )
        with pytest.raises(sqlite3.IntegrityError, match="intents are immutable"):
            conn.execute(
                "UPDATE conversation_submission_intents SET kind = 'create' "
                "WHERE submission_id = 'submission-next'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="intents are append-only"):
            conn.execute(
                "DELETE FROM conversation_submission_intents "
                "WHERE submission_id = 'submission-next'"
            )

        insert_submission("submission-second", "turn-second")
        executions.insert_submission_intent(
            submission_id="submission-second",
            task_id="task-1",
            kind="create",
            retry_of_turn_id=None,
            created_at=_NOW,
        )
        with pytest.raises(sqlite3.IntegrityError, match="active blocking Turn"):
            executions.insert_next_turn(
                submission_id="submission-second",
                task_id="task-1",
                blocking_turn_id="turn-1",
                created_at=_NOW,
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be claimed"):
            executions.transition_submission(
                submission_id="submission-next",
                expected_status="queued",
                status="claimed",
                claimed_at=_NOW,
                updated_at=_NOW,
            )
        with pytest.raises(sqlite3.IntegrityError, match="blocker is still active"):
            executions.promote_next_turn(
                submission_id="submission-next", promoted_at=_NOW, updated_at=_NOW
            )

        assert (
            conversations.finish_turn(
                turn_id="turn-1",
                status="completed",
                finished_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        assert (
            executions.promote_next_turn(
                submission_id="submission-next", promoted_at=_NOW, updated_at=_NOW
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="invalid next-Turn"):
            conn.execute(
                "UPDATE next_turn_submissions SET status = 'waiting', promoted_at = NULL "
                "WHERE submission_id = 'submission-next'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            conn.execute(
                "UPDATE next_turn_submissions SET blocking_turn_id = 'turn-next' "
                "WHERE submission_id = 'submission-next'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM next_turn_submissions WHERE submission_id = 'submission-next'"
            )


def test_retry_intent_requires_same_task_turn_lineage(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        conversations = SqliteConversationRepository(conn)
        executions = SqliteConversationExecutionRepository(conn)
        _insert_binding(conversations)
        _insert_turn(conversations)
        executions.insert_submission(
            submission_id="submission-retry",
            task_id="task-1",
            reserved_turn_id="turn-retry",
            actor_user_id="user-1",
            idempotency_key="retry",
            request_hash="retry-hash",
            input_json='{"text":"retry"}',
            context_snapshot_ref=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        with pytest.raises(sqlite3.IntegrityError):
            executions.insert_submission_intent(
                submission_id="submission-retry",
                task_id="task-1",
                kind="retry",
                retry_of_turn_id=None,
                created_at=_NOW,
            )
        executions.insert_submission_intent(
            submission_id="submission-retry",
            task_id="task-1",
            kind="retry",
            retry_of_turn_id="turn-1",
            created_at=_NOW,
        )


def test_queued_submission_context_can_be_rebound_but_started_context_cannot(
    tmp_path: Path,
) -> None:
    with closing(_database(tmp_path)) as conn:
        conversations = SqliteConversationRepository(conn)
        executions = SqliteConversationExecutionRepository(conn)
        _insert_binding(conversations)
        _insert_turn(conversations)
        executions.insert_submission(
            submission_id="submission-context",
            task_id="task-1",
            reserved_turn_id="turn-context",
            actor_user_id="user-1",
            idempotency_key="context",
            request_hash="context-hash",
            input_json='{"text":"hello"}',
            context_snapshot_ref="snapshot-old",
            created_at=_NOW,
            updated_at=_NOW,
        )
        conn.execute(
            "UPDATE turn_submissions SET context_snapshot_ref = ?, updated_at = ? "
            "WHERE submission_id = ?",
            ("snapshot-new", _NOW, "submission-context"),
        )
        assert (
            conn.execute(
                "SELECT context_snapshot_ref FROM turn_submissions WHERE submission_id = ?",
                ("submission-context",),
            ).fetchone()[0]
            == "snapshot-new"
        )
        conn.execute(
            "UPDATE turn_submissions SET status = 'claimed', claimed_at = ?, updated_at = ? "
            "WHERE submission_id = ?",
            (_NOW, _NOW, "submission-context"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="started Turn Submission context"):
            conn.execute(
                "UPDATE turn_submissions SET context_snapshot_ref = ? WHERE submission_id = ?",
                ("snapshot-too-late", "submission-context"),
            )


def test_fresh_current_conversation_stores_start_empty(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("task_turns", "turn_items", "engine_conversation_bindings")
        }
    assert counts == {
        "task_turns": 0,
        "turn_items": 0,
        "engine_conversation_bindings": 0,
    }

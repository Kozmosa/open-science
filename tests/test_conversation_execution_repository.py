"""Focused persistence tests for conversation execution records."""

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
_LATER = "2026-07-18T00:01:00+00:00"
_EXPIRY = "2026-07-18T01:00:00+00:00"


def _database(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "execution.sqlite3")
    run_pending(conn, "agentic_researcher")
    for task_id in ("task-1", "task-2"):
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (?, 'project-legacy', 'workspace-legacy', 'environment-legacy',
                'general', 'codex_app_server', 'Conversation', 'test', ?, ?, 'user-1')
            """,
            (task_id, _NOW, _NOW),
        )
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, project_id, workspace_id, environment_id, researcher_type,
            harness_engine, title, prompt, created_at, updated_at, owner_user_id
        ) VALUES ('task-legacy', 'project-legacy', 'workspace-legacy', 'environment-legacy',
            'general', 'codex_app_server', 'Legacy', 'test', ?, ?, 'user-1')
        """,
        (_NOW, _NOW),
    )
    conversation_repository = SqliteConversationRepository(conn)
    conversation_repository.insert_task_authority(task_id="task-1", created_at=_NOW)
    conversation_repository.insert_task_authority(task_id="task-2", created_at=_NOW)
    return conn


def _accepted_turn(conn: sqlite3.Connection) -> None:
    repository = SqliteConversationRepository(conn)
    repository.insert_binding(
        binding_id="binding-1",
        task_id="task-1",
        binding_seq=1,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-1",
        contract_version=1,
        provider_profile_ref="profile-1",
        provider_profile_version="1",
        provider_profile_fingerprint="fingerprint-1",
        provenance_json='{"source":"receipt"}',
        validation_evidence_json='{"confidence":"proven"}',
        created_at=_NOW,
        validated_at=_NOW,
    )
    repository.insert_turn(
        turn_id="turn-1",
        task_id="task-1",
        turn_seq=1,
        status="in_progress",
        retry_of_turn_id=None,
        context_snapshot_ref=None,
        binding_id="binding-1",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        provider_profile_ref="profile-1",
        provider_profile_version="1",
        provider_profile_fingerprint="fingerprint-1",
        model="gpt-5.5",
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        accepted_at=_NOW,
        started_at=_NOW,
        updated_at=_NOW,
    )


def _runtime(repository: SqliteConversationExecutionRepository) -> None:
    repository.insert_runtime_execution(
        runtime_execution_id="execution-1",
        task_id="task-1",
        turn_id="turn-1",
        execution_seq=repository.next_execution_seq("turn-1"),
        runtime_generation=repository.next_runtime_generation("turn-1"),
        binding_id="binding-1",
        native_runtime_kind="process",
        native_runtime_ref="runtime-1",
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        evidence_json='{"source":"driver"}',
        created_at=_NOW,
        started_at=_NOW,
        updated_at=_NOW,
    )


def test_submission_is_pre_acceptance_authority_not_canonical_history(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        repository.insert_submission(
            submission_id="submission-1",
            task_id="task-1",
            reserved_turn_id="turn-1",
            actor_user_id="user-1",
            idempotency_key="create-1",
            request_hash="hash-1",
            input_json='{"text":"hello"}',
            context_snapshot_ref="snapshot-1",
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 0
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="queued",
                status="claimed",
                claimed_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="claimed",
                status="delivering",
                claimed_at=_NOW,
                delivering_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="accepted Turn"):
            conn.execute(
                """
                UPDATE turn_submissions SET status = 'delivered', accepted_at = ?,
                    finished_at = ?, native_turn_kind = 'turn',
                    native_turn_ref = 'native-turn-1', updated_at = ?
                WHERE submission_id = 'submission-1'
                """,
                (_NOW, _NOW, _NOW),
            )

        _accepted_turn(conn)
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="delivering",
                status="delivered",
                accepted_at=_NOW,
                finished_at=_NOW,
                native_turn_kind="turn",
                native_turn_ref="native-turn-1",
                delivery_evidence_json='{"accepted":true}',
                updated_at=_NOW,
            )
            == 1
        )


def test_delivery_unknown_converges_without_replay_or_failed_turn(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        repository.insert_submission(
            submission_id="submission-1",
            task_id="task-1",
            reserved_turn_id="turn-reserved",
            actor_user_id="user-1",
            idempotency_key="create-1",
            request_hash="hash-1",
            input_json='{"text":"hello"}',
            context_snapshot_ref=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        repository.transition_submission(
            submission_id="submission-1",
            expected_status="queued",
            status="claimed",
            claimed_at=_NOW,
            updated_at=_NOW,
        )
        repository.transition_submission(
            submission_id="submission-1",
            expected_status="claimed",
            status="delivering",
            claimed_at=_NOW,
            delivering_at=_NOW,
            updated_at=_NOW,
        )
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="delivering",
                status="delivery_unknown",
                failure_code="acceptance_unknown",
                delivery_evidence_json='{"probe":"required"}',
                updated_at=_LATER,
            )
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 0
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="delivery_unknown",
                status="failed_delivery",
                finished_at=_LATER,
                failure_code="proven_not_accepted",
                delivery_evidence_json='{"accepted":false}',
                updated_at=_LATER,
            )
            == 1
        )
        submission = repository.submission_by_id("submission-1")
        assert submission is not None
        assert submission["claimed_at"] == _NOW
        assert submission["delivering_at"] == _NOW
        assert submission["finished_at"] == _LATER
        assert submission["delivery_evidence_json"] == '{"accepted":false}'
        assert submission["failure_code"] == "proven_not_accepted"
        with pytest.raises(sqlite3.IntegrityError, match="terminal Turn Submissions"):
            conn.execute(
                "UPDATE turn_submissions SET updated_at = 'later' "
                "WHERE submission_id = 'submission-1'"
            )


def test_delivery_unknown_reconciliation_clears_failure_code(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        repository.insert_submission(
            submission_id="submission-1",
            task_id="task-1",
            reserved_turn_id="turn-1",
            actor_user_id="user-1",
            idempotency_key="create-1",
            request_hash="hash-1",
            input_json='{"text":"hello"}',
            context_snapshot_ref=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        repository.transition_submission(
            submission_id="submission-1",
            expected_status="queued",
            status="claimed",
            claimed_at=_NOW,
            updated_at=_NOW,
        )
        repository.transition_submission(
            submission_id="submission-1",
            expected_status="claimed",
            status="delivering",
            delivering_at=_NOW,
            updated_at=_NOW,
        )
        repository.transition_submission(
            submission_id="submission-1",
            expected_status="delivering",
            status="delivery_unknown",
            failure_code="acceptance_unknown",
            delivery_evidence_json='{"probe":"required"}',
            updated_at=_LATER,
        )
        _accepted_turn(conn)
        assert (
            repository.transition_submission(
                submission_id="submission-1",
                expected_status="delivery_unknown",
                status="delivered",
                accepted_at=_LATER,
                native_turn_kind="turn",
                native_turn_ref="native-turn-1",
                delivery_evidence_json='{"accepted":true}',
                updated_at=_LATER,
            )
            == 1
        )
        submission = repository.submission_by_id("submission-1")
        assert submission is not None
        assert submission["status"] == "delivered"
        assert submission["failure_code"] is None
        assert submission["finished_at"] == _LATER


def test_runtime_lifecycle_generation_and_terminal_immutability(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        _accepted_turn(conn)
        repository = SqliteConversationExecutionRepository(conn)
        _runtime(repository)
        assert (
            repository.transition_runtime_execution(
                runtime_execution_id="execution-1",
                expected_status="starting",
                status="running",
                evidence_json='{"running":true}',
                updated_at=_LATER,
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError):
            _runtime(repository)
        assert (
            repository.transition_runtime_execution(
                runtime_execution_id="execution-1",
                expected_status="running",
                status="completed",
                evidence_json='{"terminal":true}',
                finished_at=_LATER,
                updated_at=_LATER,
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="terminal Runtime Executions"):
            conn.execute(
                "UPDATE runtime_executions SET updated_at = 'later' "
                "WHERE runtime_execution_id = 'execution-1'"
            )


def test_runtime_rejects_terminal_or_native_mismatched_turn_scope(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        _accepted_turn(conn)
        repository = SqliteConversationExecutionRepository(conn)
        with pytest.raises(sqlite3.IntegrityError, match="Turn scope is stale"):
            repository.insert_runtime_execution(
                runtime_execution_id="execution-missing-native-turn",
                task_id="task-1",
                turn_id="turn-1",
                execution_seq=1,
                runtime_generation=1,
                binding_id="binding-1",
                native_runtime_kind="process",
                native_runtime_ref="runtime-missing-native-turn",
                native_turn_kind=None,
                native_turn_ref=None,
                evidence_json="{}",
                created_at=_NOW,
                started_at=_NOW,
                updated_at=_NOW,
            )
        with pytest.raises(sqlite3.IntegrityError, match="Turn scope is stale"):
            repository.insert_runtime_execution(
                runtime_execution_id="execution-mismatch",
                task_id="task-1",
                turn_id="turn-1",
                execution_seq=1,
                runtime_generation=1,
                binding_id="binding-1",
                native_runtime_kind="process",
                native_runtime_ref="runtime-mismatch",
                native_turn_kind="turn",
                native_turn_ref="wrong-native-turn",
                evidence_json="{}",
                created_at=_NOW,
                started_at=_NOW,
                updated_at=_NOW,
            )
        conversation = SqliteConversationRepository(conn)
        assert (
            conversation.finish_turn(
                turn_id="turn-1", status="completed", finished_at=_LATER, updated_at=_LATER
            )
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="Turn scope is stale"):
            _runtime(repository)


def test_controls_enforce_expected_turn_and_distinguish_interrupt_evidence(
    tmp_path: Path,
) -> None:
    with closing(_database(tmp_path)) as conn:
        _accepted_turn(conn)
        repository = SqliteConversationExecutionRepository(conn)
        _runtime(repository)
        repository.insert_control_request(
            control_request_id="interrupt-1",
            task_id="task-1",
            expected_turn_id="turn-1",
            runtime_execution_id="execution-1",
            runtime_generation=1,
            kind="interrupt",
            actor_user_id="user-1",
            idempotency_key="interrupt-key",
            request_hash="interrupt-hash",
            payload_json='{"reason":"user"}',
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert (
            repository.transition_control_request(
                control_request_id="interrupt-1",
                expected_status="requested",
                status="accepted",
                evidence_json='{"rpc_ack":true}',
                accepted_at=_NOW,
                updated_at=_NOW,
            )
            == 1
        )
        row = conn.execute("SELECT status, completed_at FROM turn_control_requests").fetchone()
        assert row is not None and tuple(row) == ("accepted", None)
        assert (
            repository.complete_accepted_interrupts(
                runtime_execution_id="execution-1",
                completed_at=_LATER,
                updated_at=_LATER,
            )
            == 1
        )
        completed = conn.execute(
            "SELECT evidence_json, accepted_at, completed_at FROM turn_control_requests "
            "WHERE control_request_id = 'interrupt-1'"
        ).fetchone()
        assert completed is not None
        assert tuple(completed) == ('{"rpc_ack":true}', _NOW, _LATER)

        repository.insert_control_request(
            control_request_id="steer-1",
            task_id="task-1",
            expected_turn_id="turn-1",
            runtime_execution_id="execution-1",
            runtime_generation=1,
            kind="steer",
            actor_user_id="user-1",
            idempotency_key="steer-key",
            request_hash="steer-hash",
            payload_json='{"text":"focus"}',
            created_at=_NOW,
            updated_at=_NOW,
        )
        with pytest.raises(sqlite3.IntegrityError, match="invalid Turn Control Request"):
            repository.transition_control_request(
                control_request_id="steer-1",
                expected_status="requested",
                status="accepted",
                evidence_json='{"rpc_ack":true}',
                accepted_at=_NOW,
                updated_at=_NOW,
            )
        assert (
            repository.transition_control_request(
                control_request_id="steer-1",
                expected_status="requested",
                status="delivering",
                evidence_json='{"phase":"delivery"}',
                updated_at=_NOW,
            )
            == 1
        )
        assert (
            repository.transition_control_request(
                control_request_id="steer-1",
                expected_status="delivering",
                status="accepted",
                evidence_json='{"rpc_ack":true}',
                accepted_at=_LATER,
                updated_at=_LATER,
            )
            == 1
        )

        repository.insert_control_request(
            control_request_id="interrupt-claim",
            task_id="task-1",
            expected_turn_id="turn-1",
            runtime_execution_id="execution-1",
            runtime_generation=1,
            kind="interrupt",
            actor_user_id="user-1",
            idempotency_key="interrupt-claim-key",
            request_hash="interrupt-claim-hash",
            payload_json="{}",
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert (
            repository.claim_interrupt_request(
                control_request_id="interrupt-claim",
                evidence_json='{"delivery_claim_id":"claim-1"}',
                updated_at=_LATER,
            )
            == 1
        )
        assert (
            repository.claim_interrupt_request(
                control_request_id="interrupt-claim",
                evidence_json='{"delivery_claim_id":"claim-2"}',
                updated_at=_LATER,
            )
            == 0
        )
        claimed = conn.execute(
            "SELECT status, evidence_json FROM turn_control_requests "
            "WHERE control_request_id = 'interrupt-claim'"
        ).fetchone()
        assert claimed is not None and tuple(claimed) == (
            "requested",
            '{"delivery_claim_id":"claim-1"}',
        )

        with pytest.raises(sqlite3.IntegrityError, match="runtime scope is stale"):
            repository.insert_control_request(
                control_request_id="stale-1",
                task_id="task-1",
                expected_turn_id="turn-missing",
                runtime_execution_id="execution-1",
                runtime_generation=1,
                kind="steer",
                actor_user_id="user-1",
                idempotency_key="steer-key",
                request_hash="steer-hash",
                payload_json="{}",
                created_at=_NOW,
                updated_at=_NOW,
            )


def _preview(
    repository: SqliteConversationExecutionRepository,
    *,
    preview_id: str = "preview-1",
    preview_hash: str = "preview-hash",
    transfer_mode: str = "selected_turns",
    truncated: bool = True,
) -> None:
    repository.insert_fork_preview(
        preview_id=preview_id,
        preview_hash=preview_hash,
        source_task_id="task-1",
        source_revision="revision-1",
        source_engine_family="codex",
        target_engine_family="claude",
        transfer_mode=transfer_mode,
        transfer_range_json='{"turn_ids":["turn-1"]}',
        message_count=2,
        turn_count=1,
        item_count=3,
        character_count=100,
        utf8_byte_count=100,
        estimated_token_count=25,
        token_estimator="estimate-v1",
        context_window_percent=1.5,
        tool_result_count=1,
        reasoning_count=0,
        binary_count=0,
        image_reference_count=0,
        cost_estimate_json=None,
        cost_unknown=True,
        truncated=truncated,
        disclosure_json='{"truncated":true}',
        created_at=_NOW,
        expires_at=_EXPIRY,
    )


def test_fork_confirmation_binds_hash_revision_expiry_and_disclosure(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        _preview(repository)
        with pytest.raises(sqlite3.IntegrityError, match="does not match its preview"):
            repository.insert_fork_transfer(
                transfer_id="transfer-bad",
                preview_id="preview-1",
                preview_hash="wrong-hash",
                source_task_id="task-1",
                source_revision="revision-1",
                transfer_mode="selected_turns",
                truncation_acknowledged=False,
                full_transcript_confirmed=False,
                actor_user_id="user-1",
                idempotency_key="fork-bad",
                request_hash="fork-hash-bad",
                confirmed_at=_LATER,
                updated_at=_LATER,
            )
        with pytest.raises(sqlite3.IntegrityError, match="outside preview validity"):
            repository.insert_fork_transfer(
                transfer_id="transfer-too-early",
                preview_id="preview-1",
                preview_hash="preview-hash",
                source_task_id="task-1",
                source_revision="revision-1",
                transfer_mode="selected_turns",
                truncation_acknowledged=True,
                full_transcript_confirmed=False,
                actor_user_id="user-1",
                idempotency_key="fork-too-early",
                request_hash="fork-hash-too-early",
                confirmed_at="2026-07-17T23:59:59+00:00",
                updated_at=_NOW,
            )
        with pytest.raises(sqlite3.IntegrityError):
            repository.insert_fork_transfer(
                transfer_id="transfer-expired",
                preview_id="preview-1",
                preview_hash="preview-hash",
                source_task_id="task-1",
                source_revision="revision-1",
                transfer_mode="selected_turns",
                truncation_acknowledged=True,
                full_transcript_confirmed=False,
                actor_user_id="user-1",
                idempotency_key="fork-expired",
                request_hash="fork-hash-expired",
                confirmed_at="2026-07-18T01:00:01+00:00",
                updated_at=_LATER,
            )
        _preview(
            repository,
            preview_id="preview-mixed-offset",
            preview_hash="preview-hash-mixed-offset",
        )
        repository.insert_fork_transfer(
            transfer_id="transfer-mixed-offset",
            preview_id="preview-mixed-offset",
            preview_hash="preview-hash-mixed-offset",
            source_task_id="task-1",
            source_revision="revision-1",
            transfer_mode="selected_turns",
            truncation_acknowledged=True,
            full_transcript_confirmed=False,
            actor_user_id="user-1",
            idempotency_key="fork-mixed-offset",
            request_hash="fork-hash-mixed-offset",
            confirmed_at="2026-07-18T01:30:00+01:00",
            updated_at=_LATER,
        )
        repository.insert_fork_transfer(
            transfer_id="transfer-1",
            preview_id="preview-1",
            preview_hash="preview-hash",
            source_task_id="task-1",
            source_revision="revision-1",
            transfer_mode="selected_turns",
            truncation_acknowledged=True,
            full_transcript_confirmed=False,
            actor_user_id="user-1",
            idempotency_key="fork-key",
            request_hash="fork-hash",
            confirmed_at=_LATER,
            updated_at=_LATER,
        )
        with pytest.raises(sqlite3.IntegrityError, match="Fork target requires"):
            repository.finish_fork_transfer(
                transfer_id="transfer-1",
                status="transferred",
                target_task_id="task-legacy",
                evidence_json='{"copied":true}',
                failure_code=None,
                completed_at=_LATER,
                updated_at=_LATER,
            )
        assert (
            repository.finish_fork_transfer(
                transfer_id="transfer-1",
                status="transferred",
                target_task_id="task-2",
                evidence_json='{"copied":true}',
                failure_code=None,
                completed_at=_LATER,
                updated_at=_LATER,
            )
            == 1
        )


def test_full_transcript_requires_explicit_second_confirmation(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        repository = SqliteConversationExecutionRepository(conn)
        _preview(repository, transfer_mode="full_transcript", truncated=False)
        with pytest.raises(sqlite3.IntegrityError):
            repository.insert_fork_transfer(
                transfer_id="transfer-1",
                preview_id="preview-1",
                preview_hash="preview-hash",
                source_task_id="task-1",
                source_revision="revision-1",
                transfer_mode="full_transcript",
                truncation_acknowledged=False,
                full_transcript_confirmed=False,
                actor_user_id="user-1",
                idempotency_key="fork-key",
                request_hash="fork-hash",
                confirmed_at=_LATER,
                updated_at=_LATER,
            )


def test_legacy_upgrade_leaves_execution_tables_empty(tmp_path: Path) -> None:
    with closing(_database(tmp_path)) as conn:
        tables = (
            "turn_submissions",
            "runtime_executions",
            "turn_control_requests",
            "fork_preview_receipts",
            "fork_transfer_receipts",
        )
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables
        }
    assert counts == dict.fromkeys(tables, 0)

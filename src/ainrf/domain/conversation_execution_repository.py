"""Transaction-neutral SQLite persistence for conversation execution records.

Application services own authorization, transaction boundaries, replay policy, and
external effects. This repository exposes only guarded SQL primitives.
"""

from __future__ import annotations

import sqlite3


class SqliteConversationExecutionRepository:
    """SQL-only repository for submission, runtime, control, approval, and Fork records."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_submission(
        self,
        *,
        submission_id: str,
        task_id: str,
        reserved_turn_id: str,
        actor_user_id: str,
        idempotency_key: str,
        request_hash: str,
        input_json: str,
        context_snapshot_ref: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO turn_submissions (
                submission_id, task_id, reserved_turn_id, actor_user_id,
                idempotency_key, request_hash, status, input_json,
                context_snapshot_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (
                submission_id,
                task_id,
                reserved_turn_id,
                actor_user_id,
                idempotency_key,
                request_hash,
                input_json,
                context_snapshot_ref,
                created_at,
                updated_at,
            ),
        )

    def insert_submission_intent(
        self,
        *,
        submission_id: str,
        task_id: str,
        kind: str,
        retry_of_turn_id: str | None,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO conversation_submission_intents (
                submission_id, task_id, kind, retry_of_turn_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (submission_id, task_id, kind, retry_of_turn_id, created_at),
        )

    def submission_intent(self, submission_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM conversation_submission_intents WHERE submission_id = ?
            """,
            (submission_id,),
        ).fetchone()

    def submission_by_id(self, submission_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM turn_submissions WHERE submission_id = ?", (submission_id,)
        ).fetchone()

    def next_ready_submission(self) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT submission.*
            FROM turn_submissions AS submission
            JOIN conversation_task_states AS task_state
              ON task_state.task_id = submission.task_id
             AND task_state.work_status = 'open'
            LEFT JOIN next_turn_submissions AS next_turn
              ON next_turn.submission_id = submission.submission_id
            WHERE submission.status = 'queued'
              AND (next_turn.submission_id IS NULL OR next_turn.status = 'ready')
            ORDER BY submission.created_at, submission.submission_id
            LIMIT 1
            """
        ).fetchone()

    def pending_submission_rows(self, task_id: str) -> list[sqlite3.Row]:
        """Return pre-delivery submissions that can be cancelled atomically."""

        return self._conn.execute(
            """
            SELECT submission.*, next_turn.status AS next_turn_status
            FROM turn_submissions AS submission
            LEFT JOIN next_turn_submissions AS next_turn
              ON next_turn.submission_id = submission.submission_id
             AND next_turn.task_id = submission.task_id
            WHERE submission.task_id = ?
              AND submission.status IN ('queued', 'claimed', 'delivering')
            ORDER BY submission.created_at, submission.submission_id
            """,
            (task_id,),
        ).fetchall()

    def submission_by_task_key(
        self, *, task_id: str, actor_user_id: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM turn_submissions
            WHERE task_id = ? AND actor_user_id = ? AND idempotency_key = ?
            """,
            (task_id, actor_user_id, idempotency_key),
        ).fetchone()

    def transition_submission(
        self,
        *,
        submission_id: str,
        expected_status: str,
        status: str,
        updated_at: str,
        claimed_at: str | None = None,
        delivering_at: str | None = None,
        accepted_at: str | None = None,
        finished_at: str | None = None,
        native_turn_kind: str | None = None,
        native_turn_ref: str | None = None,
        delivery_evidence_json: str = "{}",
        failure_code: str | None = None,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE turn_submissions
            SET status = ?, claimed_at = COALESCE(?, claimed_at),
                delivering_at = COALESCE(?, delivering_at),
                accepted_at = COALESCE(?, accepted_at),
                finished_at = CASE
                    WHEN ? = 'delivered' THEN COALESCE(?, ?, finished_at)
                    ELSE COALESCE(?, finished_at) END,
                native_turn_kind = COALESCE(?, native_turn_kind),
                native_turn_ref = COALESCE(?, native_turn_ref),
                delivery_evidence_json = CASE
                    WHEN ? = '{}' THEN delivery_evidence_json ELSE ? END,
                failure_code = CASE
                    WHEN ? = 'delivered' THEN NULL
                    ELSE COALESCE(?, failure_code) END,
                updated_at = ?
            WHERE submission_id = ? AND status = ?
            """,
            (
                status,
                claimed_at,
                delivering_at,
                accepted_at,
                status,
                finished_at,
                accepted_at,
                finished_at,
                native_turn_kind,
                native_turn_ref,
                delivery_evidence_json,
                delivery_evidence_json,
                status,
                failure_code,
                updated_at,
                submission_id,
                expected_status,
            ),
        ).rowcount

    def next_execution_seq(self, turn_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(execution_seq), 0) + 1 FROM runtime_executions WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def next_runtime_generation(self, turn_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(runtime_generation), 0) + 1 FROM runtime_executions "
            "WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def insert_runtime_execution(
        self,
        *,
        runtime_execution_id: str,
        task_id: str,
        turn_id: str,
        execution_seq: int,
        runtime_generation: int,
        binding_id: str | None,
        native_runtime_kind: str | None,
        native_runtime_ref: str | None,
        native_turn_kind: str | None,
        native_turn_ref: str | None,
        evidence_json: str,
        created_at: str,
        started_at: str | None,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO runtime_executions (
                runtime_execution_id, task_id, turn_id, execution_seq,
                runtime_generation, binding_id, status, native_runtime_kind,
                native_runtime_ref, native_turn_kind, native_turn_ref,
                evidence_json, created_at, started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                runtime_execution_id,
                task_id,
                turn_id,
                execution_seq,
                runtime_generation,
                binding_id,
                native_runtime_kind,
                native_runtime_ref,
                native_turn_kind,
                native_turn_ref,
                evidence_json,
                created_at,
                started_at,
                updated_at,
            ),
        )

    def runtime_execution_by_id(self, runtime_execution_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM runtime_executions WHERE runtime_execution_id = ?",
            (runtime_execution_id,),
        ).fetchone()

    def runtime_execution_by_native_identity(
        self, *, native_runtime_kind: str, native_runtime_ref: str
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM runtime_executions
            WHERE native_runtime_kind = ? AND native_runtime_ref = ?
            """,
            (native_runtime_kind, native_runtime_ref),
        ).fetchone()

    def runtime_executions_for_turn(self, turn_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM runtime_executions WHERE turn_id = "
            "? ORDER BY runtime_generation, execution_seq",
            (turn_id,),
        ).fetchall()

    def active_runtime_execution(self, turn_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM runtime_executions
            WHERE turn_id = ? AND status IN ('starting', 'running', 'reconciling')
            """,
            (turn_id,),
        ).fetchone()

    def requested_controls(self, runtime_execution_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM turn_control_requests
            WHERE runtime_execution_id = ? AND status = 'requested'
            ORDER BY created_at, control_request_id
            """,
            (runtime_execution_id,),
        ).fetchall()

    def pending_controls(self, runtime_execution_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM turn_control_requests
            WHERE runtime_execution_id = ? AND status IN ('requested', 'delivering')
            ORDER BY created_at, control_request_id
            """,
            (runtime_execution_id,),
        ).fetchall()

    def stale_control_requests(self, stale_before: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM turn_control_requests
            WHERE updated_at < ? AND status IN ('requested', 'delivering')
            ORDER BY updated_at, control_request_id
            """,
            (stale_before,),
        ).fetchall()

    def approval_by_id(self, approval_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM runtime_approval_requests WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()

    def fork_preview_by_id(self, preview_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM fork_preview_receipts WHERE preview_id = ?", (preview_id,)
        ).fetchone()

    def insert_next_turn(
        self,
        *,
        submission_id: str,
        task_id: str,
        blocking_turn_id: str,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO next_turn_submissions (
                submission_id, task_id, blocking_turn_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'waiting', ?, ?)
            """,
            (submission_id, task_id, blocking_turn_id, created_at, created_at),
        )

    def pending_next_turn(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT next_turn.*, submission.reserved_turn_id, submission.input_json,
                   submission.context_snapshot_ref
            FROM next_turn_submissions AS next_turn
            JOIN turn_submissions AS submission
              ON submission.submission_id = next_turn.submission_id
            WHERE next_turn.task_id = ? AND next_turn.status IN ('waiting', 'ready')
              AND submission.status = 'queued'
            ORDER BY next_turn.created_at, next_turn.submission_id
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    def waiting_next_turn(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT next_turn.*, submission.reserved_turn_id, submission.input_json,
                   submission.context_snapshot_ref
            FROM next_turn_submissions AS next_turn
            JOIN turn_submissions AS submission
              ON submission.submission_id = next_turn.submission_id
            WHERE next_turn.task_id = ? AND next_turn.status = 'waiting'
            ORDER BY next_turn.created_at, next_turn.submission_id
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    def promote_next_turn(self, *, submission_id: str, promoted_at: str, updated_at: str) -> int:
        return self._conn.execute(
            """
            UPDATE next_turn_submissions
            SET status = 'ready', promoted_at = ?, updated_at = ?
            WHERE submission_id = ? AND status = 'waiting'
            """,
            (promoted_at, updated_at, submission_id),
        ).rowcount

    def cancel_next_turn(self, *, submission_id: str, updated_at: str) -> int:
        return self._conn.execute(
            """
            UPDATE next_turn_submissions
            SET status = 'cancelled', promoted_at = NULL, updated_at = ?
            WHERE submission_id = ? AND status IN ('waiting', 'ready')
            """,
            (updated_at, submission_id),
        ).rowcount

    def transition_runtime_execution(
        self,
        *,
        runtime_execution_id: str,
        expected_status: str,
        status: str,
        evidence_json: str,
        updated_at: str,
        finished_at: str | None = None,
        failure_code: str | None = None,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE runtime_executions
            SET status = ?, evidence_json = ?, finished_at = ?, failure_code = ?,
                updated_at = ?
            WHERE runtime_execution_id = ? AND status = ?
            """,
            (
                status,
                evidence_json,
                finished_at,
                failure_code,
                updated_at,
                runtime_execution_id,
                expected_status,
            ),
        ).rowcount

    def insert_control_request(
        self,
        *,
        control_request_id: str,
        task_id: str,
        expected_turn_id: str,
        runtime_execution_id: str,
        runtime_generation: int,
        kind: str,
        actor_user_id: str,
        idempotency_key: str,
        request_hash: str,
        payload_json: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO turn_control_requests (
                control_request_id, task_id, expected_turn_id,
                runtime_execution_id, runtime_generation, kind, status,
                actor_user_id, idempotency_key, request_hash, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?)
            """,
            (
                control_request_id,
                task_id,
                expected_turn_id,
                runtime_execution_id,
                runtime_generation,
                kind,
                actor_user_id,
                idempotency_key,
                request_hash,
                payload_json,
                created_at,
                updated_at,
            ),
        )

    def control_request_by_id(self, control_request_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM turn_control_requests WHERE control_request_id = ?",
            (control_request_id,),
        ).fetchone()

    def claim_interrupt_request(
        self,
        *,
        control_request_id: str,
        evidence_json: str,
        updated_at: str,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE turn_control_requests
            SET evidence_json = ?, updated_at = ?
            WHERE control_request_id = ?
              AND kind = 'interrupt'
              AND status = 'requested'
              AND evidence_json = '{}'
              AND accepted_at IS NULL
              AND completed_at IS NULL
              AND failure_code IS NULL
            """,
            (evidence_json, updated_at, control_request_id),
        ).rowcount

    def transition_control_request(
        self,
        *,
        control_request_id: str,
        expected_status: str,
        status: str,
        evidence_json: str,
        updated_at: str,
        accepted_at: str | None = None,
        completed_at: str | None = None,
        failure_code: str | None = None,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE turn_control_requests
            SET status = ?,
                evidence_json = CASE WHEN ? = '{}' THEN evidence_json ELSE ? END,
                accepted_at = COALESCE(?, accepted_at),
                completed_at = COALESCE(?, completed_at),
                failure_code = COALESCE(?, failure_code), updated_at = ?
            WHERE control_request_id = ? AND status = ?
            """,
            (
                status,
                evidence_json,
                evidence_json,
                accepted_at,
                completed_at,
                failure_code,
                updated_at,
                control_request_id,
                expected_status,
            ),
        ).rowcount

    def complete_accepted_interrupts(
        self,
        *,
        runtime_execution_id: str,
        completed_at: str,
        updated_at: str,
    ) -> int:
        """Complete accepted interrupt controls with terminal runtime evidence.

        An interrupt acknowledgement only proves that the provider accepted the
        request.  The control becomes durable ``completed`` evidence in the same
        transaction that records the interrupted RuntimeExecution/Turn.
        """

        return self._conn.execute(
            """
            UPDATE turn_control_requests
            SET status = 'completed', completed_at = ?, updated_at = ?
            WHERE runtime_execution_id = ?
              AND kind = 'interrupt'
              AND status = 'accepted'
            """,
            (completed_at, updated_at, runtime_execution_id),
        ).rowcount

    def insert_approval_request(
        self,
        *,
        approval_id: str,
        task_id: str,
        turn_id: str,
        runtime_execution_id: str,
        runtime_generation: int,
        tool_call_ref: str,
        request_json: str,
        created_at: str,
        expires_at: str | None,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO runtime_approval_requests (
                approval_id, task_id, turn_id, runtime_execution_id,
                runtime_generation, tool_call_ref, status, request_json,
                created_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                approval_id,
                task_id,
                turn_id,
                runtime_execution_id,
                runtime_generation,
                tool_call_ref,
                request_json,
                created_at,
                expires_at,
                updated_at,
            ),
        )

    def resolve_approval(
        self,
        *,
        approval_id: str,
        status: str,
        decision_json: str,
        decision_actor_user_id: str | None,
        decision_idempotency_key: str | None,
        decision_request_hash: str | None,
        resolved_at: str,
        updated_at: str,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE runtime_approval_requests
            SET status = ?, decision_json = ?, decision_actor_user_id = ?,
                decision_idempotency_key = ?, decision_request_hash = ?,
                resolved_at = ?, updated_at = ?
            WHERE approval_id = ? AND status = 'pending'
            """,
            (
                status,
                decision_json,
                decision_actor_user_id,
                decision_idempotency_key,
                decision_request_hash,
                resolved_at,
                updated_at,
                approval_id,
            ),
        ).rowcount

    def insert_fork_preview(
        self,
        *,
        preview_id: str,
        preview_hash: str,
        source_task_id: str,
        source_revision: str,
        source_engine_family: str,
        target_engine_family: str,
        target_project_id: str = "project-1",
        target_workspace_id: str = "workspace-1",
        target_harness_engine: str = "agent-sdk",
        target_title: str = "Forked Task",
        transfer_mode: str,
        transfer_range_json: str,
        message_count: int,
        turn_count: int,
        item_count: int,
        character_count: int,
        utf8_byte_count: int,
        estimated_token_count: int,
        token_estimator: str,
        context_window_percent: float | None,
        tool_result_count: int,
        reasoning_count: int,
        binary_count: int,
        image_reference_count: int,
        cost_estimate_json: str | None,
        cost_unknown: bool,
        truncated: bool,
        disclosure_json: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO fork_preview_receipts (
                preview_id, preview_hash, source_task_id, source_revision,
                source_engine_family, target_engine_family, transfer_mode,
                target_project_id, target_workspace_id, target_harness_engine, target_title,
                transfer_range_json, message_count, turn_count, item_count,
                character_count, utf8_byte_count, estimated_token_count,
                token_estimator, context_window_percent, tool_result_count,
                reasoning_count, binary_count, image_reference_count,
                cost_estimate_json, cost_unknown, truncated, disclosure_json,
                created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?)
            """,
            (
                preview_id,
                preview_hash,
                source_task_id,
                source_revision,
                source_engine_family,
                target_engine_family,
                transfer_mode,
                target_project_id,
                target_workspace_id,
                target_harness_engine,
                target_title,
                transfer_range_json,
                message_count,
                turn_count,
                item_count,
                character_count,
                utf8_byte_count,
                estimated_token_count,
                token_estimator,
                context_window_percent,
                tool_result_count,
                reasoning_count,
                binary_count,
                image_reference_count,
                cost_estimate_json,
                int(cost_unknown),
                int(truncated),
                disclosure_json,
                created_at,
                expires_at,
            ),
        )

    def insert_fork_transfer(
        self,
        *,
        transfer_id: str,
        preview_id: str,
        preview_hash: str,
        source_task_id: str,
        source_revision: str,
        transfer_mode: str,
        truncation_acknowledged: bool,
        full_transcript_confirmed: bool,
        actor_user_id: str,
        idempotency_key: str,
        request_hash: str,
        confirmed_at: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO fork_transfer_receipts (
                transfer_id, preview_id, preview_hash, source_task_id,
                source_revision, transfer_mode, truncation_acknowledged,
                full_transcript_confirmed, actor_user_id, idempotency_key,
                request_hash, status, confirmed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)
            """,
            (
                transfer_id,
                preview_id,
                preview_hash,
                source_task_id,
                source_revision,
                transfer_mode,
                int(truncation_acknowledged),
                int(full_transcript_confirmed),
                actor_user_id,
                idempotency_key,
                request_hash,
                confirmed_at,
                updated_at,
            ),
        )

    def finish_fork_transfer(
        self,
        *,
        transfer_id: str,
        status: str,
        target_task_id: str | None,
        evidence_json: str,
        failure_code: str | None,
        completed_at: str,
        updated_at: str,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE fork_transfer_receipts
            SET status = ?, target_task_id = ?, evidence_json = ?, failure_code = ?,
                completed_at = ?, updated_at = ?
            WHERE transfer_id = ? AND status = 'confirmed'
            """,
            (
                status,
                target_task_id,
                evidence_json,
                failure_code,
                completed_at,
                updated_at,
                transfer_id,
            ),
        ).rowcount

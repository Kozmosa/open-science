"""Private worker Interface for canonical Conversation execution.

HTTP and ordinary application callers use ``ConversationApplicationService``.
Only the worker crosses this Seam to claim submissions, materialize runtime
executions, append canonical Items, and consume controls.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_contracts import TurnItemActor, TurnItemType, TurnStatus
from ainrf.domain.conversation_execution_repository import (
    SqliteConversationExecutionRepository,
)
from ainrf.domain.conversation_repository import SqliteConversationRepository
from ainrf.domain.conversation_service import ConversationApplicationService
from ainrf.domain.service import DomainConflictError, DomainNotFoundError
from ainrf.domain_control import MaintenanceModeError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class SubmissionClaim:
    submission_id: str
    task_id: str
    reserved_turn_id: str
    input: dict[str, object]
    context_snapshot_ref: str | None


@dataclass(frozen=True, slots=True)
class RuntimeExecutionClaim:
    runtime_execution_id: str
    task_id: str
    turn_id: str
    runtime_generation: int


class ConversationExecutionService:
    """Deep worker Module behind a private execution Interface."""

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._application = ConversationApplicationService(
            state_root,
            artifact_sha=artifact_sha,
        )

    @staticmethod
    def _begin(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if state is None or bool(state["is_active"]):
            raise MaintenanceModeError("domain writes are paused for maintenance")

    def claim_next_submission(self) -> SubmissionClaim | None:
        """Claim the oldest ready submission with a SQLite CAS fence."""

        claimed_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                row = repository.next_ready_submission()
                if row is None:
                    conn.commit()
                    return None
                submission_id = str(row["submission_id"])
                if (
                    repository.transition_submission(
                        submission_id=submission_id,
                        expected_status="queued",
                        status="claimed",
                        claimed_at=claimed_at,
                        updated_at=claimed_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Submission claim lost its compare-and-swap race")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        raw_input = json.loads(str(row["input_json"]))
        if not isinstance(raw_input, dict):
            raise DomainConflictError("Submission input is not an object")
        return SubmissionClaim(
            submission_id=submission_id,
            task_id=str(row["task_id"]),
            reserved_turn_id=str(row["reserved_turn_id"]),
            input=raw_input,
            context_snapshot_ref=(
                None if row["context_snapshot_ref"] is None else str(row["context_snapshot_ref"])
            ),
        )

    def begin_delivery(self, submission_id: str) -> None:
        delivered_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                if repository.submission_by_id(submission_id) is None:
                    raise DomainNotFoundError(submission_id)
                if (
                    repository.transition_submission(
                        submission_id=submission_id,
                        expected_status="claimed",
                        status="delivering",
                        delivering_at=delivered_at,
                        updated_at=delivered_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Submission is no longer claimed")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def accept_and_open_execution(
        self,
        claim: SubmissionClaim,
        *,
        engine_family: str,
        engine_driver: str,
        native_turn_kind: str,
        native_turn_ref: str,
        native_runtime_kind: str | None,
        native_runtime_ref: str | None,
        evidence: Mapping[str, object],
    ) -> RuntimeExecutionClaim:
        accepted = self._application.accept_submission(
            claim.submission_id,
            native_turn_kind=native_turn_kind,
            native_turn_ref=native_turn_ref,
            engine_family=engine_family,
            engine_driver=engine_driver,
            contract_version=1,
            delivery_evidence=evidence,
        )
        turn_id = str(accepted["turn_id"])
        created_at = _now()
        runtime_execution_id = uuid4().hex
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                generation = repository.next_runtime_generation(turn_id)
                repository.insert_runtime_execution(
                    runtime_execution_id=runtime_execution_id,
                    task_id=claim.task_id,
                    turn_id=turn_id,
                    execution_seq=repository.next_execution_seq(turn_id),
                    runtime_generation=generation,
                    binding_id=None,
                    native_runtime_kind=native_runtime_kind,
                    native_runtime_ref=native_runtime_ref,
                    native_turn_kind=native_turn_kind,
                    native_turn_ref=native_turn_ref,
                    evidence_json=_canonical_json(evidence),
                    created_at=created_at,
                    started_at=created_at,
                    updated_at=created_at,
                )
                if (
                    repository.transition_runtime_execution(
                        runtime_execution_id=runtime_execution_id,
                        expected_status="starting",
                        status="running",
                        evidence_json=_canonical_json(evidence),
                        updated_at=created_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Runtime execution could not enter running state")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return RuntimeExecutionClaim(
            runtime_execution_id=runtime_execution_id,
            task_id=claim.task_id,
            turn_id=turn_id,
            runtime_generation=generation,
        )

    def append_item(
        self,
        execution: RuntimeExecutionClaim,
        *,
        item_type: TurnItemType,
        actor: TurnItemActor,
        payload: Mapping[str, object],
        native_provenance: Mapping[str, object],
        native_item_id: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, object]:
        persisted_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                executions = SqliteConversationExecutionRepository(conn)
                runtime = executions.runtime_execution_by_id(execution.runtime_execution_id)
                if runtime is None or str(runtime["status"]) != "running":
                    raise DomainConflictError("Runtime execution is not active")
                conversations = SqliteConversationRepository(conn)
                item_id = uuid4().hex
                task_item_seq = conversations.next_task_item_seq(execution.task_id)
                turn_item_seq = conversations.next_turn_item_seq(execution.turn_id)
                conversations.insert_turn_item(
                    item_id=item_id,
                    task_id=execution.task_id,
                    turn_id=execution.turn_id,
                    task_item_seq=task_item_seq,
                    turn_item_seq=turn_item_seq,
                    envelope_type="canonical_item",
                    envelope_version=1,
                    item_type=item_type,
                    actor=actor,
                    payload_json=_canonical_json(payload),
                    native_provenance_json=_canonical_json(native_provenance),
                    native_dedupe_scope=(
                        None
                        if native_item_id is None
                        else f"execution:{execution.runtime_execution_id}"
                    ),
                    native_item_id=native_item_id,
                    parent_item_id=None,
                    call_item_id=None,
                    occurred_at=occurred_at,
                    ingested_at=persisted_at,
                    persisted_at=persisted_at,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return {
            "item_id": item_id,
            "task_item_seq": task_item_seq,
            "turn_item_seq": turn_item_seq,
        }

    def requested_controls(self, execution: RuntimeExecutionClaim) -> list[dict[str, object]]:
        with closing(connect(self._db_path)) as conn:
            repository = SqliteConversationExecutionRepository(conn)
            return [
                dict(row) for row in repository.requested_controls(execution.runtime_execution_id)
            ]

    def transition_control(
        self,
        control_request_id: str,
        *,
        expected_status: str,
        status: str,
        evidence: Mapping[str, object],
        failure_code: str | None = None,
    ) -> None:
        updated_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                if (
                    repository.transition_control_request(
                        control_request_id=control_request_id,
                        expected_status=expected_status,
                        status=status,
                        evidence_json=_canonical_json(evidence),
                        updated_at=updated_at,
                        accepted_at=updated_at if status in {"accepted", "completed"} else None,
                        completed_at=(
                            updated_at
                            if status in {"completed", "rejected", "delivery_unknown"}
                            else None
                        ),
                        failure_code=failure_code,
                    )
                    != 1
                ):
                    raise DomainConflictError("Control transition lost its state race")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def finish_execution(
        self,
        execution: RuntimeExecutionClaim,
        *,
        status: TurnStatus,
        evidence: Mapping[str, object],
        failure_code: str | None = None,
    ) -> dict[str, object]:
        execution_status = {
            TurnStatus.COMPLETED: "completed",
            TurnStatus.INTERRUPTED: "interrupted",
            TurnStatus.FAILED: "failed",
        }[status]

        def finish_runtime(
            repository: SqliteConversationExecutionRepository,
            finished_at: str,
        ) -> None:
            row = repository.runtime_execution_by_id(execution.runtime_execution_id)
            if row is None:
                raise DomainNotFoundError(execution.runtime_execution_id)
            if str(row["status"]) == execution_status:
                return
            if (
                repository.transition_runtime_execution(
                    runtime_execution_id=execution.runtime_execution_id,
                    expected_status=str(row["status"]),
                    status=execution_status,
                    evidence_json=_canonical_json(evidence),
                    updated_at=finished_at,
                    finished_at=finished_at,
                    failure_code=failure_code,
                )
                != 1
            ):
                raise DomainConflictError("Runtime terminal transition lost its state race")

        return self._application.finish_turn(
            execution.task_id,
            execution.turn_id,
            status=status,
            failure_code=failure_code,
            _terminal_side_effect=finish_runtime,
        )

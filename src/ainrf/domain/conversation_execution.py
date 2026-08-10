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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_contracts import (
    ConversationContractError,
    ConversationErrorCode,
    TaskWorkStatus,
    TurnItemActor,
    TurnItemType,
    TurnStatus,
)
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


def _json_object(value: object) -> dict[str, object]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


@dataclass(frozen=True, slots=True)
class RuntimeExecutionIdentity:
    """Stable runtime identity reserved by one TurnSubmission.

    A submission is the only durable identity available before provider
    acceptance materializes a ``RuntimeExecution`` row. Deriving the row key
    here keeps worker callers from inventing their own checkpoint/session
    identity and makes retries (new submissions) naturally isolated.
    """

    submission_id: str
    runtime_execution_id: str

    @classmethod
    def for_submission(cls, submission_id: str) -> RuntimeExecutionIdentity:
        if not submission_id.strip():
            raise ValueError("submission_id must not be empty")
        return cls(
            submission_id=submission_id,
            runtime_execution_id=uuid5(
                NAMESPACE_URL,
                f"openscience-runtime-execution:{submission_id}",
            ).hex,
        )


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

    def claim_next_submission(self, *, stale_after_seconds: float = 30.0) -> SubmissionClaim | None:
        """Claim queued work or safely reclaim a pre-delivery crashed claim."""

        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")

        claimed_at = _now()
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                stale_delivering = conn.execute(
                    """
                    SELECT submission_id FROM turn_submissions
                    WHERE status = 'delivering' AND delivering_at < ?
                    ORDER BY delivering_at, submission_id
                    """,
                    (stale_before,),
                ).fetchall()
                for stale in stale_delivering:
                    repository.transition_submission(
                        submission_id=str(stale["submission_id"]),
                        expected_status="delivering",
                        status="delivery_unknown",
                        failure_code="worker_lost_during_delivery",
                        delivery_evidence_json=_canonical_json(
                            {"source": "worker_recovery", "replay_forbidden": True}
                        ),
                        updated_at=claimed_at,
                    )
                row = repository.next_ready_submission()
                if row is None:
                    row = conn.execute(
                        """
                        SELECT submission.* FROM turn_submissions AS submission
                        JOIN conversation_task_states AS task_state
                          ON task_state.task_id = submission.task_id
                         AND task_state.work_status = 'open'
                        LEFT JOIN next_turn_submissions AS next_turn
                          ON next_turn.submission_id = submission.submission_id
                        WHERE submission.status = 'claimed' AND submission.claimed_at < ?
                          AND (next_turn.submission_id IS NULL OR next_turn.status = 'ready')
                        ORDER BY submission.claimed_at, submission.submission_id
                        LIMIT 1
                        """,
                        (stale_before,),
                    ).fetchone()
                    if row is not None:
                        updated = conn.execute(
                            """
                            UPDATE turn_submissions SET claimed_at = ?, updated_at = ?
                            WHERE submission_id = ? AND status = 'claimed' AND claimed_at = ?
                              AND EXISTS (
                                  SELECT 1 FROM conversation_task_states AS task_state
                                  WHERE task_state.task_id = turn_submissions.task_id
                                    AND task_state.work_status = 'open'
                              )
                            """,
                            (claimed_at, claimed_at, row["submission_id"], row["claimed_at"]),
                        ).rowcount
                        if updated != 1:
                            raise DomainConflictError(
                                "Stale submission reclaim lost its compare-and-swap race"
                            )
                if row is None:
                    conn.commit()
                    return None
                submission_id = str(row["submission_id"])
                if str(row["status"]) == "queued" and (
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

    def runtime_identity_for_launch_context(
        self, claim: SubmissionClaim
    ) -> RuntimeExecutionIdentity:
        """Resolve identity for a worker launch/checkpoint context.

        Claimed/delivering submissions without a persisted execution are the
        normal pre-launch path and receive a deterministic identity. A
        delivered/delivery-unknown submission may only reconnect to one
        persisted active execution; without that durable evidence, launching
        again would cross an unknown external side-effect boundary.
        """

        submission_status, deterministic, rows = self._validated_runtime_identity_inputs(claim)
        active, terminal = self._partition_runtime_rows(rows)
        if terminal:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "Terminal RuntimeExecution cannot establish a new context",
            )
        if len(active) > 1:
            raise DomainConflictError("Submission Turn has multiple active RuntimeExecutions")
        if submission_status in {"claimed", "delivering"}:
            if active:
                raise ConversationContractError(
                    ConversationErrorCode.INVALID_STATE_TRANSITION,
                    "Active RuntimeExecution requires delivered recovery evidence",
                )
            return deterministic
        if submission_status in {"delivered", "delivery_unknown"} and active:
            return RuntimeExecutionIdentity(
                submission_id=claim.submission_id,
                runtime_execution_id=str(active[0]["runtime_execution_id"]),
            )
        raise ConversationContractError(
            ConversationErrorCode.INVALID_STATE_TRANSITION,
            "Submission has no persisted RuntimeExecution to establish a launch context",
        )

    def _runtime_identity_for_acceptance(self, claim: SubmissionClaim) -> RuntimeExecutionIdentity:
        """Resolve identity for atomic provider-acceptance materialization.

        Acceptance recovery is intentionally narrower in visibility but wider
        in materialization authority than launch-context resolution: a
        delivered/delivery-unknown callback may prove acceptance while its
        RuntimeExecution row is still absent, so the deterministic identity is
        allowed here and immediately persisted by ``accept_and_open_execution``.
        """

        submission_status, deterministic, rows = self._validated_runtime_identity_inputs(claim)
        if submission_status not in {"delivering", "delivered", "delivery_unknown"}:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "Only a delivering or reconciliable submission can materialize acceptance",
            )
        active, terminal = self._partition_runtime_rows(rows)
        if terminal:
            raise ConversationContractError(
                ConversationErrorCode.INVALID_STATE_TRANSITION,
                "Terminal RuntimeExecution cannot establish a new context",
            )
        if len(active) > 1:
            raise DomainConflictError("Submission Turn has multiple active RuntimeExecutions")
        if active:
            if submission_status not in {"delivered", "delivery_unknown"}:
                raise ConversationContractError(
                    ConversationErrorCode.INVALID_STATE_TRANSITION,
                    "Active RuntimeExecution requires delivered recovery evidence",
                )
            return RuntimeExecutionIdentity(
                submission_id=claim.submission_id,
                runtime_execution_id=str(active[0]["runtime_execution_id"]),
            )
        return deterministic

    def _validated_runtime_identity_inputs(
        self, claim: SubmissionClaim
    ) -> tuple[str, RuntimeExecutionIdentity, list[sqlite3.Row]]:
        """Validate claim ownership and collect all rows relevant to identity."""

        with closing(connect(self._db_path)) as conn:
            repository = SqliteConversationExecutionRepository(conn)
            submission = repository.submission_by_id(claim.submission_id)
            if submission is None:
                raise DomainConflictError("Submission claim has no authoritative submission record")
            authoritative_task_id = str(submission["task_id"])
            authoritative_turn_id = str(submission["reserved_turn_id"])
            if (
                authoritative_task_id != claim.task_id
                or authoritative_turn_id != claim.reserved_turn_id
            ):
                raise DomainConflictError(
                    "Submission claim does not match its authoritative Task and Turn"
                )
            submission_status = str(submission["status"])
            if submission_status in {"cancelled", "failed_delivery"}:
                raise ConversationContractError(
                    ConversationErrorCode.INVALID_STATE_TRANSITION,
                    "Terminal submission cannot establish a RuntimeExecution context",
                )
            if submission_status not in {
                "queued",
                "claimed",
                "delivering",
                "delivered",
                "delivery_unknown",
            }:
                raise DomainConflictError("Submission has an unknown durable status")

            deterministic = RuntimeExecutionIdentity.for_submission(claim.submission_id)
            rows = repository.runtime_executions_for_turn(authoritative_turn_id)
            persisted_deterministic = repository.runtime_execution_by_id(
                deterministic.runtime_execution_id
            )
            if persisted_deterministic is not None and all(
                str(row["runtime_execution_id"]) != deterministic.runtime_execution_id
                for row in rows
            ):
                rows.append(persisted_deterministic)

            for row in rows:
                runtime_task_id = str(row["task_id"])
                runtime_turn_id = str(row["turn_id"])
                raw_runtime_execution_id = row["runtime_execution_id"]
                runtime_execution_id = (
                    raw_runtime_execution_id.strip()
                    if isinstance(raw_runtime_execution_id, str)
                    else ""
                )
                if (
                    runtime_task_id != authoritative_task_id
                    or runtime_turn_id != authoritative_turn_id
                    or not runtime_execution_id
                    or runtime_execution_id != raw_runtime_execution_id
                ):
                    raise DomainConflictError(
                        "RuntimeExecution does not belong to the claimed Task and Turn"
                    )
                status = str(row["status"])
                if status not in {
                    "starting",
                    "running",
                    "reconciling",
                    "completed",
                    "interrupted",
                    "failed",
                    "unknown",
                }:
                    raise DomainConflictError("RuntimeExecution has an unknown durable status")
            return submission_status, deterministic, rows

    @staticmethod
    def _partition_runtime_rows(
        rows: list[sqlite3.Row],
    ) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
        active: list[sqlite3.Row] = []
        terminal: list[sqlite3.Row] = []
        for row in rows:
            status = str(row["status"])
            if status in {"starting", "running", "reconciling"}:
                active.append(row)
            elif status in {"completed", "interrupted", "failed", "unknown"}:
                terminal.append(row)
            else:
                raise DomainConflictError("RuntimeExecution has an unknown durable status")
        return active, terminal

    def mark_delivery_unknown(
        self,
        submission_id: str,
        *,
        failure_code: str,
        evidence: Mapping[str, object],
    ) -> None:
        """Fence a delivery whose external acceptance cannot be proven."""

        updated_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                row = repository.submission_by_id(submission_id)
                if row is None:
                    raise DomainNotFoundError(submission_id)
                if str(row["status"]) == "delivery_unknown":
                    conn.commit()
                    return
                if (
                    repository.transition_submission(
                        submission_id=submission_id,
                        expected_status="delivering",
                        status="delivery_unknown",
                        failure_code=failure_code,
                        delivery_evidence_json=_canonical_json(evidence),
                        updated_at=updated_at,
                    )
                    != 1
                ):
                    raise DomainConflictError("Submission is no longer delivering")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def begin_delivery(self, submission_id: str) -> None:
        """Arm durable delivery immediately before the Runtime Adapter starts."""

        delivered_at = _now()
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                submission = repository.submission_by_id(submission_id)
                if submission is None:
                    raise DomainNotFoundError(submission_id)
                task_state = SqliteConversationRepository(conn).task_state(
                    str(submission["task_id"])
                )
                if task_state is None or str(task_state["work_status"]) != TaskWorkStatus.OPEN:
                    raise ConversationContractError(
                        ConversationErrorCode.TASK_NOT_OPEN,
                        "Task was closed before submission delivery began",
                    )
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
        native_conversation_kind: str,
        native_conversation_ref: str,
        native_turn_kind: str,
        native_turn_ref: str,
        native_runtime_kind: str | None,
        native_runtime_ref: str | None,
        evidence: Mapping[str, object],
    ) -> RuntimeExecutionClaim:
        runtime_execution_id = self._runtime_identity_for_acceptance(claim).runtime_execution_id

        runtime_claim: RuntimeExecutionClaim | None = None

        def persist_runtime(
            repository: SqliteConversationExecutionRepository,
            turn_id: str,
            accepted_at: str,
            binding_id: str | None,
        ) -> None:
            nonlocal runtime_claim
            if native_runtime_kind is not None and native_runtime_ref is not None:
                global_identity = repository.runtime_execution_by_native_identity(
                    native_runtime_kind=native_runtime_kind,
                    native_runtime_ref=native_runtime_ref,
                )
                if global_identity is not None and str(global_identity["turn_id"]) != turn_id:
                    raise DomainConflictError(
                        "Native RuntimeExecution identity is already bound to another Turn"
                    )
            existing = repository.runtime_executions_for_turn(turn_id)
            for row in existing:
                if (
                    str(row["task_id"]) != claim.task_id
                    or (None if row["binding_id"] is None else str(row["binding_id"])) != binding_id
                    or str(row["native_turn_kind"]) != native_turn_kind
                    or str(row["native_turn_ref"]) != native_turn_ref
                    or str(row["native_runtime_kind"]) != str(native_runtime_kind)
                    or str(row["native_runtime_ref"]) != str(native_runtime_ref)
                ):
                    raise DomainConflictError(
                        "Runtime execution native identity contradicts the accepted Turn"
                    )
            terminal = [
                row
                for row in existing
                if str(row["status"]) in {"completed", "interrupted", "failed", "unknown"}
            ]
            if terminal:
                raise DomainConflictError("Accepted Turn already has a terminal RuntimeExecution")
            active = [
                row
                for row in existing
                if str(row["status"]) in {"starting", "running", "reconciling"}
            ]
            if len(active) > 1:
                raise DomainConflictError("Accepted Turn has multiple active RuntimeExecutions")
            if active:
                row = active[0]
                existing_runtime_execution_id = str(row["runtime_execution_id"])
                if str(row["status"]) == "starting":
                    if (
                        repository.transition_runtime_execution(
                            runtime_execution_id=existing_runtime_execution_id,
                            expected_status="starting",
                            status="running",
                            evidence_json=str(row["evidence_json"]),
                            updated_at=accepted_at,
                        )
                        != 1
                    ):
                        raise DomainConflictError(
                            "Existing RuntimeExecution could not enter running state"
                        )
                runtime_claim = RuntimeExecutionClaim(
                    runtime_execution_id=existing_runtime_execution_id,
                    task_id=claim.task_id,
                    turn_id=turn_id,
                    runtime_generation=int(row["runtime_generation"]),
                )
                return
            generation = repository.next_runtime_generation(turn_id)
            try:
                repository.insert_runtime_execution(
                    runtime_execution_id=runtime_execution_id,
                    task_id=claim.task_id,
                    turn_id=turn_id,
                    execution_seq=repository.next_execution_seq(turn_id),
                    runtime_generation=generation,
                    binding_id=binding_id,
                    native_runtime_kind=native_runtime_kind,
                    native_runtime_ref=native_runtime_ref,
                    native_turn_kind=native_turn_kind,
                    native_turn_ref=native_turn_ref,
                    evidence_json=_canonical_json(evidence),
                    created_at=accepted_at,
                    started_at=accepted_at,
                    updated_at=accepted_at,
                )
            except sqlite3.IntegrityError as exc:
                raise DomainConflictError(
                    "Native RuntimeExecution identity could not be claimed"
                ) from exc
            if (
                repository.transition_runtime_execution(
                    runtime_execution_id=runtime_execution_id,
                    expected_status="starting",
                    status="running",
                    evidence_json=_canonical_json(evidence),
                    updated_at=accepted_at,
                )
                != 1
            ):
                raise DomainConflictError("Runtime execution could not enter running state")
            runtime_claim = RuntimeExecutionClaim(
                runtime_execution_id=runtime_execution_id,
                task_id=claim.task_id,
                turn_id=turn_id,
                runtime_generation=generation,
            )

        self._application.accept_submission(
            claim.submission_id,
            native_turn_kind=native_turn_kind,
            native_turn_ref=native_turn_ref,
            engine_family=engine_family,
            engine_driver=engine_driver,
            native_conversation_kind=native_conversation_kind,
            native_conversation_ref=native_conversation_ref,
            contract_version=1,
            delivery_evidence=evidence,
            _post_accept_side_effect=persist_runtime,
        )
        if runtime_claim is None:
            raise DomainConflictError("Accepted Turn did not persist its RuntimeExecution")
        return runtime_claim

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

    def claim_interrupt(self, control_request_id: str, *, claim_id: str) -> bool:
        """Durably serialize one interrupt adapter call.

        Interrupt has no ``delivering`` state in the public contract.  Its
        requested row therefore carries a durable claim marker while the
        adapter call is in flight.  A competing worker cannot claim that row,
        and recovery fences a stale marker as delivery-unknown instead of
        replaying an external interrupt.
        """

        if not claim_id.strip():
            raise ValueError("claim_id must not be empty")
        claimed_at = _now()
        evidence = {
            "delivery_claim_id": claim_id,
            "delivery_claimed_at": claimed_at,
        }
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                row = repository.control_request_by_id(control_request_id)
                if row is None:
                    raise DomainNotFoundError(control_request_id)
                if str(row["kind"]) != "interrupt" or str(row["status"]) != "requested":
                    conn.commit()
                    return False
                claimed = repository.claim_interrupt_request(
                    control_request_id=control_request_id,
                    evidence_json=_canonical_json(evidence),
                    updated_at=claimed_at,
                )
                conn.commit()
                return claimed == 1
            except BaseException:
                conn.rollback()
                raise

    def recover_stale_control_delivery(self, *, stale_after_seconds: float = 30.0) -> int:
        """Fence controls left in-flight by a crashed worker without replay."""

        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        recovered_at = _now()
        recovered = 0
        with closing(connect(self._db_path)) as conn:
            try:
                self._begin(conn)
                repository = SqliteConversationExecutionRepository(conn)
                for row in repository.stale_control_requests(stale_before):
                    current_status = str(row["status"])
                    kind = str(row["kind"])
                    evidence = _json_object(row["evidence_json"])
                    if current_status == "requested" and (
                        kind != "interrupt" or not evidence.get("delivery_claim_id")
                    ):
                        continue
                    evidence.update(
                        {
                            "source": "worker_recovery",
                            "failure": "control_delivery_stale",
                            "replay_forbidden": True,
                        }
                    )
                    if (
                        repository.transition_control_request(
                            control_request_id=str(row["control_request_id"]),
                            expected_status=current_status,
                            status="delivery_unknown",
                            evidence_json=_canonical_json(evidence),
                            updated_at=recovered_at,
                            completed_at=recovered_at,
                            failure_code="worker_lost_during_control_delivery",
                        )
                        == 1
                    ):
                        recovered += 1
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return recovered

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

    def _reconcile_terminal_controls(
        self,
        repository: SqliteConversationExecutionRepository,
        execution: RuntimeExecutionClaim,
        *,
        terminal_status: str,
        finished_at: str,
        terminal_evidence: Mapping[str, object],
    ) -> None:
        for row in repository.pending_controls(execution.runtime_execution_id):
            current_status = str(row["status"])
            kind = str(row["kind"])
            evidence = _json_object(row["evidence_json"])
            delivery_unknown = current_status == "delivering" or (
                kind == "interrupt" and bool(evidence.get("delivery_claim_id"))
            )
            status = "delivery_unknown" if delivery_unknown else "rejected"
            evidence.update(
                {
                    "source": "runtime_terminal_reconciliation",
                    "runtime_status": terminal_status,
                    "replay_forbidden": delivery_unknown,
                    "terminal_evidence": dict(terminal_evidence),
                }
            )
            failure_code = (
                "control_delivery_unknown_runtime_terminal"
                if delivery_unknown
                else "runtime_terminal_before_control_delivery"
            )
            if (
                repository.transition_control_request(
                    control_request_id=str(row["control_request_id"]),
                    expected_status=current_status,
                    status=status,
                    evidence_json=_canonical_json(evidence),
                    updated_at=finished_at,
                    completed_at=finished_at,
                    failure_code=failure_code,
                )
                != 1
            ):
                raise DomainConflictError("Terminal control reconciliation lost its state race")

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
                if execution_status == "interrupted":
                    repository.complete_accepted_interrupts(
                        runtime_execution_id=execution.runtime_execution_id,
                        completed_at=finished_at,
                        updated_at=finished_at,
                    )
                self._reconcile_terminal_controls(
                    repository,
                    execution,
                    terminal_status=execution_status,
                    finished_at=finished_at,
                    terminal_evidence=evidence,
                )
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
            if execution_status == "interrupted":
                repository.complete_accepted_interrupts(
                    runtime_execution_id=execution.runtime_execution_id,
                    completed_at=finished_at,
                    updated_at=finished_at,
                )
            self._reconcile_terminal_controls(
                repository,
                execution,
                terminal_status=execution_status,
                finished_at=finished_at,
                terminal_evidence=evidence,
            )

        return self._application.finish_turn(
            execution.task_id,
            execution.turn_id,
            status=status,
            failure_code=failure_code,
            _terminal_side_effect=finish_runtime,
        )

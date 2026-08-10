from __future__ import annotations

import pytest

from ainrf.domain.conversation_contracts import (
    CapabilityDeclaration,
    CapabilitySupport,
    ConversationContractError,
    ConversationErrorCode,
    ControlKind,
    ControlRequestStatus,
    EngineCapability,
    EngineDriver,
    EngineFamily,
    NativeReceipt,
    NativeReceiptKind,
    NativeReceiptMetadata,
    OpaqueNativeReference,
    ReceiptConfidence,
    RuntimeActiveFlag,
    RuntimeExecutionStatus,
    RuntimeProjection,
    RuntimeProjectionState,
    TaskWorkStatus,
    TurnAcceptanceBoundary,
    TurnStatus,
    TurnSubmissionStatus,
    require_control_transition,
    require_runtime_execution_transition,
    require_single_active_turn,
    require_submission_transition,
    require_task_work_transition,
    require_turn_transition,
    translate_codex_active_flag,
    translate_codex_runtime_state,
    translate_codex_turn_status,
)

pytestmark = [pytest.mark.unit]


def test_task_work_status_allows_close_cancel_and_explicit_reopen() -> None:
    require_task_work_transition(TaskWorkStatus.OPEN, TaskWorkStatus.COMPLETED)
    require_task_work_transition(TaskWorkStatus.OPEN, TaskWorkStatus.CANCELLED)
    require_task_work_transition(TaskWorkStatus.COMPLETED, TaskWorkStatus.OPEN)
    require_task_work_transition(TaskWorkStatus.CANCELLED, TaskWorkStatus.OPEN)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskWorkStatus.COMPLETED, TaskWorkStatus.CANCELLED),
        (TaskWorkStatus.CANCELLED, TaskWorkStatus.COMPLETED),
        (TaskWorkStatus.OPEN, TaskWorkStatus.OPEN),
    ],
)
def test_task_work_status_rejects_implicit_or_noop_transitions(
    current: TaskWorkStatus, target: TaskWorkStatus
) -> None:
    with pytest.raises(ConversationContractError) as caught:
        require_task_work_transition(current, target)

    assert caught.value.code is ConversationErrorCode.INVALID_STATE_TRANSITION


@pytest.mark.parametrize(
    "terminal",
    [TurnStatus.COMPLETED, TurnStatus.INTERRUPTED, TurnStatus.FAILED],
)
def test_turn_can_finish_only_from_in_progress(terminal: TurnStatus) -> None:
    require_turn_transition(TurnStatus.IN_PROGRESS, terminal)

    with pytest.raises(ConversationContractError):
        require_turn_transition(terminal, TurnStatus.IN_PROGRESS)


def test_submission_delivery_unknown_requires_explicit_reconciliation() -> None:
    require_submission_transition(
        TurnSubmissionStatus.DELIVERING, TurnSubmissionStatus.DELIVERY_UNKNOWN
    )
    require_submission_transition(
        TurnSubmissionStatus.DELIVERY_UNKNOWN, TurnSubmissionStatus.DELIVERED
    )
    require_submission_transition(
        TurnSubmissionStatus.DELIVERY_UNKNOWN,
        TurnSubmissionStatus.FAILED_DELIVERY,
    )

    with pytest.raises(ConversationContractError):
        require_submission_transition(
            TurnSubmissionStatus.DELIVERY_UNKNOWN, TurnSubmissionStatus.QUEUED
        )


def test_pre_delivery_submission_cancellation_does_not_create_a_turn_state() -> None:
    require_submission_transition(TurnSubmissionStatus.QUEUED, TurnSubmissionStatus.CANCELLED)
    assert set(TurnStatus).isdisjoint(set(TurnSubmissionStatus))


def test_runtime_reconciliation_can_recover_or_fail_closed() -> None:
    for target in (
        RuntimeExecutionStatus.RUNNING,
        RuntimeExecutionStatus.COMPLETED,
        RuntimeExecutionStatus.INTERRUPTED,
        RuntimeExecutionStatus.FAILED,
        RuntimeExecutionStatus.UNKNOWN,
    ):
        require_runtime_execution_transition(RuntimeExecutionStatus.RECONCILING, target)

    with pytest.raises(ConversationContractError):
        require_runtime_execution_transition(
            RuntimeExecutionStatus.UNKNOWN, RuntimeExecutionStatus.RUNNING
        )


def test_control_acceptance_and_terminal_evidence_are_separate() -> None:
    require_control_transition(
        ControlKind.INTERRUPT,
        ControlRequestStatus.REQUESTED,
        ControlRequestStatus.ACCEPTED,
    )
    require_control_transition(
        ControlKind.INTERRUPT,
        ControlRequestStatus.ACCEPTED,
        ControlRequestStatus.COMPLETED,
    )

    with pytest.raises(ConversationContractError):
        require_control_transition(
            ControlKind.STEER,
            ControlRequestStatus.ACCEPTED,
            ControlRequestStatus.COMPLETED,
        )


def test_single_active_turn_invariant_is_task_scoped() -> None:
    require_single_active_turn((TurnStatus.COMPLETED, TurnStatus.IN_PROGRESS, TurnStatus.FAILED))

    with pytest.raises(ConversationContractError) as caught:
        require_single_active_turn((TurnStatus.IN_PROGRESS, TurnStatus.IN_PROGRESS))

    assert caught.value.code is ConversationErrorCode.ACTIVE_TURN_EXISTS


def test_runtime_projection_keeps_flags_orthogonal_to_work_status() -> None:
    projection = RuntimeProjection(
        state=RuntimeProjectionState.ACTIVE,
        active_flags=(RuntimeActiveFlag.WAITING_ON_APPROVAL,),
    )

    assert projection.state is RuntimeProjectionState.ACTIVE
    assert TaskWorkStatus.OPEN.value not in {flag.value for flag in projection.active_flags}

    with pytest.raises(ConversationContractError):
        RuntimeProjection(
            state=RuntimeProjectionState.IDLE,
            active_flags=(RuntimeActiveFlag.WAITING_ON_USER_INPUT,),
        )


def test_capability_contract_distinguishes_provider_from_adapter() -> None:
    declaration = CapabilityDeclaration(
        capability=EngineCapability.SAME_TURN_STEER,
        provider_support=CapabilitySupport.NATIVE,
        adapter_support=CapabilitySupport.UNSUPPORTED,
    )
    boundary = TurnAcceptanceBoundary(
        driver=EngineDriver.CLAUDE_CODE_CLI,
        evidence="owned process spawned and prompt written",
        confidence=ReceiptConfidence.UNVERIFIED,
    )

    assert declaration.provider_support is CapabilitySupport.NATIVE
    assert declaration.adapter_support is CapabilitySupport.UNSUPPORTED
    assert boundary.confidence is ReceiptConfidence.UNVERIFIED


def test_receipt_contains_only_opaque_sanitized_native_evidence() -> None:
    receipt = NativeReceipt(
        kind=NativeReceiptKind.START_ACCEPTED,
        task_id="task-001",
        turn_id="turn-001",
        native_references=(
            OpaqueNativeReference(
                provider=EngineFamily.CODEX,
                reference_type="turn",
                value="native-turn-001",
            ),
        ),
        metadata=NativeReceiptMetadata(attributes=(("protocol_version", "0.144.5"),)),
    )

    assert receipt.native_references[0].reference_type == "turn"

    for key in ("api_key", "Authorization", "client-secret", "credential_ref"):
        with pytest.raises(ConversationContractError):
            NativeReceiptMetadata(attributes=((key, "redacted"),))

    with pytest.raises(ConversationContractError):
        NativeReceiptMetadata(attributes=(("result", "Bearer private-value"),))


def test_codex_wire_values_translate_to_canonical_values() -> None:
    assert translate_codex_turn_status("inProgress") is TurnStatus.IN_PROGRESS
    assert translate_codex_runtime_state("notLoaded") is RuntimeProjectionState.NOT_LOADED
    assert translate_codex_active_flag("waitingOnApproval") is RuntimeActiveFlag.WAITING_ON_APPROVAL

    with pytest.raises(ConversationContractError) as caught:
        translate_codex_turn_status("paused")

    assert caught.value.code is ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH

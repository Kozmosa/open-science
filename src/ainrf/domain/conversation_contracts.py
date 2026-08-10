"""Stable conversation-domain contracts shared by persistence, drivers, and APIs."""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class TaskWorkStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TurnStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class TurnSubmissionStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DELIVERY_UNKNOWN = "delivery_unknown"
    FAILED_DELIVERY = "failed_delivery"


class RuntimeExecutionStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RuntimeProjectionState(StrEnum):
    NOT_LOADED = "not_loaded"
    IDLE = "idle"
    ACTIVE = "active"
    SYSTEM_ERROR = "system_error"


class RuntimeActiveFlag(StrEnum):
    WAITING_ON_APPROVAL = "waiting_on_approval"
    WAITING_ON_USER_INPUT = "waiting_on_user_input"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ControlKind(StrEnum):
    STEER = "steer"
    INTERRUPT = "interrupt"


class ControlRequestStatus(StrEnum):
    REQUESTED = "requested"
    DELIVERING = "delivering"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REJECTED = "rejected"
    DELIVERY_UNKNOWN = "delivery_unknown"


class CapabilitySupport(StrEnum):
    NATIVE = "native"
    EMULATED = "emulated"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class EngineFamily(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"


class EngineDriver(StrEnum):
    CODEX_APP_SERVER = "codex-app-server"
    CLAUDE_CODE_CLI = "claude-code"
    CLAUDE_AGENT_SDK = "agent-sdk"


class EngineCapability(StrEnum):
    DURABLE_CONVERSATION = "durable_conversation"
    NATIVE_TURN_ID = "native_turn_id"
    SAME_TURN_STEER = "same_turn_steer"
    INTERRUPT = "interrupt"
    APPROVALS = "approvals"
    RECONNECT = "reconnect"
    FORK = "fork"
    TYPED_ITEMS = "typed_items"
    USAGE = "usage"
    ACTIVE_RUNTIME_ADOPTION = "active_runtime_adoption"


class ReceiptConfidence(StrEnum):
    PROVEN = "proven"
    DEGRADED = "degraded"
    UNVERIFIED = "unverified"


class TurnItemType(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    REASONING_SUMMARY = "reasoning_summary"
    COMMAND_EXECUTION = "command_execution"
    FILE_CHANGE = "file_change"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESULT = "approval_result"
    SYSTEM_NOTICE = "system_notice"
    PLAN_UPDATE = "plan_update"
    ERROR = "error"


class TurnItemActor(StrEnum):
    USER = "user"
    AGENT = "agent"
    TOOL = "tool"
    SYSTEM = "system"


class UsageCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class UsageSource(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    DRIVER_OBSERVED = "driver_observed"
    UNAVAILABLE = "unavailable"


class ForkTransferMode(StrEnum):
    SELECTED_TURNS = "selected_turns"
    RECENT_TURNS = "recent_turns"
    FULL_TRANSCRIPT = "full_transcript"
    CONTEXT_ONLY = "context_only"


class ConversationErrorCode(StrEnum):
    ACTIVE_TURN_EXISTS = "active_turn_exists"
    EXPECTED_TURN_MISMATCH = "expected_turn_mismatch"
    TURN_NOT_ACTIVE = "turn_not_active"
    DELIVERY_UNKNOWN = "delivery_unknown"
    RUNTIME_LOST = "runtime_lost"
    SESSION_UNAVAILABLE = "session_unavailable"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    TASK_NOT_OPEN = "task_not_open"
    FORK_CONFIRMATION_REQUIRED = "fork_confirmation_required"
    MIGRATION_REQUIRED = "migration_required"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    PROVIDER_CONTRACT_MISMATCH = "provider_contract_mismatch"


class IdempotencyScope(StrEnum):
    CREATE_TASK = "create_task"
    CREATE_TURN = "create_turn"
    RETRY_TURN = "retry_turn"
    STEER_TURN = "steer_turn"
    INTERRUPT_TURN = "interrupt_turn"
    RESOLVE_APPROVAL = "resolve_approval"
    UPDATE_WORK_STATUS = "update_work_status"
    FORK_PREVIEW = "fork_preview"
    FORK_CONFIRM = "fork_confirm"
    CANCEL_TASK = "cancel_task"
    ARCHIVE_TASK = "archive_task"
    UNARCHIVE_TASK = "unarchive_task"
    UPDATE_TASK_TITLE = "update_task_title"
    MOVE_TASK = "move_task"


class AdmissionFact(StrEnum):
    REQUEST_ACCEPTED = "request_accepted"
    PROVIDER_ACCEPTED = "provider_accepted"
    TERMINAL_EVIDENCE = "terminal_evidence"


class NativeReceiptKind(StrEnum):
    START_ACCEPTED = "start_accepted"
    STEER_ACCEPTED = "steer_accepted"
    INTERRUPT_REQUESTED = "interrupt_requested"
    TERMINAL_EVIDENCE = "terminal_evidence"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"


class ConversationContractError(ValueError):
    """A stable contract was violated before a side effect was attempted."""

    def __init__(self, code: ConversationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


_TASK_TRANSITIONS: Final = {
    TaskWorkStatus.OPEN: frozenset({TaskWorkStatus.COMPLETED, TaskWorkStatus.CANCELLED}),
    TaskWorkStatus.COMPLETED: frozenset({TaskWorkStatus.OPEN}),
    TaskWorkStatus.CANCELLED: frozenset({TaskWorkStatus.OPEN}),
}
_TURN_TRANSITIONS: Final = {
    TurnStatus.IN_PROGRESS: frozenset(
        {TurnStatus.COMPLETED, TurnStatus.INTERRUPTED, TurnStatus.FAILED}
    ),
    TurnStatus.COMPLETED: frozenset(),
    TurnStatus.INTERRUPTED: frozenset(),
    TurnStatus.FAILED: frozenset(),
}
_SUBMISSION_TRANSITIONS: Final = {
    TurnSubmissionStatus.QUEUED: frozenset(
        {TurnSubmissionStatus.CLAIMED, TurnSubmissionStatus.CANCELLED}
    ),
    TurnSubmissionStatus.CLAIMED: frozenset(
        {TurnSubmissionStatus.DELIVERING, TurnSubmissionStatus.CANCELLED}
    ),
    TurnSubmissionStatus.DELIVERING: frozenset(
        {TurnSubmissionStatus.DELIVERED, TurnSubmissionStatus.DELIVERY_UNKNOWN}
    ),
    TurnSubmissionStatus.DELIVERY_UNKNOWN: frozenset(
        {TurnSubmissionStatus.DELIVERED, TurnSubmissionStatus.FAILED_DELIVERY}
    ),
    TurnSubmissionStatus.DELIVERED: frozenset(),
    TurnSubmissionStatus.CANCELLED: frozenset(),
    TurnSubmissionStatus.FAILED_DELIVERY: frozenset(),
}
_RUNTIME_EXECUTION_TRANSITIONS: Final = {
    RuntimeExecutionStatus.STARTING: frozenset(
        {
            RuntimeExecutionStatus.RUNNING,
            RuntimeExecutionStatus.RECONCILING,
            RuntimeExecutionStatus.FAILED,
        }
    ),
    RuntimeExecutionStatus.RUNNING: frozenset(
        {
            RuntimeExecutionStatus.RECONCILING,
            RuntimeExecutionStatus.COMPLETED,
            RuntimeExecutionStatus.INTERRUPTED,
            RuntimeExecutionStatus.FAILED,
        }
    ),
    RuntimeExecutionStatus.RECONCILING: frozenset(
        {
            RuntimeExecutionStatus.RUNNING,
            RuntimeExecutionStatus.COMPLETED,
            RuntimeExecutionStatus.INTERRUPTED,
            RuntimeExecutionStatus.FAILED,
            RuntimeExecutionStatus.UNKNOWN,
        }
    ),
    RuntimeExecutionStatus.COMPLETED: frozenset(),
    RuntimeExecutionStatus.INTERRUPTED: frozenset(),
    RuntimeExecutionStatus.FAILED: frozenset(),
    RuntimeExecutionStatus.UNKNOWN: frozenset(),
}
_CONTROL_TRANSITIONS: Final = {
    ControlKind.STEER: {
        ControlRequestStatus.REQUESTED: frozenset(
            {
                ControlRequestStatus.DELIVERING,
                ControlRequestStatus.REJECTED,
            }
        ),
        ControlRequestStatus.DELIVERING: frozenset(
            {
                ControlRequestStatus.ACCEPTED,
                ControlRequestStatus.REJECTED,
                ControlRequestStatus.DELIVERY_UNKNOWN,
            }
        ),
        ControlRequestStatus.ACCEPTED: frozenset(),
        ControlRequestStatus.COMPLETED: frozenset(),
        ControlRequestStatus.REJECTED: frozenset(),
        ControlRequestStatus.DELIVERY_UNKNOWN: frozenset(),
    },
    ControlKind.INTERRUPT: {
        ControlRequestStatus.REQUESTED: frozenset(
            {
                ControlRequestStatus.ACCEPTED,
                ControlRequestStatus.REJECTED,
                ControlRequestStatus.DELIVERY_UNKNOWN,
            }
        ),
        ControlRequestStatus.ACCEPTED: frozenset({ControlRequestStatus.COMPLETED}),
        ControlRequestStatus.DELIVERING: frozenset(),
        ControlRequestStatus.COMPLETED: frozenset(),
        ControlRequestStatus.REJECTED: frozenset(),
        ControlRequestStatus.DELIVERY_UNKNOWN: frozenset(),
    },
}
_APPROVAL_TRANSITIONS: Final = {
    ApprovalStatus.PENDING: frozenset(
        {
            ApprovalStatus.APPROVED,
            ApprovalStatus.DENIED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.INVALIDATED,
        }
    ),
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.DENIED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
    ApprovalStatus.INVALIDATED: frozenset(),
}


def _require_transition[T: StrEnum](
    current: T,
    target: T,
    transitions: Mapping[T, Set[T]],
) -> None:
    if target not in transitions[current]:
        raise ConversationContractError(
            ConversationErrorCode.INVALID_STATE_TRANSITION,
            f"cannot transition {current.value} to {target.value}",
        )


def require_task_work_transition(current: TaskWorkStatus, target: TaskWorkStatus) -> None:
    _require_transition(current, target, _TASK_TRANSITIONS)


def require_turn_transition(current: TurnStatus, target: TurnStatus) -> None:
    _require_transition(current, target, _TURN_TRANSITIONS)


def require_submission_transition(
    current: TurnSubmissionStatus, target: TurnSubmissionStatus
) -> None:
    _require_transition(current, target, _SUBMISSION_TRANSITIONS)


def require_runtime_execution_transition(
    current: RuntimeExecutionStatus, target: RuntimeExecutionStatus
) -> None:
    _require_transition(current, target, _RUNTIME_EXECUTION_TRANSITIONS)


def require_control_transition(
    kind: ControlKind,
    current: ControlRequestStatus,
    target: ControlRequestStatus,
) -> None:
    _require_transition(current, target, _CONTROL_TRANSITIONS[kind])


def require_approval_transition(current: ApprovalStatus, target: ApprovalStatus) -> None:
    _require_transition(current, target, _APPROVAL_TRANSITIONS)


def require_single_active_turn(statuses: tuple[TurnStatus, ...]) -> None:
    if statuses.count(TurnStatus.IN_PROGRESS) > 1:
        raise ConversationContractError(
            ConversationErrorCode.ACTIVE_TURN_EXISTS,
            "a task cannot have more than one active turn",
        )


@dataclass(frozen=True, slots=True)
class RuntimeProjection:
    state: RuntimeProjectionState
    active_flags: tuple[RuntimeActiveFlag, ...] = ()

    def __post_init__(self) -> None:
        if self.state is not RuntimeProjectionState.ACTIVE and self.active_flags:
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "runtime flags are valid only for an active projection",
            )
        if len(set(self.active_flags)) != len(self.active_flags):
            raise ConversationContractError(
                ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                "runtime projection flags must be unique",
            )


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    capability: EngineCapability
    provider_support: CapabilitySupport
    adapter_support: CapabilitySupport


@dataclass(frozen=True, slots=True)
class TurnAcceptanceBoundary:
    driver: EngineDriver
    evidence: str
    confidence: ReceiptConfidence

    def __post_init__(self) -> None:
        if not self.evidence.strip():
            raise ValueError("turn acceptance evidence must not be empty")


_FORBIDDEN_METADATA_KEYS: Final = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "credential",
    "secret",
    "cookie",
    "provider_header",
)


@dataclass(frozen=True, slots=True)
class NativeReceiptMetadata:
    """Small sanitized attributes, never a raw provider payload."""

    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for key, value in self.attributes:
            normalized = key.strip().lower().replace("-", "_")
            if not normalized or normalized in seen:
                raise ValueError("native receipt metadata keys must be unique and non-empty")
            if any(fragment in normalized for fragment in _FORBIDDEN_METADATA_KEYS):
                raise ConversationContractError(
                    ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                    f"native receipt metadata field is prohibited: {key}",
                )
            if value.lstrip().lower().startswith("bearer "):
                raise ConversationContractError(
                    ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
                    "native receipt metadata must not contain bearer credentials",
                )
            seen.add(normalized)


@dataclass(frozen=True, slots=True)
class OpaqueNativeReference:
    provider: EngineFamily
    reference_type: str
    value: str

    def __post_init__(self) -> None:
        if not self.reference_type.strip() or not self.value.strip():
            raise ValueError("opaque native references require a type and value")


@dataclass(frozen=True, slots=True)
class NativeReceipt:
    kind: NativeReceiptKind
    task_id: str
    turn_id: str
    native_references: tuple[OpaqueNativeReference, ...] = ()
    metadata: NativeReceiptMetadata = NativeReceiptMetadata()

    def __post_init__(self) -> None:
        if not self.task_id or not self.turn_id:
            raise ValueError("native receipts require task and turn identities")


_CODEX_TURN_STATUS: Final = {
    "inProgress": TurnStatus.IN_PROGRESS,
    "completed": TurnStatus.COMPLETED,
    "interrupted": TurnStatus.INTERRUPTED,
    "failed": TurnStatus.FAILED,
}
_CODEX_RUNTIME_STATE: Final = {
    "notLoaded": RuntimeProjectionState.NOT_LOADED,
    "idle": RuntimeProjectionState.IDLE,
    "active": RuntimeProjectionState.ACTIVE,
    "systemError": RuntimeProjectionState.SYSTEM_ERROR,
}
_CODEX_ACTIVE_FLAG: Final = {
    "waitingOnApproval": RuntimeActiveFlag.WAITING_ON_APPROVAL,
    "waitingOnUserInput": RuntimeActiveFlag.WAITING_ON_USER_INPUT,
}


def _translate_provider_value[T: StrEnum](value: str, values: dict[str, T], *, contract: str) -> T:
    try:
        return values[value]
    except KeyError as error:
        raise ConversationContractError(
            ConversationErrorCode.PROVIDER_CONTRACT_MISMATCH,
            f"unknown {contract} value: {value}",
        ) from error


def translate_codex_turn_status(value: str) -> TurnStatus:
    return _translate_provider_value(value, _CODEX_TURN_STATUS, contract="Codex turn status")


def translate_codex_runtime_state(value: str) -> RuntimeProjectionState:
    return _translate_provider_value(value, _CODEX_RUNTIME_STATE, contract="Codex runtime state")


def translate_codex_active_flag(value: str) -> RuntimeActiveFlag:
    return _translate_provider_value(value, _CODEX_ACTIVE_FLAG, contract="Codex active flag")

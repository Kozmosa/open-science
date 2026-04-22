from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ainrf.terminal.models import TerminalAttachmentMode


class ManagedTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskTerminalBindingStatus(StrEnum):
    PENDING_ATTACH = "pending_attach"
    RUNNING_OBSERVE = "running_observe"
    TAKEN_OVER = "taken_over"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class TaskAgentWriteState(StrEnum):
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED_BY_USER = "paused_by_user"
    RESUME_REQUESTED = "resume_requested"


class TaskTakeoverLeaseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"


@dataclass(slots=True)
class ManagedTask:
    task_id: str
    binding_id: str
    environment_id: str
    title: str
    command: str
    working_directory: str
    status: ManagedTaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    exit_code: int | None = None
    detail: str | None = None


@dataclass(slots=True)
class TaskTerminalBinding:
    task_id: str
    binding_id: str
    environment_id: str
    agent_session_name: str
    window_id: str
    window_name: str
    binding_status: TaskTerminalBindingStatus
    mode: TerminalAttachmentMode = TerminalAttachmentMode.OBSERVE
    readonly: bool = True
    ownership_user_id: str | None = None
    agent_write_state: TaskAgentWriteState = TaskAgentWriteState.RUNNING
    pause_requested_at: datetime | None = None
    pause_acknowledged_at: datetime | None = None
    last_takeover_at: datetime | None = None
    last_output_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def status(self) -> TaskTerminalBindingStatus:
        return self.binding_status


@dataclass(slots=True)
class TaskTakeoverLease:
    lease_id: str
    task_id: str
    user_id: str
    status: TaskTakeoverLeaseStatus
    acquired_at: datetime
    released_at: datetime | None = None

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
    status: ManagedTaskStatus
    mode: TerminalAttachmentMode = TerminalAttachmentMode.OBSERVE
    readonly: bool = True
    last_output_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

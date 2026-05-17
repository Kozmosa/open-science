from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class SessionError(RuntimeError):
    """Base error for session operations."""


class SessionNotFoundError(SessionError):
    """Session not found."""


class AttemptNotFoundError(SessionError):
    """Attempt not found."""


@dataclass(slots=True)
class Session:
    id: str
    project_id: str
    title: str
    status: SessionStatus
    task_count: int
    total_duration_ms: int
    total_cost_usd: float
    created_at: str
    updated_at: str


@dataclass(slots=True)
class SessionAttempt:
    id: str
    session_id: str
    task_id: str | None
    parent_attempt_id: str | None
    attempt_seq: int
    intervention_reason: str | None
    status: AttemptStatus
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    token_usage_json: str | None
    created_at: str

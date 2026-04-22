from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class TerminalSessionStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class TerminalMuxKind(StrEnum):
    TMUX = "tmux"


@dataclass(slots=True)
class UserEnvironmentBinding:
    binding_id: str
    user_id: str
    environment_id: str
    remote_login_user: str
    default_shell: str | None
    default_workdir: str | None
    mux_kind: TerminalMuxKind = TerminalMuxKind.TMUX
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class UserSessionPair:
    binding_id: str
    personal_session_name: str
    agent_session_name: str | None = None
    personal_status: TerminalSessionStatus = TerminalSessionStatus.IDLE
    agent_status: TerminalSessionStatus | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    personal_started_at: datetime | None = None
    personal_closed_at: datetime | None = None
    last_verified_at: datetime | None = None
    last_personal_attach_at: datetime | None = None
    last_agent_attach_at: datetime | None = None
    detail: str | None = None


@dataclass(slots=True)
class TerminalSessionRecord:
    session_id: str | None
    provider: str
    target_kind: str
    status: TerminalSessionStatus
    environment_id: str | None = None
    environment_alias: str | None = None
    working_directory: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    closed_at: datetime | None = None
    terminal_ws_url: str | None = None
    detail: str | None = None
    binding_id: str | None = None
    session_name: str | None = None
    attachment_id: str | None = None
    attachment_expires_at: datetime | None = None


@dataclass(slots=True)
class TerminalAttachmentTarget:
    binding_id: str
    session_id: str
    session_name: str
    user_id: str
    environment_id: str
    environment_alias: str
    target_kind: str
    working_directory: str | None
    attach_command: tuple[str, ...]
    spawn_working_directory: Path


@dataclass(slots=True)
class TerminalAttachment:
    attachment_id: str
    token: str
    session_id: str
    binding_id: str
    session_name: str
    user_id: str
    environment_id: str
    environment_alias: str
    target_kind: str
    working_directory: str | None
    created_at: datetime
    expires_at: datetime
    attach_command: tuple[str, ...]
    spawn_working_directory: Path
    readonly: bool = False


def utc_now() -> datetime:
    return datetime.now(UTC)

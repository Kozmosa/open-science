from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ainrf.environments.models import AnthropicEnvStatus, DetectionStatus, EnvironmentAuthKind


class ApiStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class TerminalSessionStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class CodeServerLifecycleStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApiStatus
    state_root: str
    container_configured: bool
    container_health: dict[str, Any] | None = None
    detail: str | None = None


class TerminalSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    provider: str = "tmux"
    target_kind: str = "daemon-host"
    environment_id: str | None = None
    environment_alias: str | None = None
    working_directory: str | None = None
    status: TerminalSessionStatus
    created_at: str | None = None
    started_at: str | None = None
    closed_at: str | None = None
    terminal_ws_url: str | None = None
    detail: str | None = None
    binding_id: str | None = None
    session_name: str | None = None
    attachment_id: str | None = None
    attachment_expires_at: str | None = None


class CodeServerStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CodeServerLifecycleStatus
    environment_id: str | None = None
    environment_alias: str | None = None
    workspace_dir: str | None = None
    detail: str | None = None
    managed: bool = True


class ToolStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    version: str | None = None
    path: str | None = None


class EnvironmentDetectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    detected_at: datetime
    status: DetectionStatus
    summary: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ssh_ok: bool = False
    hostname: str | None = None
    os_info: str | None = None
    arch: str | None = None
    workdir_exists: bool | None = None
    python: ToolStatusResponse
    conda: ToolStatusResponse
    uv: ToolStatusResponse
    pixi: ToolStatusResponse
    torch: ToolStatusResponse
    cuda: ToolStatusResponse
    gpu_models: list[str] = Field(default_factory=list)
    gpu_count: int = 0
    claude_cli: ToolStatusResponse
    anthropic_env: AnthropicEnvStatus


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    alias: str
    display_name: str
    description: str | None = None
    is_seed: bool = False
    tags: list[str] = Field(default_factory=list)
    host: str
    port: int = 22
    user: str = "root"
    auth_kind: EnvironmentAuthKind = EnvironmentAuthKind.SSH_KEY
    identity_file: str | None = None
    proxy_jump: str | None = None
    proxy_command: str | None = None
    ssh_options: dict[str, str] = Field(default_factory=dict)
    default_workdir: str | None = None
    preferred_python: str | None = None
    preferred_env_manager: str | None = None
    preferred_runtime_notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_detection: EnvironmentDetectionResponse | None = None


class EnvironmentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EnvironmentResponse]


class ProjectEnvironmentReferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    is_default: bool = False
    override_workdir: str | None = None
    override_env_name: str | None = None
    override_env_manager: str | None = None
    override_runtime_notes: str | None = None
    updated_at: datetime | None = None


class ProjectEnvironmentReferenceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectEnvironmentReferenceResponse]


class EnvironmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str
    display_name: str
    host: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    port: int = 22
    user: str = "root"
    auth_kind: EnvironmentAuthKind = EnvironmentAuthKind.SSH_KEY
    identity_file: str | None = None
    proxy_jump: str | None = None
    proxy_command: str | None = None
    ssh_options: dict[str, str] = Field(default_factory=dict)
    default_workdir: str | None = None
    preferred_python: str | None = None
    preferred_env_manager: str | None = None
    preferred_runtime_notes: str | None = None


class EnvironmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = None
    display_name: str | None = None
    host: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    port: int | None = None
    user: str | None = None
    auth_kind: EnvironmentAuthKind | None = None
    identity_file: str | None = None
    proxy_jump: str | None = None
    proxy_command: str | None = None
    ssh_options: dict[str, str] | None = None
    default_workdir: str | None = None
    preferred_python: str | None = None
    preferred_env_manager: str | None = None
    preferred_runtime_notes: str | None = None


class ProjectEnvironmentReferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    is_default: bool = False
    override_workdir: str | None = None
    override_env_name: str | None = None
    override_env_manager: str | None = None
    override_runtime_notes: str | None = None


class ProjectEnvironmentReferenceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_default: bool | None = None
    override_workdir: str | None = None
    override_env_name: str | None = None
    override_env_manager: str | None = None
    override_runtime_notes: str | None = None


class TerminalSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str


class TerminalSessionResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    attachment_id: str | None = None


class CodeServerSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EnvironmentAuthKind(StrEnum):
    SSH_KEY = "ssh_key"
    PASSWORD = "password"
    AGENT = "agent"


class DetectionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class AnthropicEnvStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ToolStatus:
    available: bool
    version: str | None = None
    path: str | None = None


@dataclass(slots=True)
class EnvironmentRegistryEntry:
    id: str
    alias: str
    display_name: str
    description: str | None
    is_seed: bool = False
    tags: list[str] = field(default_factory=list)
    host: str = ""
    port: int = 22
    user: str = "root"
    auth_kind: EnvironmentAuthKind = EnvironmentAuthKind.SSH_KEY
    identity_file: str | None = None
    proxy_jump: str | None = None
    proxy_command: str | None = None
    ssh_options: dict[str, str] = field(default_factory=dict)
    default_workdir: str | None = None
    preferred_python: str | None = None
    preferred_env_manager: str | None = None
    preferred_runtime_notes: str | None = None
    task_harness_profile: str | None = None
    code_server_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class DetectionSnapshot:
    environment_id: str
    detected_at: datetime
    status: DetectionStatus
    summary: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ssh_ok: bool = False
    hostname: str | None = None
    os_info: str | None = None
    arch: str | None = None
    workdir_exists: bool | None = None
    python: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    conda: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    uv: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    pixi: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    torch: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    cuda: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    gpu_models: list[str] = field(default_factory=list)
    gpu_count: int = 0
    claude_cli: ToolStatus = field(default_factory=lambda: ToolStatus(available=False))
    anthropic_env: AnthropicEnvStatus = AnthropicEnvStatus.UNKNOWN


@dataclass(slots=True)
class ProjectEnvironmentReference:
    project_id: str
    environment_id: str
    is_default: bool = False
    override_workdir: str | None = None
    override_env_name: str | None = None
    override_env_manager: str | None = None
    override_runtime_notes: str | None = None
    updated_at: datetime | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)

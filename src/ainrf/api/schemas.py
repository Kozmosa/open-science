from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ainrf.environments.models import AnthropicEnvStatus, DetectionStatus, EnvironmentAuthKind
from ainrf.terminal.models import TerminalAttachmentMode


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


class TaskStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
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


class ProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    description: str | None = None
    default_workspace_id: str | None = None
    default_environment_id: str | None = None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectResponse]


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    default_workspace_id: str | None = None
    default_environment_id: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApiStatus
    state_root: str
    startup_cwd: str
    default_workspace_dir: str
    container_configured: bool
    container_health: dict[str, Any] | None = None
    runtime_readiness: dict[str, object] | None = None
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


class UserSessionPairResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    environment_id: str
    environment_alias: str | None = None
    personal_session_name: str
    agent_session_name: str | None = None
    personal_status: TerminalSessionStatus
    agent_status: TerminalSessionStatus | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_verified_at: str | None = None
    last_personal_attach_at: str | None = None
    last_agent_attach_at: str | None = None
    detail: str | None = None


class UserSessionPairListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserSessionPairResponse]


class TerminalAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: str
    terminal_ws_url: str
    expires_at: str
    binding_id: str
    session_id: str
    session_name: str
    environment_id: str
    environment_alias: str
    target_kind: str
    working_directory: str | None = None
    readonly: bool = False
    mode: TerminalAttachmentMode = TerminalAttachmentMode.WRITE
    window_id: str | None = None
    window_name: str | None = None


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
    tmux_ok: bool = False
    hostname: str | None = None
    os_info: str | None = None
    arch: str | None = None
    workdir_exists: bool | None = None
    python: ToolStatusResponse
    conda: ToolStatusResponse
    uv: ToolStatusResponse
    pixi: ToolStatusResponse
    codex: ToolStatusResponse
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
    task_harness_profile: str | None = None
    code_server_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_detection: EnvironmentDetectionResponse | None = None


class EnvironmentCodeServerInstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: EnvironmentResponse
    installed: bool
    version: str
    install_dir: str
    code_server_path: str
    execution_mode: str
    already_installed: bool
    detail: str
    terminal_session_id: str | None = None
    terminal_attachment_id: str | None = None
    terminal_ws_url: str | None = None
    terminal_attachment_expires_at: str | None = None


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
    task_harness_profile: str | None = None
    code_server_path: str | None = None


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
    task_harness_profile: str | None = None
    code_server_path: str | None = None


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


class TerminalExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    command: list[str] = Field(default_factory=list, min_length=1)
    workspace_id: str | None = None
    timeout: float = Field(default=60.0, gt=0)


class TerminalExecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stdout: str
    stderr: str
    exit_code: int
    command: str


class ResearchAgentProfileSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    label: str
    system_prompt: str | None = None
    skills: list[str] = Field(default_factory=list)
    skills_prompt: str | None = None
    settings_json: dict[str, Any] | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    default_opus_model: str | None = None
    default_sonnet_model: str | None = None
    default_haiku_model: str | None = None
    env_overrides: dict[str, str] | None = None


class TaskConfigurationSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    template_id: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    raw_prompt: str | None = None


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(default="default", min_length=1)
    workspace_id: str
    environment_id: str
    task_profile: str = Field(default="claude-code", min_length=1)
    task_input: str = Field(min_length=1)
    title: str | None = None
    execution_engine: str | None = None
    auto_connect: bool = Field(default=False)
    session_id: str | None = None
    research_agent_profile: ResearchAgentProfileSnapshotRequest | None = None
    task_configuration: TaskConfigurationSnapshotRequest | None = None


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    label: str
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str
    created_at: datetime
    updated_at: datetime


class WorkspaceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WorkspaceResponse]


class SkillItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    description: str | None = None
    inject_mode: str = "auto"
    dependencies: list[str] = Field(default_factory=list)
    package: str | None = None


class SkillListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SkillItemResponse]


class SkillDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    description: str | None = None
    version: str
    author: str
    dependencies: list[str] = Field(default_factory=list)
    inject_mode: str
    settings_fragment: dict[str, Any] = Field(default_factory=dict)
    mcp_servers: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    skill_md: str | None = None
    package: str | None = None


class SkillPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    settings_fragment: dict[str, Any] = Field(default_factory=dict)
    merged_preview: dict[str, Any] = Field(default_factory=dict)


class SkillImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., pattern="^(git|local)$")
    url: str | None = None
    local_path: str | None = None
    skill_id: str | None = None


class SkillImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    path: str


class WorkspaceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    label: str
    description: str | None = None
    default_workdir: str | None = None


class EnvironmentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    alias: str
    display_name: str
    host: str
    default_workdir: str | None = None


class TaskSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    project_id: str
    title: str
    task_profile: str
    status: TaskStatus
    workspace_summary: WorkspaceSummaryResponse
    environment_summary: EnvironmentSummaryResponse
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error_summary: str | None = None
    latest_output_seq: int = 0
    execution_engine: str = "claude-code"
    session_id: str | None = None


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskSummaryResponse]


class TaskEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    project_id: str
    source_task_id: str
    target_task_id: str
    created_at: str


class TaskEdgeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskEdgeResponse]


class TaskEdgeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_task_id: str = Field(min_length=1)
    target_task_id: str = Field(min_length=1)


class ResearchAgentProfileSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    label: str
    system_prompt: str | None = None
    skills: list[str] = Field(default_factory=list)
    skills_prompt: str | None = None
    settings_json: dict[str, Any] | None = None
    settings_artifact_path: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    mcp_servers: dict[str, Any] | None = None
    disallowed_tools: list[str] | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    default_opus_model: str | None = None
    default_sonnet_model: str | None = None
    default_haiku_model: str | None = None
    env_overrides: dict[str, str] | None = None


class TaskConfigurationSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    template_id: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    raw_prompt: str | None = None
    rendered_task_input: str


class TaskBindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: WorkspaceSummaryResponse
    environment: EnvironmentSummaryResponse
    task_profile: str
    title: str
    task_input: str
    resolved_workdir: str
    snapshot_path: str
    execution_engine: str = "claude-code"
    research_agent_profile: ResearchAgentProfileSnapshotResponse | None = None
    task_configuration: TaskConfigurationSnapshotResponse | None = None


class TaskPromptLayerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    name: str
    label: str
    content: str
    char_count: int


class TaskPromptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rendered_prompt: str
    layer_order: list[str] = Field(default_factory=list)
    layers: list[TaskPromptLayerResponse] = Field(default_factory=list)
    manifest_path: str


class TaskRuntimeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runner_kind: str | None = None
    working_directory: str | None = None
    command: list[str] = Field(default_factory=list)
    prompt_file: str | None = None
    helper_path: str | None = None
    launch_payload_path: str | None = None


class TaskResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int | None = None
    failure_category: str | None = None
    error_summary: str | None = None
    completed_at: str | None = None


class TaskDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    project_id: str
    title: str
    task_profile: str
    status: TaskStatus
    workspace_summary: WorkspaceSummaryResponse
    environment_summary: EnvironmentSummaryResponse
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error_summary: str | None = None
    latest_output_seq: int = 0
    binding: TaskBindingResponse | None = None
    prompt: TaskPromptResponse | None = None
    runtime: TaskRuntimeResponse | None = None
    result: TaskResultResponse
    execution_engine: str = "claude-code"
    research_agent_profile: ResearchAgentProfileSnapshotResponse | None = None
    task_configuration: TaskConfigurationSnapshotResponse | None = None
    session_id: str | None = None


class TaskOutputEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    seq: int
    kind: str
    content: str
    created_at: str


class TaskOutputListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskOutputEventResponse]
    next_seq: int


class CodeServerSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str


class FileEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    kind: str
    size: int | None = None
    modified_at: str | None = None


class FileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    entries: list[FileEntryResponse]


class FileReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    is_binary: bool
    size: int
    language: str | None = None
    mime_type: str | None = None


class FileUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size: int


class TaskPauseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    status: str


class TaskResumeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    status: str


class TaskPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1)


class TaskPromptSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    sequence: int


class MessageItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    content: str | dict[str, Any]
    metadata: dict[str, Any]


class TaskMessagesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[MessageItemResponse]
    has_more: bool
    next_sequence: int | None = None


# --- Skill Registry Schemas ---


class SkillRegistryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    display_name: str
    git_url: str
    installed: bool = False
    installed_count: int = 0
    has_update: bool = False
    is_dirty: bool = False
    last_sync_at: str | None = None


class SkillRegistryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SkillRegistryItemResponse]


class SkillRegistryStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    installed: bool
    installed_count: int
    last_sync_at: str | None = None
    remote_commit: str | None = None
    local_commit: str | None = None
    has_update: bool
    is_dirty: bool
    sync_in_progress: bool


class SkillRegistryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class SkillRegistryInstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    installed_count: int
    skills: list[str]


class SkillRegistryUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    updated_count: int
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


# ── Session schemas ──────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)


class SessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: str | None = None  # "active" | "completed" | "archived"


class AttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    session_id: str
    task_id: str | None = None
    parent_attempt_id: str | None = None
    attempt_seq: int
    intervention_reason: str | None = None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    token_usage_json: str | None = None
    created_at: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    title: str
    status: str
    task_count: int
    total_duration_ms: int
    total_cost_usd: float
    created_at: str
    updated_at: str


class SessionDetailResponse(SessionResponse):
    attempts: list["AttemptResponse"] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list["SessionResponse"]


class AttemptListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list["AttemptResponse"]

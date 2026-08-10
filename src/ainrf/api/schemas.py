from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ainrf.domain.conversation_contracts import ConversationTaskStatus, TaskWorkStatus
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


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None


class ComponentHealth(BaseModel):
    """Health status for a single component (database, Litefuse, etc.)."""

    model_config = ConfigDict(extra="forbid")

    status: str  # "ok" | "degraded" | "unhealthy"
    latency_ms: float | None = None
    error: str | None = None


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
    uptime_seconds: float | None = None
    checks: dict[str, ComponentHealth] | None = None


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
    task_harness_profile: str | None = None


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
    codex_base_url: str | None = None
    codex_api_key: str | None = None
    codex_model: str | None = None
    codex_app_server_command: str | None = None
    codex_approval_policy: str | None = None
    codex_config_toml: str | None = None
    codex_auth_json: str | None = None


class TaskConfigurationSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    template_id: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    raw_prompt: str | None = None


class ProjectContextDraftRequest(BaseModel):
    """Replace the editable Project Brief Draft."""

    model_config = ConfigDict(extra="forbid")

    content: str


class ProjectContextCandidateCreateRequest(BaseModel):
    """An auditable Context suggestion; it never publishes itself."""

    model_config = ConfigDict(extra="forbid")

    content: str
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    source_task_id: str = Field(min_length=1)
    source_message_start_seq: int | None = Field(default=None, ge=0)
    source_message_end_seq: int | None = Field(default=None, ge=0)
    source_output_start_seq: int | None = Field(default=None, ge=0)
    source_output_end_seq: int | None = Field(default=None, ge=0)


class ProjectContextCandidateRejectRequest(BaseModel):
    """Record why a candidate was explicitly rejected."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ProjectContextFragmentCreateRequest(BaseModel):
    """Store one immutable Context Fragment with its provenance."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1)
    content: str
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    source_version: str | None = None
    sort_order: int = 0
    byte_budget: int | None = Field(default=None, ge=0)


class TaskContextConfirmRequest(BaseModel):
    """Confirm a previously rendered Task Context update preview."""

    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(min_length=1)


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    researcher_type: Literal["vanilla", "aris-researcher"]
    harness_engine: Literal["claude-code", "agent-sdk", "codex-app-server"]
    prompt: str = Field(min_length=1)
    skills: list[str] = []
    mcp_servers: list[str] = []
    title: str | None = None


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)


class TaskMoveRequest(BaseModel):
    """Move a not-yet-started Task to a Project Context selected by the caller."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    context_version_id: str = Field(min_length=1)


class TaskForkRequest(BaseModel):
    """Fork a Task when changing its Workspace is required."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)


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
    skill_md: str | None = None
    package: str | None = None


class SkillImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., pattern="^(git|local)$")
    url: str | None = Field(default=None, min_length=1, pattern=r"^(https?|git|file)://")
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
    workspace_id: str
    environment_id: str
    researcher_type: str
    harness_engine: str
    status: ConversationTaskStatus
    work_status: TaskWorkStatus
    title: str
    prompt: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    owner_user_id: str
    archived_at: str | None = None
    archive_reason: str | None = None
    project_context_version_id: str | None = None
    latest_output_seq: int = 0
    exit_code: int | None = None
    error_summary: str | None = None
    working_directory: str | None = None
    command: list[str] = Field(default_factory=list)
    token_usage_json: str | None = None


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskSummaryResponse]
    total: int


class TaskTokenUsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_count: int
    tasks_with_usage: int
    total_tokens: int
    total_cost_usd: float
    total_duration_ms: int
    median_duration_ms: int | None = None
    top_tasks: list[dict[str, int | float | str | None]] = Field(default_factory=list)
    total: dict[str, int | float]
    by_model: dict[str, dict[str, int | float]] = Field(default_factory=dict)
    by_engine: dict[str, dict[str, int | float]] = Field(default_factory=dict)


class TurnSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str
    task_id: str
    reserved_turn_id: str
    status: str
    intent: str


class ConversationTaskMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskSummaryResponse
    submission: TurnSubmissionResponse


class TurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    allow_next_turn: bool = False
    context_snapshot_ref: str | None = Field(default=None, min_length=1)


class TurnResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    turn_id: str
    task_id: str
    turn_seq: int
    status: str


class TurnListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TurnResponse]


class TurnItemResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    item_id: str
    task_id: str
    turn_id: str
    task_item_seq: int
    turn_item_seq: int
    item_type: str
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TurnItemListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TurnItemResponse]


class TurnSteerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_turn_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TurnInterruptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_turn_id: str = Field(min_length=1)


class TurnControlResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    control_request_id: str
    task_id: str
    expected_turn_id: str
    kind: str
    status: str


class ForkPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_engine_family: Literal["codex", "claude"]
    target_project_id: str | None = None
    target_workspace_id: str | None = None
    target_harness_engine: Literal["codex-app-server", "agent-sdk", "claude-code"] | None = None
    target_title: str | None = Field(default=None, max_length=500)
    transfer_mode: Literal["selected_turns", "recent_turns", "full_transcript", "context_only"]
    transfer_range: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    disclosure: dict[str, Any] = Field(default_factory=dict)


class ForkConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_hash: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    transfer_mode: Literal["selected_turns", "recent_turns", "full_transcript", "context_only"]
    truncation_acknowledged: bool = False
    full_transcript_confirmed: bool = False


class ForkPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str
    preview_hash: str
    source_task_id: str
    source_revision: str
    source_engine_family: Literal["codex", "claude"]
    target_engine_family: Literal["codex", "claude"]
    target_project_id: str
    target_workspace_id: str
    target_harness_engine: Literal["codex-app-server", "agent-sdk", "claude-code"]
    target_title: str
    transfer_mode: Literal["selected_turns", "recent_turns", "full_transcript", "context_only"]
    truncated: bool
    expires_at: str


class ForkConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transfer_id: str
    preview_id: str
    source_task_id: str
    status: Literal["transferred"]
    target_task_id: str
    submission_id: str
    reserved_turn_id: str


class TaskRelationshipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: str
    project_id: str
    source_task_id: str
    target_task_id: str
    relationship_type: str = "related_to"
    created_at: str


class TaskRelationshipListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskRelationshipResponse]


class TaskRelationshipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_task_id: str = Field(min_length=1)
    target_task_id: str = Field(min_length=1)


class ProjectUsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    task_count: int
    attempt_count: int
    total_duration_ms: int
    total_cost_usd: float
    total_tokens: int
    by_model: dict[str, dict[str, object]] = Field(default_factory=dict)


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


class TaskHealthResponse(BaseModel):
    """Engine liveness and last-event time for a task."""

    model_config = ConfigDict(extra="forbid")
    task_id: str
    status: str
    engine_alive: bool
    last_event_at: str | None = None
    inactive_seconds: float | None = None


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
    bundled_skill_fingerprint: str | None = None
    backup_available: bool = False


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
    bundled_skill_fingerprint: str | None = None
    backup_available: bool = False


class SkillRegistryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class SkillRegistryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    git_url: str = Field(..., min_length=1)
    git_ref: str = "main"
    source_skills_path: str = "skills"
    core_skill_ids: list[str] = Field(default_factory=list)
    install_mode: str = "copy"
    enabled: bool = True


class SkillRegistryUpdateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1)
    git_url: str | None = Field(default=None, min_length=1)
    git_ref: str | None = Field(default=None, min_length=1)
    source_skills_path: str | None = Field(default=None, min_length=1)
    core_skill_ids: list[str] | None = None
    install_mode: str | None = Field(default=None, pattern="^(copy|symlink)$")
    enabled: bool | None = None


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


# ── Auth schemas ──────────────────────────────────────────


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="ASCII letters, digits, dots, underscores, hyphens only",
    )
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=4)


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    refresh_token: str
    user: dict


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class AccessTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str


class UserInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str
    display_name: str
    role: str
    status: str
    must_change_password: bool = False


# ── Admin schemas ─────────────────────────────────────────


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None  # 'active' | 'disabled'


class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=4)


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str
    display_name: str
    role: str
    status: str
    created_at: str
    last_login_at: str | None = None
    is_online: bool = False


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AdminUserResponse]


# ── Collaborator schemas ──────────────────────────────────


class ProjectMemberRequest(BaseModel):
    """Authoritative v2 Project membership and publishing capability."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["viewer", "editor"]
    can_publish: bool = False


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    username: str
    display_name: str
    role: Literal["viewer", "editor"]
    can_publish: bool


class ProjectMemberListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectMemberResponse]


# ── Environment Access schemas ────────────────────────────


class EnvironmentAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    max_concurrent_tasks: int | None = Field(default=None, ge=0)


class EnvironmentAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    username: str
    display_name: str
    max_concurrent_tasks: int | None = Field(ge=0)


class EnvironmentAccessListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EnvironmentAccessResponse]


# ── Change Password schema ──────────────────────────────────


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=4)


class WorkspaceUpdateRequest(BaseModel):
    project_id: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, min_length=1)
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str | None = Field(default=None, min_length=1)


class CodexDefaultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codex_config_toml: str | None = None
    codex_auth_json: str | None = None


class DeploymentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    short_commit: str | None = None
    committed_at: str | None = None


class SearchBackendItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    display_name: str
    description: str
    requires_mcp: bool


class SearchSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_backend: str
    available_backends: list[SearchBackendItem]
    auto_start_mcp_servers: list[str]


class SearchSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_backend: str | None = None
    auto_start_mcp_servers: list[str] | None = None


class McpServerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str


class McpServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    servers: list[McpServerSummary]


class MonitoringServiceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    display_name: str
    description: str
    url: str | None = None
    icon: str


class MonitoringSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    services: list[MonitoringServiceItem]

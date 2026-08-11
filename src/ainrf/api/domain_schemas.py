from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProjectRole = Literal["admin", "owner", "editor", "viewer"]
ContextCandidateStatus = Literal["proposed", "accepted", "rejected"]
ContextFragmentProvenanceStatus = Literal["verified", "attention_needed"]
OverviewCardSourceStatus = Literal["ok", "partial", "stale", "unavailable", "failed"]
OverviewRefreshSourceStatus = Literal["ok", "partial", "failed"]
OverviewRefreshStatus = Literal["queued", "retry_wait", "running", "succeeded", "partial", "failed"]
OverviewRefreshTrigger = Literal["manual", "scheduled", "catchup"]


class DomainParticipantReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_type: Literal["task-dispatcher"]
    ready: bool
    maintenance_active: bool
    maintenance_epoch: int | None
    stale_after_seconds: float = Field(gt=0)
    registered_participant_ids: list[str]
    active_participant_ids: list[str]
    fresh_participant_ids: list[str]
    stale_participant_ids: list[str]


class DomainOverviewPlannerReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_store_ready: bool
    planner_ready: bool
    planner_status: Literal["unavailable", "missing", "running", "stopped"]
    planner_id: str | None = None
    heartbeat_at: str | None = None
    last_schedule_at: str | None = None
    last_error: str | None = None


class DomainCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_contract_version: Literal[1, 2]
    mode: Literal["v2"]
    standard_task_create: bool
    project_context: bool
    workspace_links: bool
    task_dispatcher: DomainParticipantReadinessResponse
    literature_research_task: bool
    overview_snapshot: bool
    overview_snapshot_job_store: bool
    overview_snapshot_planner: DomainOverviewPlannerReadinessResponse


class DomainProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None


class DomainProjectCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str


class DomainWorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    canonical_path: str
    label: str


class DomainWorkspaceCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str


class DomainWorkspaceLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    workspace_id: str
    is_primary: bool
    environment_id: str
    can_execute: bool
    cannot_execute_reason: str | None = None


class DomainProjectPermissionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_edit: bool
    can_publish: bool
    can_manage_members: bool
    can_archive: bool
    can_unarchive: bool
    can_create_task: bool


class DomainPrimaryWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    label: str
    canonical_path: str
    environment_id: str
    environment_alias: str
    environment_display_name: str
    is_primary: Literal[True]
    can_execute: bool
    cannot_execute_reason: str | None = None


class DomainProjectSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    description: str | None = None
    status: Literal["active", "archived"]
    is_default: bool
    owner_user_id: str
    current_user_role: ProjectRole
    created_at: str
    updated_at: str
    recent_activity_at: str
    workspace_count: int = Field(ge=0)
    executable_workspace_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    active_task_count: int = Field(ge=0)
    running_task_count: int = Field(ge=0)
    primary_workspace: DomainPrimaryWorkspaceResponse | None = None
    attention_required: bool
    attention_reasons: list[str] = Field(default_factory=list)
    permissions: DomainProjectPermissionsResponse


class DomainProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainProjectSummaryResponse]


class DomainWorkspaceEnvironmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    alias: str
    display_name: str
    status: Literal["active", "disabled"]


class DomainWorkspaceProjectLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    project_status: Literal["active", "archived"]
    current_user_role: ProjectRole
    link_status: Literal["active", "retired"]
    is_primary: bool
    can_execute: bool
    cannot_execute_reason: str | None = None


class DomainWorkspaceGitStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["not_collected", "available", "unavailable"]
    branch: str | None = None
    is_dirty: bool | None = None
    observed_at: str | None = None


class DomainWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    label: str
    description: str | None = None
    canonical_path: str
    workspace_context: str | None = None
    status: Literal["active", "unregistered"]
    owner_user_id: str
    created_at: str
    updated_at: str
    recent_activity_at: str
    environment: DomainWorkspaceEnvironmentResponse
    project_links: list[DomainWorkspaceProjectLinkResponse] = Field(default_factory=list)
    task_count: int = Field(ge=0)
    active_task_count: int = Field(ge=0)
    can_execute: bool
    cannot_execute_reason: str | None = None
    can_manage_registry: bool
    git_status: DomainWorkspaceGitStatusResponse


class DomainWorkspaceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainWorkspaceResponse]


class DomainContextDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    fingerprint: str
    updated_by_user_id: str
    updated_at: str


class DomainContextDraftMutationResponse(DomainContextDraftResponse):
    project_id: str


class DomainContextVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_version_id: str
    project_id: str
    content: str
    fingerprint: str
    fragment_manifest: list[object]
    fragment_provenance_status: ContextFragmentProvenanceStatus
    fragment_provenance_evidence: dict[str, object]
    assembly_eligible: bool = True
    is_active: bool
    created_by_user_id: str
    created_at: str


class DomainContextVersionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainContextVersionResponse]


class DomainProjectContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    active_version: DomainContextVersionResponse | None
    draft: DomainContextDraftResponse | None


class DomainContextDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    before_context_version_id: str
    after_context_version_id: str
    diff: str


class DomainContextCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    project_id: str
    content: str
    status: ContextCandidateStatus
    created_at: str
    created_by_user_id: str | None
    source_metadata: dict[str, object]
    source_task_id: str | None
    source_message_start_seq: int | None = Field(default=None, ge=1)
    source_message_end_seq: int | None = Field(default=None, ge=1)
    source_output_start_seq: int | None = Field(default=None, ge=1)
    source_output_end_seq: int | None = Field(default=None, ge=1)
    accepted_by_user_id: str | None
    accepted_at: str | None
    rejected_by_user_id: str | None
    rejected_at: str | None
    rejection_reason: str | None


class DomainContextCandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainContextCandidateResponse]


class DomainContextCandidateAcceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: DomainContextCandidateResponse
    draft: DomainContextDraftResponse | None


class DomainTaskContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_snapshot_id: str | None
    context_version_id: str | None
    fingerprint: str | None
    content: str
    source_manifest: list[object]
    byte_budget: int | None = Field(default=None, ge=0)
    truncated: bool
    created_at: str | None = None


class DomainOverviewSourceCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["domain", "literature", "resources"]
    data: dict[str, object] | None
    data_cutoff_at: str
    source_status: OverviewCardSourceStatus
    attention_required: bool
    error_summary: str | None


class DomainOverviewDisplayCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["attention", "progress", "literature", "continue", "resources"]
    data: dict[str, object]
    data_cutoff_at: str
    source_status: OverviewCardSourceStatus
    attention_required: bool
    error_summary: str | None


class DomainOverviewSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    owner_user_id: str
    snapshot_date: str
    data_cutoff_at: str
    source_status: Literal["ok", "partial"]
    attention_required: bool
    cards: list[DomainOverviewSourceCardResponse]
    display_cards: list[DomainOverviewDisplayCardResponse] = Field(default_factory=list)
    next_scheduled_at: str | None = None
    source: Literal["control_plane_only"] = "control_plane_only"
    projects_active: int = Field(default=0, ge=0)
    tasks_by_status: dict[str, int] = Field(default_factory=dict)
    active_turns: int = Field(default=0, ge=0)


class DomainOverviewRefreshJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    owner_user_id: str
    trigger: OverviewRefreshTrigger
    scheduled_for_date: str | None
    status: OverviewRefreshStatus
    attempt_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    next_retry_at: str | None
    last_failure_at: str | None
    snapshot_id: str | None
    source_status: OverviewRefreshSourceStatus | None
    error_summary: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None

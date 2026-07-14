from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProjectRole = Literal["admin", "owner", "editor", "viewer"]


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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TaskHarnessStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskOutputKind(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"
    LIFECYCLE = "lifecycle"


@dataclass(slots=True)
class WorkspaceSummary:
    workspace_id: str
    label: str
    description: str | None
    default_workdir: str | None


@dataclass(slots=True)
class EnvironmentSummary:
    environment_id: str
    alias: str
    display_name: str
    host: str
    default_workdir: str | None


@dataclass(slots=True)
class TaskListItem:
    task_id: str
    title: str
    task_profile: str
    status: TaskHarnessStatus
    workspace_summary: WorkspaceSummary
    environment_summary: EnvironmentSummary
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None
    latest_output_seq: int


@dataclass(slots=True)
class TaskBindingSummary:
    workspace: WorkspaceSummary
    environment: EnvironmentSummary
    task_profile: str
    title: str
    task_input: str
    resolved_workdir: str
    snapshot_path: str


@dataclass(slots=True)
class TaskPromptLayer:
    position: int
    name: str
    label: str
    content: str
    char_count: int


@dataclass(slots=True)
class TaskPromptSummary:
    rendered_prompt: str
    layer_order: list[str]
    layers: list[TaskPromptLayer]
    manifest_path: str


@dataclass(slots=True)
class TaskRuntimeSummary:
    runner_kind: str | None
    working_directory: str | None
    command: list[str]
    prompt_file: str | None
    helper_path: str | None
    launch_payload_path: str | None


@dataclass(slots=True)
class TaskResultSummary:
    exit_code: int | None
    failure_category: str | None
    error_summary: str | None
    completed_at: datetime | None


@dataclass(slots=True)
class TaskDetail:
    task_id: str
    title: str
    task_profile: str
    status: TaskHarnessStatus
    workspace_summary: WorkspaceSummary
    environment_summary: EnvironmentSummary
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None
    latest_output_seq: int
    binding: TaskBindingSummary | None
    prompt: TaskPromptSummary | None
    runtime: TaskRuntimeSummary | None
    result: TaskResultSummary


@dataclass(slots=True)
class TaskOutputEvent:
    task_id: str
    seq: int
    kind: TaskOutputKind
    content: str
    created_at: datetime


@dataclass(slots=True)
class TaskOutputPage:
    items: list[TaskOutputEvent]
    next_seq: int

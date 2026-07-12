from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ainrf.harness_engine.base import HarnessEngineType


class AgenticResearcherType(StrEnum):
    VANILLA = "vanilla"
    ARIS = "aris-researcher"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    STOPPED = "stopped"
    STOPPED_BY_PROJECT_ARCHIVE = "stopped_by_project_archive"
    LAUNCH_UNKNOWN = "launch_unknown"
    STOPPED_PERMISSION_REVOKED = "stopped_permission_revoked"


@dataclass
class AgenticResearcher:
    type: AgenticResearcherType
    harness_engine: HarnessEngineType
    skills: list[str]
    mcp_servers: list[str]
    system_prompt: str | None

    @classmethod
    def vanilla(
        cls,
        engine: HarnessEngineType,
        user_skills: list[str] | None = None,
    ) -> AgenticResearcher:
        return cls(
            type=AgenticResearcherType.VANILLA,
            harness_engine=engine,
            skills=user_skills or [],
            mcp_servers=[],
            system_prompt=None,
        )

    @classmethod
    def aris(
        cls,
        engine: HarnessEngineType,
        system_prompt: str | None = None,
    ) -> AgenticResearcher:
        return cls(
            type=AgenticResearcherType.ARIS,
            harness_engine=engine,
            skills=["research-pipeline", "research-lit", "research-refine-pipeline"],
            mcp_servers=[],
            system_prompt=system_prompt,
        )


@dataclass
class Task:
    task_id: str
    project_id: str
    workspace_id: str
    environment_id: str
    researcher_type: AgenticResearcherType
    harness_engine: HarnessEngineType
    status: TaskStatus
    title: str
    prompt: str
    user_skills: list[str]
    user_mcp_servers: list[str]
    owner_user_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latest_output_seq: int = 0
    exit_code: int | None = None
    error_summary: str | None = None
    token_usage_json: str | None = None
    # Per-task credential / profile overrides — when set they take
    # precedence over tenant / container defaults via env-var injection.
    api_base_url: str | None = None
    api_key: str | None = None
    codex_base_url: str | None = None
    codex_api_key: str | None = None
    codex_model: str | None = None
    codex_app_server_command: str | None = None
    codex_approval_policy: str | None = None


@dataclass
class TaskOutputEvent:
    task_id: str
    seq: int
    kind: str
    content: str
    created_at: datetime

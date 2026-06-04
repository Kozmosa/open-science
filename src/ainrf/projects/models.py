from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    name: str
    description: str | None
    default_workspace_id: str | None
    default_environment_id: str | None
    created_at: datetime
    updated_at: datetime
    owner_user_id: str | None = None


@dataclass(slots=True)
class TaskEdgeRecord:
    edge_id: str
    project_id: str
    source_task_id: str
    target_task_id: str
    created_at: datetime

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class WorkspaceRecord:
    workspace_id: str
    label: str
    description: str | None
    default_workdir: str | None
    workspace_prompt: str
    created_at: datetime
    updated_at: datetime

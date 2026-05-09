from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SessionCheckpoint:
    version: int = 1
    task_id: str = ""
    session_id: str | None = None
    cwd: str = ""
    created_at: str = ""
    turn_count: int = 0
    total_cost_usd: float = 0.0
    pending_prompts: list[str] | None = None


class SessionStateStore:
    def __init__(self, state_root: Path) -> None:
        self._root = state_root / "session-states"

    def _checkpoint_path(self, task_id: str) -> Path:
        return self._root / task_id / "checkpoint.json"

    def save(self, checkpoint: SessionCheckpoint) -> None:
        path = self._checkpoint_path(checkpoint.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(checkpoint), indent=2))

    def load(self, task_id: str) -> SessionCheckpoint | None:
        path = self._checkpoint_path(task_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return SessionCheckpoint(**data)

    def checkpoint_path(self, task_id: str) -> Path:
        return self._checkpoint_path(task_id)

    def delete(self, task_id: str) -> None:
        path = self._checkpoint_path(task_id)
        if path.exists():
            path.unlink()

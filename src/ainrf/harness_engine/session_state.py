from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class SessionCheckpoint:
    version: int = 1
    task_id: str = ""
    session_id: str | None = None
    cwd: str = ""
    created_at: str = ""
    turn_count: int = 0
    total_cost_usd: float = 0.0
    pending_prompts: list[str] | None = None
    metadata: dict[str, object] | None = None


class SessionStateStore:
    def __init__(self, state_root: Path) -> None:
        self._root = state_root / "session-states"

    def checkpoint_path(self, task_id: str) -> Path:
        return self._root / task_id / "checkpoint.json"

    def save(self, checkpoint: SessionCheckpoint) -> None:
        from ainrf.db.connection import atomic_write_json

        path = self.checkpoint_path(checkpoint.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, asdict(checkpoint))

    def load(self, task_id: str) -> SessionCheckpoint | None:
        path = self.checkpoint_path(task_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionCheckpoint(**data)

    def delete(self, task_id: str) -> None:
        path = self.checkpoint_path(task_id)
        if path.exists():
            path.unlink()

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class SessionCheckpoint:
    version: int = 2
    task_id: str = ""
    # A v2 Task can have multiple Attempts.  These fields bind a checkpoint
    # to the one durable launch that wrote it instead of letting a retry
    # accidentally resume another Attempt's external session.
    attempt_id: str | None = None
    runtime_launch_key: str | None = None
    session_id: str | None = None
    cwd: str = ""
    created_at: str = ""
    turn_count: int = 0
    total_cost_usd: float = 0.0
    pending_prompts: list[str] | None = None
    metadata: dict[str, object] | None = None

    def assert_matches_runtime(
        self,
        *,
        task_id: str,
        attempt_id: str | None,
        runtime_launch_key: str | None,
    ) -> None:
        """Reject a v2 checkpoint that belongs to another runtime identity.

        Legacy callers deliberately omit ``runtime_launch_key`` and retain
        their historical task-scoped checkpoint behavior.  A durable context,
        however, must have both an Attempt and launch key and may only restore
        a checkpoint written by that exact pair.
        """

        if runtime_launch_key is None:
            return
        if attempt_id is None:
            raise ValueError("Durable runtime checkpoint validation requires an attempt ID")
        if (
            self.task_id != task_id
            or self.attempt_id != attempt_id
            or self.runtime_launch_key != runtime_launch_key
        ):
            raise ValueError("Checkpoint runtime identity does not match this durable Attempt")


class SessionStateStore:
    def __init__(self, state_root: Path) -> None:
        self._root = state_root / "session-states"

    def checkpoint_path(self, task_id: str, *, attempt_id: str | None = None) -> Path:
        """Return the legacy Task or durable Attempt checkpoint path."""

        identity = attempt_id or task_id
        return self._root / identity / "checkpoint.json"

    def save(self, checkpoint: SessionCheckpoint) -> None:
        from ainrf.db.connection import atomic_write_json

        path = self.checkpoint_path(checkpoint.task_id, attempt_id=checkpoint.attempt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, asdict(checkpoint))

    def load(self, task_id: str, *, attempt_id: str | None = None) -> SessionCheckpoint | None:
        path = self.checkpoint_path(task_id, attempt_id=attempt_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionCheckpoint(**data)

    def delete(self, task_id: str, *, attempt_id: str | None = None) -> None:
        path = self.checkpoint_path(task_id, attempt_id=attempt_id)
        if path.exists():
            path.unlink()

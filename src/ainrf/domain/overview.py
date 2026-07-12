"""Persisted, read-only Today overview snapshots."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OverviewSnapshotService:
    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def refresh(self, owner_user_id: str) -> dict[str, object]:
        """Aggregate only local control-plane rows; never calls external services."""
        now = _now()
        day = now.date().isoformat()
        with closing(self._connect()) as conn:
            projects = int(
                conn.execute(
                    "SELECT COUNT(*) FROM projects WHERE owner_user_id = ? AND status = 'active'",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            task_statuses = {
                str(row["status"]): int(row["count"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM tasks WHERE owner_user_id = ? GROUP BY status",
                    (owner_user_id,),
                )
            }
            attempts = int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_task_attempts a JOIN tasks t ON t.task_id = a.task_id WHERE t.owner_user_id = ? AND a.status IN ('queued', 'starting', 'running')",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            payload: dict[str, object] = {
                "snapshot_date": day,
                "projects_active": projects,
                "tasks_by_status": task_statuses,
                "active_attempts": attempts,
                "source": "control_plane_only",
            }
            conn.execute(
                "INSERT INTO overview_snapshots(snapshot_id, owner_user_id, snapshot_date, payload_json, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(owner_user_id, snapshot_date) DO UPDATE SET payload_json = excluded.payload_json, created_at = excluded.created_at",
                (
                    f"overview-{uuid4().hex}",
                    owner_user_id,
                    day,
                    json.dumps(payload, sort_keys=True),
                    now.isoformat(),
                ),
            )
            conn.commit()
            return payload

    def latest(self, owner_user_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM overview_snapshots WHERE owner_user_id = ? ORDER BY snapshot_date DESC LIMIT 1",
                (owner_user_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

"""Recoverable Literature-to-standard-Task coordination service."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain import TaskApplicationService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiteratureTaskSagaService:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "literature.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "literature")
        self._tasks = TaskApplicationService(state_root)

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def convert(
        self,
        user: dict[str, object],
        *,
        paper_id: str,
        subscription_id: str,
        project_id: str,
        workspace_id: str,
    ) -> dict[str, str]:
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Authenticated user ID is required")
        with closing(self._connect()) as conn:
            paper = conn.execute(
                """SELECT p.title, p.abstract FROM literature_papers p
                   JOIN literature_subscription_papers sp ON sp.paper_id = p.paper_id
                   JOIN literature_subscriptions s ON s.subscription_id = sp.subscription_id
                   WHERE p.paper_id = ? AND sp.subscription_id = ? AND s.user_id = ?""",
                (paper_id, subscription_id, user_id),
            ).fetchone()
            if paper is None:
                raise LookupError("Paper not found")
            existing = conn.execute(
                "SELECT * FROM literature_task_sagas WHERE subscription_id = ? AND paper_id = ? AND project_id = ? AND workspace_id = ?",
                (subscription_id, paper_id, project_id, workspace_id),
            ).fetchone()
            if existing is None:
                saga_id = f"literature-saga-{uuid4().hex}"
                key = f"literature:{subscription_id}:{paper_id}:{project_id}:{workspace_id}"
                conn.execute(
                    "INSERT INTO literature_task_sagas(saga_id, subscription_id, paper_id, user_id, project_id, workspace_id, status, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                    (
                        saga_id,
                        subscription_id,
                        paper_id,
                        user_id,
                        project_id,
                        workspace_id,
                        key,
                        _now(),
                        _now(),
                    ),
                )
                conn.commit()
                existing = conn.execute(
                    "SELECT * FROM literature_task_sagas WHERE saga_id = ?", (saga_id,)
                ).fetchone()
            assert existing is not None
        try:
            task = self._tasks.create_task(
                user,
                project_id=project_id,
                workspace_id=workspace_id,
                title=f"Literature: {paper['title']}",
                prompt=f"Review and extend this paper.\n\nTitle: {paper['title']}\n\nAbstract:\n{paper['abstract']}",
                researcher_type="vanilla",
                harness_engine="claude-code",
                idempotency_key=str(existing["idempotency_key"]),
            )
        except Exception as exc:
            with closing(self._connect()) as conn:
                conn.execute(
                    "UPDATE literature_task_sagas SET status = 'failed', error_detail = ?, updated_at = ? WHERE saga_id = ?",
                    (str(exc), _now(), existing["saga_id"]),
                )
                conn.commit()
            raise
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE literature_task_sagas SET task_id = ?, status = 'task_created', error_detail = NULL, updated_at = ? WHERE saga_id = ?",
                (task["task_id"], _now(), existing["saga_id"]),
            )
            conn.execute(
                "UPDATE literature_subscription_papers SET is_converted_to_task = 1, task_id = ? WHERE subscription_id = ? AND paper_id = ?",
                (task["task_id"], subscription_id, paper_id),
            )
            conn.execute(
                "UPDATE literature_task_sagas SET status = 'completed', updated_at = ? WHERE saga_id = ?",
                (_now(), existing["saga_id"]),
            )
            conn.commit()
        return {"saga_id": str(existing["saga_id"]), "task_id": task["task_id"]}

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.agentic_researcher.models import (
    AgenticResearcher,
    AgenticResearcherType,
    HarnessEngineType,
    Task,
    TaskStatus,
)


class TaskNotFoundError(LookupError):
    pass


class TaskOperationError(RuntimeError):
    pass


class AgenticResearcherService:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    researcher_type TEXT NOT NULL,
                    harness_engine TEXT NOT NULL,
                    user_skills TEXT,
                    user_mcp_servers TEXT,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    owner_user_id TEXT NOT NULL,
                    exit_code INTEGER,
                    error_summary TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_outputs (
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self) -> str:
        return uuid4().hex[:12]

    def create_task(
        self,
        project_id: str,
        workspace_id: str,
        environment_id: str,
        researcher: AgenticResearcher,
        prompt: str,
        owner_user_id: str,
        title: str | None = None,
    ) -> Task:
        task_id = self._new_id()
        now = self._now()
        task = Task(
            task_id=task_id,
            project_id=project_id,
            workspace_id=workspace_id,
            environment_id=environment_id,
            researcher_type=researcher.type,
            harness_engine=researcher.harness_engine,
            status=TaskStatus.PENDING,
            title=title or f"Task {task_id}",
            prompt=prompt,
            user_skills=researcher.skills,
            user_mcp_servers=researcher.mcp_servers,
            owner_user_id=owner_user_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, workspace_id, environment_id,
                    researcher_type, harness_engine, user_skills, user_mcp_servers,
                    status, title, prompt, created_at, updated_at, owner_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id, task.project_id, task.workspace_id, task.environment_id,
                    task.researcher_type.value, task.harness_engine.value,
                    json.dumps(task.user_skills), json.dumps(task.user_mcp_servers),
                    task.status.value, task.title, task.prompt,
                    now, now, task.owner_user_id,
                ),
            )
        return task

    def get_task(self, task_id: str) -> Task:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self._row_to_task(row)

    def list_tasks(self, project_id: str | None = None, user_id: str | None = None) -> list[Task]:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if user_id:
            query += " AND owner_user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def cancel_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskOperationError(f"Cannot cancel task with status: {task.status}")
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ? WHERE task_id = ?",
                (TaskStatus.CANCELLED.value, now, now, task_id),
            )
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.fromisoformat(now)
        task.completed_at = datetime.fromisoformat(now)
        return task

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            environment_id=row["environment_id"],
            researcher_type=AgenticResearcherType(row["researcher_type"]),
            harness_engine=HarnessEngineType(row["harness_engine"]),
            status=TaskStatus(row["status"]),
            title=row["title"],
            prompt=row["prompt"],
            user_skills=json.loads(row["user_skills"] or "[]"),
            user_mcp_servers=json.loads(row["user_mcp_servers"] or "[]"),
            owner_user_id=row["owner_user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            exit_code=row["exit_code"],
            error_summary=row["error_summary"],
        )

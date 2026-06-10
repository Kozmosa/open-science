from __future__ import annotations

import asyncio
import json
import shlex
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ainrf.agentic_researcher.models import (
    AgenticResearcher,
    AgenticResearcherType,
    HarnessEngineType,
    Task,
    TaskOutputEvent,
    TaskStatus,
)
from ainrf.harness_engine import EngineEvent, ExecutionContext, get_engine
from ainrf.harness_engine.base import HarnessEngine
from ainrf.workspaces.service import WorkspaceNotFoundError

if TYPE_CHECKING:
    from ainrf.workspaces import WorkspaceRegistryService


class TaskNotFoundError(LookupError):
    pass


class TaskOperationError(RuntimeError):
    pass


TOKEN_TOTAL_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _number(value: object) -> float:
    return value if isinstance(value, int | float) else 0.0


def _int_number(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _empty_token_summary() -> dict:
    return {
        "task_count": 0,
        "tasks_with_usage": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "total_duration_ms": 0,
        "median_duration_ms": None,
        "top_tasks": [],
        "total": {field: 0 for field in TOKEN_TOTAL_FIELDS} | {"cost_usd": 0.0},
        "by_model": {},
        "by_engine": {},
    }


def _token_total(total: dict) -> int:
    return sum(_int_number(total.get(field)) for field in TOKEN_TOTAL_FIELDS)


def _duration_ms(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(completed_at)
    duration = int((end - start).total_seconds() * 1000)
    return max(duration, 0)


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _normalize_token_usage(usage: dict) -> dict:
    normalized_total: dict[str, int | float] = {
        field: _int_number(usage.get("total", {}).get(field)) for field in TOKEN_TOTAL_FIELDS
    }
    normalized_total["cost_usd"] = _number(usage.get("total", {}).get("cost_usd"))
    normalized = {
        "source": usage.get("source", "unknown"),
        "total": normalized_total,
    }
    by_model = usage.get("by_model")
    if isinstance(by_model, dict) and by_model:
        normalized["by_model"] = {
            str(model): {field: _int_number(model_usage.get(field)) for field in TOKEN_TOTAL_FIELDS}
            | {"cost_usd": _number(model_usage.get("cost_usd"))}
            for model, model_usage in by_model.items()
            if isinstance(model_usage, dict)
        }
    return normalized


def _add_token_totals(target: dict, incoming: dict) -> None:
    for field in TOKEN_TOTAL_FIELDS:
        target[field] = _int_number(target.get(field)) + _int_number(incoming.get(field))
    target["cost_usd"] = _number(target.get("cost_usd")) + _number(incoming.get("cost_usd"))


def _add_model_usage(target: dict, incoming: dict) -> None:
    if not isinstance(incoming, dict):
        return
    for model, model_usage in incoming.items():
        if not isinstance(model_usage, dict):
            continue
        current = target.setdefault(
            str(model),
            {field: 0 for field in TOKEN_TOTAL_FIELDS} | {"cost_usd": 0.0, "tokens": 0},
        )
        _add_token_totals(current, model_usage)
        current["tokens"] = _token_total(current)


def _merge_token_usage(current: dict, incoming: dict) -> dict:
    merged = _normalize_token_usage(current)
    normalized_incoming = _normalize_token_usage(incoming)
    _add_token_totals(merged["total"], normalized_incoming.get("total", {}))
    by_model: dict = dict(merged.get("by_model", {}))
    _add_model_usage(by_model, normalized_incoming.get("by_model", {}))
    if by_model:
        merged["by_model"] = by_model
    return merged


class AgenticResearcherService:
    def __init__(
        self,
        state_root: Path,
        *,
        workspace_service: WorkspaceRegistryService | None = None,
        engine_factory: Callable[[str], HarnessEngine] = get_engine,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._workspace_service = workspace_service
        self._engine_factory = engine_factory
        self._engines: dict[HarnessEngineType, HarnessEngine] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
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
                    latest_output_seq INTEGER NOT NULL DEFAULT 0,
                    owner_user_id TEXT NOT NULL,
                    exit_code INTEGER,
                    error_summary TEXT,
                    token_usage_json TEXT
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
            self._ensure_column(
                conn,
                "tasks",
                "latest_output_seq",
                "ALTER TABLE tasks ADD COLUMN latest_output_seq INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                "tasks",
                "token_usage_json",
                "ALTER TABLE tasks ADD COLUMN token_usage_json TEXT",
            )
            self._migrate_legacy_task_statuses(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.commit()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        ddl: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in columns:
            conn.execute(ddl)

    def _migrate_legacy_task_statuses(self, conn: sqlite3.Connection) -> None:
        legacy_statuses = {
            "pending": TaskStatus.QUEUED.value,
            "canceled": TaskStatus.CANCELLED.value,
        }
        for legacy, current in legacy_statuses.items():
            conn.execute(
                "UPDATE tasks SET status = ? WHERE status = ?",
                (current, legacy),
            )

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
            status=TaskStatus.QUEUED,
            title=title or f"Task {task_id}",
            prompt=prompt,
            user_skills=researcher.skills,
            user_mcp_servers=researcher.mcp_servers,
            owner_user_id=owner_user_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, workspace_id, environment_id,
                    researcher_type, harness_engine, user_skills, user_mcp_servers,
                    status, title, prompt, created_at, updated_at, owner_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.project_id,
                    task.workspace_id,
                    task.environment_id,
                    task.researcher_type.value,
                    task.harness_engine.value,
                    json.dumps(task.user_skills),
                    json.dumps(task.user_mcp_servers),
                    task.status.value,
                    task.title,
                    task.prompt,
                    now,
                    now,
                    task.owner_user_id,
                ),
            )
            conn.commit()
        return task

    def schedule_task(self, task_id: str) -> None:
        if task_id in self._running_tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise TaskOperationError("Task execution requires an active event loop") from exc
        self._running_tasks[task_id] = loop.create_task(self.run_task(task_id))

    async def run_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != TaskStatus.QUEUED:
            raise TaskOperationError(f"Cannot run task with status: {task.status}")

        try:
            await self._set_status(task_id, TaskStatus.STARTING, started=True)
            context = self._build_execution_context(task)
            engine = self._get_engine(task.harness_engine)
            await self._set_status(task_id, TaskStatus.RUNNING)
            latest = self.get_task(task_id)
            if latest.latest_output_seq == 0:
                await self.append_output(
                    task_id,
                    "message",
                    json.dumps({"role": "user", "content": task.prompt}, ensure_ascii=True),
                )
            await engine.start(context, lambda event: self._handle_engine_event(task_id, event))
            latest = self.get_task(task_id)
            if latest.status in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                await self._set_status(task_id, TaskStatus.SUCCEEDED, completed=True, exit_code=0)
        except asyncio.CancelledError:
            await self._set_status(task_id, TaskStatus.CANCELLED, completed=True)
            raise
        except Exception as exc:
            await self.append_output(task_id, "stderr", str(exc))
            await self._set_status(
                task_id,
                TaskStatus.FAILED,
                completed=True,
                error_summary=str(exc),
            )
        finally:
            self._running_tasks.pop(task_id, None)

    async def pause_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status not in {TaskStatus.STARTING, TaskStatus.RUNNING}:
            raise TaskOperationError(f"Cannot pause task with status: {task.status}")
        engine = self._get_engine(task.harness_engine)
        try:
            await engine.pause(task_id)
        except Exception as exc:
            raise TaskOperationError(str(exc)) from exc
        return self.get_task(task_id)

    async def resume_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status != TaskStatus.PAUSED:
            raise TaskOperationError(f"Cannot resume task with status: {task.status}")
        self._mark_task_queued_for_rerun(task_id)
        self.schedule_task(task_id)
        return self.get_task(task_id)

    async def send_prompt(self, task_id: str, prompt: str) -> TaskOutputEvent:
        task = self.get_task(task_id)
        if task.status not in {TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.SUCCEEDED}:
            raise TaskOperationError(f"Cannot send prompt to task with status: {task.status}")
        engine = self._get_engine(task.harness_engine)
        try:
            await engine.send_input(task_id, prompt)
        except Exception as exc:
            raise TaskOperationError(str(exc)) from exc
        event = await self.append_output(
            task_id,
            "message",
            json.dumps({"role": "user", "content": prompt}, ensure_ascii=True),
        )
        if task.status in {TaskStatus.PAUSED, TaskStatus.SUCCEEDED}:
            self._mark_task_queued_for_rerun(task_id)
            self.schedule_task(task_id)
        return event

    def get_output(
        self, task_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[TaskOutputEvent]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_outputs
                WHERE task_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (task_id, after_seq, limit),
            ).fetchall()
        return [
            TaskOutputEvent(
                task_id=row["task_id"],
                seq=row["seq"],
                kind=row["kind"],
                content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def append_output(self, task_id: str, kind: str, content: str) -> TaskOutputEvent:
        return await asyncio.to_thread(self._append_output_sync, task_id, kind, content)

    def _append_output_sync(self, task_id: str, kind: str, content: str) -> TaskOutputEvent:
        now = self._now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT latest_output_seq FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            seq = int(row["latest_output_seq"]) + 1
            conn.execute(
                """
                INSERT INTO task_outputs (task_id, seq, kind, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, seq, kind, content, now),
            )
            conn.execute(
                "UPDATE tasks SET latest_output_seq = ?, updated_at = ? WHERE task_id = ?",
                (seq, now, task_id),
            )
            conn.commit()
        return TaskOutputEvent(
            task_id=task_id,
            seq=seq,
            kind=kind,
            content=content,
            created_at=datetime.fromisoformat(now),
        )

    def get_task(self, task_id: str) -> Task:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self._row_to_task(row)

    def list_tasks(
        self,
        project_id: str | None = None,
        user_id: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
        sort: str = "updated",
    ) -> list[Task]:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if user_id:
            query += " AND owner_user_id = ?"
            params.append(user_id)
        if not include_archived:
            # Exclude CANCELLED status as the closest equivalent to "archived"
            query += " AND status != ?"
            params.append(TaskStatus.CANCELLED.value)

        order_col = "updated_at" if sort == "updated" else "created_at"
        query += f" ORDER BY {order_col} DESC"
        query += " LIMIT ?"
        params.append(limit)

        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def token_usage_summary(
        self,
        *,
        user_id: str | None = None,
        include_archived: bool = True,
    ) -> dict:
        query = """
            SELECT task_id, title, harness_engine, status, started_at, completed_at, token_usage_json
            FROM tasks
            WHERE 1=1
        """
        params: list[object] = []
        if user_id:
            query += " AND owner_user_id = ?"
            params.append(user_id)
        if not include_archived:
            query += " AND status != ?"
            params.append(TaskStatus.CANCELLED.value)

        summary = _empty_token_summary()
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()

        summary["task_count"] = len(rows)
        durations: list[int] = []
        top_tasks: list[dict] = []
        for row in rows:
            duration_ms = _duration_ms(row["started_at"], row["completed_at"])
            if duration_ms is not None:
                durations.append(duration_ms)
                summary["total_duration_ms"] += duration_ms

            usage_json = row["token_usage_json"]
            engine = row["harness_engine"]
            by_engine = summary["by_engine"].setdefault(
                engine,
                {"task_count": 0, "tasks_with_usage": 0, "tokens": 0, "cost_usd": 0.0},
            )
            by_engine["task_count"] += 1
            if not usage_json:
                continue
            try:
                usage = json.loads(usage_json)
            except json.JSONDecodeError:
                continue
            tokens = _token_total(usage.get("total", {}))
            cost = _number(usage.get("total", {}).get("cost_usd"))
            summary["tasks_with_usage"] += 1
            summary["total_tokens"] += tokens
            summary["total_cost_usd"] += cost
            by_engine["tasks_with_usage"] += 1
            by_engine["tokens"] += tokens
            by_engine["cost_usd"] += cost
            _add_token_totals(summary["total"], usage.get("total", {}))
            _add_model_usage(summary["by_model"], usage.get("by_model", {}))
            if tokens > 0:
                top_tasks.append(
                    {
                        "task_id": row["task_id"],
                        "title": row["title"],
                        "status": row["status"],
                        "harness_engine": engine,
                        "total_tokens": tokens,
                        "cost_usd": round(cost, 6),
                        "duration_ms": duration_ms,
                    }
                )

        summary["median_duration_ms"] = _median(durations)
        summary["top_tasks"] = sorted(
            top_tasks,
            key=lambda item: item["total_tokens"],
            reverse=True,
        )[:5]

        summary["total_cost_usd"] = round(summary["total_cost_usd"], 6)
        summary["total"]["cost_usd"] = round(summary["total"].get("cost_usd", 0.0), 6)
        for engine_usage in summary["by_engine"].values():
            engine_usage["cost_usd"] = round(engine_usage["cost_usd"], 6)
        for model_usage in summary["by_model"].values():
            model_usage["cost_usd"] = round(model_usage["cost_usd"], 6)
        return summary

    def cancel_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status not in {TaskStatus.QUEUED, TaskStatus.STARTING, TaskStatus.RUNNING}:
            raise TaskOperationError(f"Cannot cancel task with status: {task.status}")
        now = self._now()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ? WHERE task_id = ?",
                (TaskStatus.CANCELLED.value, now, now, task_id),
            )
            conn.commit()
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.fromisoformat(now)
        task.completed_at = datetime.fromisoformat(now)
        return task

    def archive_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status in {TaskStatus.QUEUED, TaskStatus.STARTING, TaskStatus.RUNNING}:
            raise TaskOperationError(f"Cannot archive active task with status: {task.status}")
        if task.status == TaskStatus.CANCELLED:
            return task
        now = self._now()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (TaskStatus.CANCELLED.value, now, task_id),
            )
            conn.commit()
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.fromisoformat(now)
        return task

    async def cancel_running_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status == TaskStatus.RUNNING:
            engine = self._get_engine(task.harness_engine)
            await engine.cancel(task_id)
        running_task = self._running_tasks.get(task_id)
        if running_task is not None:
            running_task.cancel()
        return self.cancel_task(task_id)

    def _mark_task_queued_for_rerun(self, task_id: str) -> None:
        now = self._now()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, completed_at = NULL,
                    exit_code = NULL, error_summary = NULL
                WHERE task_id = ?
                """,
                (TaskStatus.QUEUED.value, now, task_id),
            )
            conn.commit()

    def delete_task(self, task_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_outputs WHERE task_id = ?", (task_id,))
            conn.commit()

    def retry_task(self, task_id: str) -> Task:
        old = self.get_task(task_id)
        if old.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise TaskOperationError(f"Cannot retry task with status: {old.status}")
        researcher = AgenticResearcher(
            type=old.researcher_type,
            harness_engine=old.harness_engine,
            skills=old.user_skills,
            mcp_servers=old.user_mcp_servers,
            system_prompt=None,
        )
        return self.create_task(
            project_id=old.project_id,
            workspace_id=old.workspace_id,
            environment_id=old.environment_id,
            researcher=researcher,
            prompt=old.prompt,
            owner_user_id=old.owner_user_id,
            title=f"Retry: {old.title}",
        )

    def _build_execution_context(self, task: Task) -> ExecutionContext:
        working_directory = self._resolve_working_directory(task)
        return ExecutionContext(
            task_id=task.task_id,
            working_directory=str(working_directory),
            rendered_prompt=task.prompt,
            researcher_type=task.researcher_type.value,
            engine_type=task.harness_engine,
            skills=task.user_skills,
            mcp_servers=task.user_mcp_servers,
            session_state_path=str(
                self._runtime_root / "session-states" / task.task_id / "checkpoint.json"
            ),
        )

    def get_runtime_summary(self, task: Task) -> dict[str, object]:
        context = self._build_execution_context(task)
        command = self._runtime_command(context)
        return {
            "working_directory": context.working_directory,
            "command": command,
        }

    def _runtime_command(self, context: ExecutionContext) -> list[str]:
        if context.engine_type == HarnessEngineType.CLAUDE_CODE:
            return [
                "claude",
                "-p",
                "--no-session-persistence",
                "--permission-mode",
                "bypassPermissions",
            ]
        if context.engine_type == HarnessEngineType.CODEX_APP_SERVER:
            command_text = context.codex_app_server_command or "codex app-server --listen stdio://"
            return shlex.split(command_text)
        return ["claude-agent-sdk", "query"]

    def _resolve_working_directory(self, task: Task) -> Path:
        if self._workspace_service is not None:
            try:
                workspace = self._workspace_service.get_workspace(task.workspace_id)
            except WorkspaceNotFoundError:
                workspace = None
            if workspace is not None and workspace.default_workdir:
                path = Path(workspace.default_workdir).expanduser().resolve()
                path.mkdir(parents=True, exist_ok=True)
                return path
        fallback = self._state_root / "workspace" / task.workspace_id
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _get_engine(self, engine_type: HarnessEngineType) -> HarnessEngine:
        engine = self._engines.get(engine_type)
        if engine is None:
            engine = self._engine_factory(engine_type.value)
            self._engines[engine_type] = engine
        return engine

    async def _handle_engine_event(self, task_id: str, event: EngineEvent) -> None:
        kind = "lifecycle" if event.event_type in {"status", "system"} else event.event_type
        content = self._event_content(event)
        await self.append_output(task_id, kind, content)
        if event.token_usage:
            await self._record_token_usage(
                task_id, event.token_usage, replace=event.event_type != "token"
            )
        if event.event_type == "status":
            status = event.payload.get("status")
            exit_code = event.payload.get("exit_code")
            if status == "succeeded":
                await self._set_status(
                    task_id,
                    TaskStatus.SUCCEEDED,
                    completed=True,
                    exit_code=exit_code if isinstance(exit_code, int) else 0,
                )
            elif status == "failed":
                await self._set_status(
                    task_id,
                    TaskStatus.FAILED,
                    completed=True,
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                )
        elif event.event_type == "system":
            subtype = event.payload.get("subtype")
            if subtype == "task_paused":
                await self._set_status(task_id, TaskStatus.PAUSED)
            elif subtype == "task_failed":
                await self._set_status(task_id, TaskStatus.FAILED, completed=True)
            elif subtype == "task_completed":
                latest = self.get_task(task_id)
                if latest.status in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                    await self._set_status(
                        task_id,
                        TaskStatus.SUCCEEDED,
                        completed=True,
                        exit_code=0,
                    )

    async def _record_token_usage(self, task_id: str, usage: dict, *, replace: bool) -> None:
        await asyncio.to_thread(self._record_token_usage_sync, task_id, usage, replace)

    def _record_token_usage_sync(self, task_id: str, usage: dict, replace: bool) -> None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT token_usage_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            current = None
            if row["token_usage_json"]:
                try:
                    current = json.loads(row["token_usage_json"])
                except json.JSONDecodeError:
                    current = None
            merged = (
                _normalize_token_usage(usage)
                if replace or current is None
                else _merge_token_usage(current, usage)
            )
            conn.execute(
                "UPDATE tasks SET token_usage_json = ?, updated_at = ? WHERE task_id = ?",
                (json.dumps(merged, ensure_ascii=True), self._now(), task_id),
            )
            conn.commit()

    def _event_content(self, event: EngineEvent) -> str:
        if event.event_type in {"message", "thinking", "tool_call", "tool_result"}:
            return json.dumps(event.payload, ensure_ascii=True)
        content = event.payload.get("content")
        if content is None:
            content = event.payload.get("message")
        if isinstance(content, str):
            return content
        return json.dumps(
            {
                "event_type": event.event_type,
                "payload": event.payload,
                "token_usage": event.token_usage,
            },
            ensure_ascii=True,
        )

    async def _set_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        started: bool = False,
        completed: bool = False,
        exit_code: int | None = None,
        error_summary: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._set_status_sync,
            task_id,
            status,
            started,
            completed,
            exit_code,
            error_summary,
        )

    def _set_status_sync(
        self,
        task_id: str,
        status: TaskStatus,
        started: bool,
        completed: bool,
        exit_code: int | None,
        error_summary: str | None,
    ) -> None:
        now = self._now()
        assignments = ["status = ?", "updated_at = ?"]
        params: list[object] = [status.value, now]
        if started:
            assignments.append("started_at = ?")
            params.append(now)
        if completed:
            assignments.append("completed_at = ?")
            params.append(now)
        if exit_code is not None:
            assignments.append("exit_code = ?")
            params.append(exit_code)
        if error_summary is not None:
            assignments.append("error_summary = ?")
            params.append(error_summary)
        params.append(task_id)
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?",
                params,
            )
            conn.commit()

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
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"]
            else None,
            latest_output_seq=row["latest_output_seq"],
            exit_code=row["exit_code"],
            error_summary=row["error_summary"],
            token_usage_json=row["token_usage_json"],
        )

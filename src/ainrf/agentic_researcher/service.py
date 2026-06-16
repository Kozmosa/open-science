from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import subprocess
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from ainrf.auth.service import AuthService
from ainrf.agentic_researcher.models import (
    AgenticResearcher,
    AgenticResearcherType,
    HarnessEngineType,
    Task,
    TaskOutputEvent,
    TaskStatus,
)
from ainrf.harness_engine import EngineEvent, ExecutionContext, get_engine
from ainrf.harness_engine.mcp_servers import resolve_mcp_servers_for_task
from ainrf.harness_engine.base import HarnessEngine
from ainrf.workspaces.service import WorkspaceNotFoundError

from ainrf.observability.protocol import NullReporter, ObservabilityReporter

if TYPE_CHECKING:
    from ainrf.workspaces import WorkspaceRegistryService

_LOG = structlog.get_logger(__name__).bind(component="agentic_researcher")


class TaskNotFoundError(LookupError):
    pass


class TaskOperationError(RuntimeError):
    pass


_DEFAULT_ENGINE_INACTIVITY_TIMEOUT_SECONDS = 600


def _col(row: sqlite3.Row, name: str) -> str | None:
    """Return *row[name]* or ``None`` when the column doesn't exist yet.

    Used for backward-compatible reads of columns added by later migrations.
    """
    try:
        val = row[name]
    except IndexError:
        return None
    return val if val else None


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


def _extract_model_from_usage(usage: dict) -> str | None:
    """Return the first model name from a token_usage dict, if any."""
    by_model = usage.get("by_model")
    if isinstance(by_model, dict) and by_model:
        return str(next(iter(by_model)))
    return None


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
        auth_service: AuthService | None = None,
        observability_reporter: ObservabilityReporter | None = None,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._workspace_service = workspace_service
        self._engine_factory = engine_factory
        self._auth_service = auth_service
        self._observability = observability_reporter or NullReporter()
        self._engines: dict[HarnessEngineType, HarnessEngine] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._initialized = False
        # Streaming delta buffer: thinking/text deltas are held in memory and
        # only the final (is_partial=False) event is persisted.  This avoids
        # writing dozens of tiny delta rows per streaming block to SQLite.
        self._stream_buffers: dict[str, list[TaskOutputEvent]] = {}
        self._seq_cache: dict[str, int] = {}
        self._stream_lock = threading.Lock()
        # Serializes the read-modify-write in _record_token_usage_sync so
        # concurrent engine events for the same task don't lose token data.
        self._token_usage_lock = threading.Lock()
        # Serializes schedule/cancel access to _running_tasks.
        self._task_lock = threading.Lock()

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        from ainrf.db.migration import run_pending

        with self._connect() as conn:
            run_pending(conn, "agentic_researcher")
        self._initialized = True
        # NOT migrated — operates on a separate legacy task_harness.sqlite3;
        # one-time index patch for the deprecated module, not worth formalizing.
        self._migrate_legacy_task_harness_indexes()

    def _migrate_legacy_task_harness_indexes(self) -> None:
        """Patch missing indexes on the legacy task_harness.sqlite3 if it exists.

        The old ``task_harness/`` module was removed in the AgenticResearcher refactor,
        but production containers may still have the database file without indexes.
        Individual index creation is tolerant of missing columns — some schema
        revisions never deployed certain columns.
        """
        legacy_db = self._runtime_root / "task_harness.sqlite3"
        if not legacy_db.exists():
            return
        _INDEXES: list[str] = [
            "CREATE INDEX IF NOT EXISTS idx_th_tasks_project_status ON task_harness_tasks(project_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_th_tasks_env ON task_harness_tasks(environment_id)",
            "CREATE INDEX IF NOT EXISTS idx_th_tasks_workspace ON task_harness_tasks(workspace_id)",
            "CREATE INDEX IF NOT EXISTS idx_th_tasks_created ON task_harness_tasks(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_th_outputs_kind ON task_harness_output_events(kind)",
            "CREATE INDEX IF NOT EXISTS idx_th_edges_project ON task_harness_edges(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_th_edges_source ON task_harness_edges(source_task_id)",
            "CREATE INDEX IF NOT EXISTS idx_th_edges_target ON task_harness_edges(target_task_id)",
        ]
        # Conditional indexes — only if column exists (schema varies by deployment)
        _CONDITIONAL: list[tuple[str, str]] = [
            (
                "task_harness_tasks",
                "CREATE INDEX IF NOT EXISTS idx_th_tasks_session ON task_harness_tasks(session_id)",
            ),
            (
                "task_harness_tasks",
                "CREATE INDEX IF NOT EXISTS idx_th_tasks_owner ON task_harness_tasks(owner_user_id)",
            ),
        ]
        try:
            with closing(sqlite3.connect(str(legacy_db))) as conn:
                for ddl in _INDEXES:
                    try:
                        conn.execute(ddl)
                    except Exception:
                        pass
                # Check which columns actually exist for conditional indexes
                existing_columns: set[str] = set()
                try:
                    for row in conn.execute("PRAGMA table_info('task_harness_tasks')"):
                        existing_columns.add(row[1])
                except Exception:
                    existing_columns = set()
                for col, ddl in _CONDITIONAL:
                    if col in existing_columns:
                        try:
                            conn.execute(ddl)
                        except Exception:
                            pass
                conn.commit()
        except Exception:
            pass  # Non-critical; don't block startup for legacy DB issues

    def _connect(self) -> sqlite3.Connection:
        from ainrf.db.connection import connect

        return connect(self._db_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _compute_duration_ms(task: Task) -> int | None:
        if task.started_at and task.completed_at:
            return max(int((task.completed_at - task.started_at).total_seconds() * 1000), 0)
        return None

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
        profile_overrides: dict[str, str | None] | None = None,
    ) -> Task:
        task_id = self._new_id()
        now = self._now()
        overrides = profile_overrides or {}
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
            api_base_url=overrides.get("api_base_url"),
            api_key=overrides.get("api_key"),
            codex_base_url=overrides.get("codex_base_url"),
            codex_api_key=overrides.get("codex_api_key"),
            codex_model=overrides.get("codex_model"),
            codex_app_server_command=overrides.get("codex_app_server_command"),
            codex_approval_policy=overrides.get("codex_approval_policy"),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, workspace_id, environment_id,
                    researcher_type, harness_engine, user_skills, user_mcp_servers,
                    status, title, prompt, created_at, updated_at, owner_user_id,
                    api_base_url, api_key,
                    codex_base_url, codex_api_key, codex_model,
                    codex_app_server_command, codex_approval_policy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    task.api_base_url,
                    task.api_key,
                    task.codex_base_url,
                    task.codex_api_key,
                    task.codex_model,
                    task.codex_app_server_command,
                    task.codex_approval_policy,
                ),
            )
            conn.commit()
        _LOG.info(
            "task_created",
            task_id=task.task_id,
            project_id=task.project_id,
            researcher_type=task.researcher_type.value,
            harness_engine=task.harness_engine.value,
            owner_user_id=owner_user_id,
        )
        return task

    def schedule_task(self, task_id: str) -> asyncio.Task[None] | None:
        with self._task_lock:
            if task_id in self._running_tasks:
                _LOG.debug("schedule_skipped_already_running", task_id=task_id)
                return None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError as exc:
                raise TaskOperationError("Task execution requires an active event loop") from exc
            task = loop.create_task(self.run_task(task_id))
            self._running_tasks[task_id] = task
            _LOG.info("task_scheduled", task_id=task_id)
            return task

    async def run_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != TaskStatus.QUEUED:
            raise TaskOperationError(f"Cannot run task with status: {task.status}")

        # Bind task_id to structlog context so all downstream log entries
        # (SSH executor, DB queries, etc.) carry the correlation key.
        structlog.contextvars.bind_contextvars(task_id=task_id)

        from ainrf.api.routes.sla_metrics import record_task_started

        record_task_started(task_id)
        self._observability.start_trace(
            trace_id=task_id,
            name=f"task-{task.researcher_type.value}-{task.harness_engine.value}",
            user_id=task.owner_user_id,
            session_id=task.project_id,
            metadata={
                "researcher_type": task.researcher_type.value,
                "harness_engine": task.harness_engine.value,
                "title": task.title,
            },
            input={"prompt": task.prompt},
        )

        try:
            _LOG.info(
                "task_starting",
                project_id=task.project_id,
                researcher_type=task.researcher_type.value,
            )
            await self._set_status(task_id, TaskStatus.STARTING, started=True)
            context = self._build_execution_context(task)
            engine = self._get_engine(task.harness_engine)
            timeout_seconds = (
                context.engine_inactivity_timeout_seconds
                or _DEFAULT_ENGINE_INACTIVITY_TIMEOUT_SECONDS
            )
            watchdog_task: asyncio.Task[None] | None = None
            if timeout_seconds > 0:
                watchdog_task = asyncio.create_task(
                    self._task_watchdog(task_id, engine, timeout_seconds)
                )
            await self._set_status(task_id, TaskStatus.RUNNING)
            _LOG.info("task_running", harness_engine=task.harness_engine.value)
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
                duration_ms = self._compute_duration_ms(latest)
                await self._set_status(task_id, TaskStatus.SUCCEEDED, completed=True, exit_code=0)
                _LOG.info("task_succeeded", duration_ms=duration_ms)
            self._observability.end_trace(
                trace_id=task_id,
                output={"status": "succeeded"},
            )
            from ainrf.api.routes.sla_metrics import record_task_completed

            record_task_completed(
                task_id,
                "succeeded",
                researcher_type=task.researcher_type.value,
                harness_engine=task.harness_engine.value,
            )
        except asyncio.CancelledError:
            latest = self.get_task(task_id)
            if latest.status == TaskStatus.FAILED:
                # The watchdog already marked this task as failed; do not
                # overwrite it to CANCELLED so the user can retry/resume.
                _LOG.warning("task_cancelled_after_watchdog_failure", task_id=task_id)
                self._observability.end_trace(
                    trace_id=task_id,
                    output={"status": "failed"},
                )
                from ainrf.api.routes.sla_metrics import record_task_completed

                record_task_completed(
                    task_id,
                    "failed",
                    researcher_type=task.researcher_type.value,
                    harness_engine=task.harness_engine.value,
                )
            else:
                await self._set_status(task_id, TaskStatus.CANCELLED, completed=True)
                _LOG.warning("task_cancelled")
                self._observability.end_trace(
                    trace_id=task_id,
                    output={"status": "cancelled"},
                )
                from ainrf.api.routes.sla_metrics import record_task_completed

                record_task_completed(
                    task_id,
                    "cancelled",
                    researcher_type=task.researcher_type.value,
                    harness_engine=task.harness_engine.value,
                )
            raise
        except Exception as exc:
            await self.append_output(task_id, "stderr", str(exc))
            await self._set_status(
                task_id,
                TaskStatus.FAILED,
                completed=True,
                error_summary=str(exc),
            )
            _LOG.error("task_failed", error_summary=str(exc))
            self._observability.end_trace(
                trace_id=task_id,
                error=str(exc),
            )
            from ainrf.api.routes.sla_metrics import record_task_completed

            record_task_completed(
                task_id,
                "failed",
                researcher_type=task.researcher_type.value,
                harness_engine=task.harness_engine.value,
            )
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog_task
            with self._task_lock:
                self._running_tasks.pop(task_id, None)
            from ainrf.api.routes.sla_metrics import cleanup_task_state

            cleanup_task_state(task_id)
            structlog.contextvars.unbind_contextvars("task_id")

    async def _task_watchdog(
        self,
        task_id: str,
        engine: HarnessEngine,
        timeout_seconds: float,
    ) -> None:
        """Monitor a running task for engine inactivity and liveness.

        If the engine has not emitted any event for *timeout_seconds* and is
        not alive, mark the task FAILED and cancel the running run_task
        coroutine.  This prevents tasks from staying RUNNING forever when the
        underlying CLI subprocess or SDK session has silently died.
        """
        poll_interval = min(30.0, timeout_seconds / 2.0)
        while True:
            await asyncio.sleep(poll_interval)
            try:
                task = self.get_task(task_id)
            except TaskNotFoundError:
                return
            if task.status not in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                return

            last_event_at = await engine.last_event_at(task_id)
            if last_event_at is None:
                continue

            inactive_seconds = time.time() - last_event_at
            engine_alive = await engine.is_alive(task_id)
            if inactive_seconds > timeout_seconds and not engine_alive:
                # Re-check status right before writing FAILED: the task may have
                # naturally completed between the initial read and now.
                try:
                    task = self.get_task(task_id)
                except TaskNotFoundError:
                    return
                if task.status not in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                    return

                error_message = f"Engine became unresponsive after {int(inactive_seconds)}s"
                _LOG.error(
                    "task_watchdog_timeout",
                    task_id=task_id,
                    inactive_seconds=inactive_seconds,
                    engine_alive=engine_alive,
                )
                await self.append_output(task_id, "stderr", error_message)
                await self._set_status(
                    task_id,
                    TaskStatus.FAILED,
                    completed=True,
                    error_summary=error_message,
                )
                running_task = None
                with self._task_lock:
                    running_task = self._running_tasks.get(task_id)
                if running_task is not None:
                    running_task.cancel()
                return

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
        if task.status not in {
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
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
        if task.status == TaskStatus.RUNNING:
            # If the engine session/process is no longer alive, the current run
            # cannot process the newly queued prompt. Fail the task and re-queue
            # it so the next start() will resume from the checkpoint/session.
            if not await engine.is_alive(task_id):
                error_message = "Engine session lost before follow-up"
                await self.append_output(task_id, "stderr", error_message)
                await self._set_status(
                    task_id,
                    TaskStatus.FAILED,
                    completed=True,
                    error_summary=error_message,
                )
                self._mark_task_queued_for_rerun(task_id)
                self.schedule_task(task_id)
        elif task.status in {
            TaskStatus.PAUSED,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            self._mark_task_queued_for_rerun(task_id)
            self.schedule_task(task_id)
        return event

    def get_output(
        self, task_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[TaskOutputEvent]:
        # Snapshot in-memory streaming deltas (thread-safe)
        with self._stream_lock:
            pending = [e for e in self._stream_buffers.get(task_id, []) if e.seq > after_seq]

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
        db_events = [
            TaskOutputEvent(
                task_id=row["task_id"],
                seq=row["seq"],
                kind=row["kind"],
                content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
        # Merge pending deltas with persisted events, ordered by seq
        if not pending:
            return db_events
        merged = sorted(pending + db_events, key=lambda e: e.seq)
        return merged[:limit]

    async def append_output(self, task_id: str, kind: str, content: str) -> TaskOutputEvent:
        return await asyncio.to_thread(self._append_output_sync, task_id, kind, content)

    def _next_seq(self, task_id: str) -> int:
        """Return the next output seq, backed by an in-memory counter."""
        with self._stream_lock:
            if task_id not in self._seq_cache:
                with closing(self._connect()) as conn:
                    row = conn.execute(
                        "SELECT latest_output_seq FROM tasks WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    if row is None:
                        raise TaskNotFoundError(f"Task not found: {task_id}")
                    self._seq_cache[task_id] = int(row["latest_output_seq"])
            self._seq_cache[task_id] += 1
            return self._seq_cache[task_id]

    def _append_output_sync(self, task_id: str, kind: str, content: str) -> TaskOutputEvent:
        now = self._now()
        seq = self._next_seq(task_id)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_outputs (task_id, seq, kind, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, seq, kind, content, now),
            )
            conn.execute(
                "UPDATE tasks SET latest_output_seq = MAX(latest_output_seq, ?), updated_at = ? WHERE task_id = ?",
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

    # Whitelist of sort → column name mappings to prevent SQL injection
    # through ORDER BY interpolation.  Unknown values fall back to
    # "updated_at".
    _SORT_COLUMNS: dict[str, str] = {"updated": "updated_at", "created": "created_at"}

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

        order_col = self._SORT_COLUMNS.get(sort, "updated_at")
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
        _LOG.warning("task_cancel_requested", task_id=task_id, current_status=task.status.value)
        if task.status == TaskStatus.RUNNING:
            engine = self._get_engine(task.harness_engine)
            await engine.cancel(task_id)
        running_task = None
        with self._task_lock:
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

    def update_task_project(self, task_id: str, new_project_id: str) -> Task:
        self.get_task(task_id)  # raises TaskNotFoundError if missing
        now = self._now()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE tasks SET project_id = ?, updated_at = ? WHERE task_id = ?",
                (new_project_id, now, task_id),
            )
            conn.commit()
        return self.get_task(task_id)

    def update_task(self, task_id: str, *, title: str | None = None) -> Task:
        """Update mutable task fields (title, etc.)."""
        self.get_task(task_id)  # raises TaskNotFoundError if missing
        updates: dict[str, str] = {}
        if title is not None:
            updates["title"] = title
        if not updates:
            return self.get_task(task_id)
        now = self._now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE task_id = ?",
                [*updates.values(), now, task_id],
            )
            conn.commit()
        return self.get_task(task_id)

    async def retry_task(self, task_id: str) -> Task:
        old = self.get_task(task_id)
        if old.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise TaskOperationError(f"Cannot retry task with status: {old.status}")

        engine = self._get_engine(old.harness_engine)

        # Session-aware engines (Agent-SDK, Claude Code): resume the same
        # session and resend the last user message.  One task = one
        # conversation session; retry replays the failed turn.
        if old.harness_engine in {
            HarnessEngineType.AGENT_SDK,
            HarnessEngineType.CLAUDE_CODE,
        }:
            last_user_msg = self._find_last_user_message(task_id)
            if last_user_msg:
                await engine.send_input(task_id, last_user_msg)
            self._mark_task_queued_for_rerun(task_id)
            self.schedule_task(task_id)
            return self.get_task(task_id)

        # Other engines: create a brand-new task.
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

    def _find_last_user_message(self, task_id: str) -> str | None:
        """Return the content of the last user message from task_outputs.

        Scans from the most recent output backwards, looking for
        ``kind='message'`` whose JSON payload has ``role='user'``.
        Returns ``None`` when no user message is found.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT content FROM task_outputs WHERE task_id = ? AND kind = 'message' ORDER BY seq DESC LIMIT 20",
                (task_id,),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("role") == "user":
                content = payload.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        return None

    def _get_prior_user_assistant_messages(self, task_id: str) -> list[dict[str, str]]:
        """Return prior user/assistant messages from task_outputs in seq order.

        Used as a last-resort context fallback when the engine's session
        (agent-sdk session_id or codex thread_id) is lost and cannot be
        resumed from the primary persistence mechanism.

        Only returns ``kind='message'`` entries with ``role='user'`` or
        ``role='assistant'``. Thinking, tool calls, tool results, stderr,
        and system events are excluded — the reconstructed context is a
        degraded view of the conversation, but enough to give the model
        awareness of prior turns.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT content FROM task_outputs
                WHERE task_id = ? AND kind = 'message'
                ORDER BY seq
                """,
                (task_id,),
            ).fetchall()
        messages: list[dict[str, str]] = []
        for row in rows:
            try:
                payload = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            content = payload.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            messages.append({"role": role, "content": content})
        return messages

    def _resolve_skill_load_dir(self, task: Task) -> str | None:
        """Resolve the skill load directory for the task's configured skills.

        Looks up the default workspace's ``skills/`` subdirectory where the
        skill-registry sync service installs ARIS (or other) skill directories.
        Returns ``None`` when no skills are requested or the load directory
        does not exist.
        """
        if not task.user_skills:
            return None

        # The registry sync service installs skills into
        #   <default_workspace_dir>/skills/
        # which resolves to ~/.ainrf_workspaces/default/skills/.
        # Derive it from state_root to avoid importing runtime paths.
        from ainrf.runtime.paths import RuntimePathConfig

        config = RuntimePathConfig(startup_cwd=self._state_root)
        load_dir = config.default_workspace_dir / "skills"
        if not load_dir.is_dir():
            return None

        # Verify at least one requested skill exists in the load directory.
        requested = set(task.user_skills)
        available = {p.name for p in load_dir.iterdir() if p.is_dir()}
        if not requested & available:
            return None

        return str(load_dir)

    @staticmethod
    def _skills_need_codex(skill_load_dir: str, user_skills: list[str]) -> bool:
        """Check whether any selected skill declares the codex MCP server.

        Reads ``skill.json`` for each requested skill and returns ``True`` if
        at least one lists ``"codex"`` in its ``mcp_servers`` field.  This
        avoids starting the Codex MCP server for every skill-enabled task.
        """
        import json

        load_dir = Path(skill_load_dir)
        for skill_id in user_skills:
            skill_json = load_dir / skill_id / "skill.json"
            if not skill_json.is_file():
                continue
            try:
                data = json.loads(skill_json.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    mcp_servers = data.get("mcp_servers", [])
                    if isinstance(mcp_servers, list) and "codex" in mcp_servers:
                        return True
            except (json.JSONDecodeError, OSError):
                continue
        return False

    def _build_execution_context(self, task: Task) -> ExecutionContext:
        tenant_user = self._resolve_tenant_user(task.owner_user_id)
        working_directory = self._resolve_working_directory(task, tenant_user=tenant_user)
        mcp_servers = resolve_mcp_servers_for_task(
            self._state_root,
            user_mcp_servers=task.user_mcp_servers,
        )
        skill_load_dir = self._resolve_skill_load_dir(task)

        # Add the Codex MCP server only when a selected skill explicitly declares
        # it in skill.json, instead of injecting it for every skill-enabled task.
        if skill_load_dir is not None and self._skills_need_codex(skill_load_dir, task.user_skills):
            from ainrf.harness_engine.mcp_servers import _codex_mcp_config

            mcp_servers.setdefault("codex", _codex_mcp_config())

        return ExecutionContext(
            task_id=task.task_id,
            working_directory=str(working_directory),
            rendered_prompt=task.prompt,
            researcher_type=task.researcher_type.value,
            engine_type=task.harness_engine,
            skills=task.user_skills,
            mcp_servers=mcp_servers or None,
            session_state_path=str(
                self._runtime_root / "session-states" / task.task_id / "checkpoint.json"
            ),
            tenant_user=tenant_user,
            skill_load_dir=skill_load_dir,
            prior_messages=(self._get_prior_user_assistant_messages(task.task_id) or None),
            api_base_url=task.api_base_url,
            api_key=task.api_key,
            codex_base_url=task.codex_base_url,
            codex_api_key=task.codex_api_key,
            codex_model=task.codex_model,
            codex_app_server_command=task.codex_app_server_command,
            codex_approval_policy=task.codex_approval_policy,
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
                "--permission-mode",
                "bypassPermissions",
            ]
        if context.engine_type == HarnessEngineType.CODEX_APP_SERVER:
            command_text = context.codex_app_server_command or "codex app-server --listen stdio://"
            return shlex.split(command_text)
        return ["claude-agent-sdk", "query"]

    def _resolve_working_directory(
        self,
        task: Task,
        tenant_user: str | None = None,
    ) -> Path:
        if self._workspace_service is not None:
            try:
                workspace = self._workspace_service.get_workspace(task.workspace_id)
            except WorkspaceNotFoundError:
                workspace = None
            if workspace is not None and workspace.default_workdir:
                path = Path(workspace.default_workdir).expanduser().resolve()
                self._ensure_dir(path, tenant_user)
                return path
        fallback = self._state_root / "workspace" / task.workspace_id
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    @staticmethod
    def _ensure_dir(path: Path, tenant_user: str | None) -> None:
        """Create *path* (with parents).  When *tenant_user* is set the
        directory is created via ``sudo -u <tenant> mkdir -p`` so the
        resulting directory is owned by the tenant user instead of ainrf.
        """
        if path.exists():
            return
        if tenant_user:
            subprocess.run(
                ["sudo", "-u", tenant_user, "mkdir", "-p", str(path)],
                check=False,
                capture_output=True,
            )
        else:
            path.mkdir(parents=True, exist_ok=True)

    def _resolve_tenant_user(self, owner_user_id: str) -> str | None:
        """Resolve owner_user_id to the Linux tenant username ``ainrf_<name>``.

        Returns ``None`` when the auth service is unavailable, the user has
        no corresponding Linux account (e.g. local dev / tests), or the
        Linux user has not been provisioned yet.
        """
        if self._auth_service is None:
            return None
        try:
            user = self._auth_service.get_user(owner_user_id)
        except Exception:
            return None
        from ainrf.auth.service import (
            _is_container_environment,
            _linux_user_exists,
            tenant_linux_username,
        )

        if not _is_container_environment():
            return None
        linux_user = tenant_linux_username(user.username)
        if not _linux_user_exists(linux_user):
            return None
        return linux_user

    def _get_engine(self, engine_type: HarnessEngineType) -> HarnessEngine:
        engine = self._engines.get(engine_type)
        if engine is None:
            engine = self._engine_factory(engine_type.value)
            # Agent-sdk engine gets a DB-backed session store so transcript
            # persistence survives container restarts.
            if engine_type == HarnessEngineType.AGENT_SDK:
                from ainrf.harness_engine.db_session_store import DbSessionStore

                engine._session_store = DbSessionStore(str(self._db_path))
            self._engines[engine_type] = engine
        return engine

    def get_engine_for_task(self, task: Task) -> HarnessEngine:
        """Return the harness engine instance for *task*, creating it if needed."""
        return self._get_engine(task.harness_engine)

    async def _handle_engine_event(self, task_id: str, event: EngineEvent) -> None:
        kind = "lifecycle" if event.event_type in {"status", "system"} else event.event_type
        content = self._event_content(event)

        # Streaming deltas (is_delta=True) are buffered in memory only.
        # The final event (is_partial=False) carries the full accumulated
        # text and is persisted to SQLite.  This avoids writing dozens of
        # tiny delta rows per thinking/text block.
        payload = event.payload
        if (
            isinstance(payload, dict)
            and payload.get("is_delta")
            and event.event_type in {"thinking", "message"}
        ):
            self._buffer_streaming_delta(task_id, kind, content)
        else:
            await self.append_output(task_id, kind, content)
            # Clear the in-memory buffer once the final event is persisted
            if (
                isinstance(payload, dict)
                and payload.get("is_partial") is False
                and event.event_type in {"thinking", "message"}
            ):
                self._clear_stream_buffer(task_id, payload.get("block_id"))

        if event.token_usage:
            await self._record_token_usage(
                task_id, event.token_usage, replace=event.event_type != "token"
            )
            # Report LLM generation to observability backend (dual-write).
            model = _extract_model_from_usage(event.token_usage)
            self._observability.record_generation(
                trace_id=task_id,
                name=f"llm-{event.event_type}",
                model=model,
                usage_details={
                    k: _int_number(event.token_usage.get("total", {}).get(k))
                    for k in TOKEN_TOTAL_FIELDS
                },
                cost_details={
                    "cost_usd": _number(event.token_usage.get("total", {}).get("cost_usd")),
                },
                metadata={"source": event.token_usage.get("source", "unknown")},
            )
            # Record SLA: first-token latency (best-effort from usage timestamp).
            from ainrf.api.routes.sla_metrics import (
                record_llm_first_token,
                record_llm_first_token_latency,
            )

            record_llm_first_token(task_id, model=model or "")
            ttft = event.token_usage.get("time_to_first_token")
            if ttft is not None:
                try:
                    record_llm_first_token_latency(
                        model=model or "",
                        latency_seconds=float(ttft),
                    )
                except (TypeError, ValueError):
                    pass
        if event.event_type == "status":
            status = event.payload.get("status")
            exit_code = event.payload.get("exit_code")
            if status == "succeeded":
                _LOG.info("task_engine_succeeded", task_id=task_id, exit_code=exit_code)
                await self._set_status(
                    task_id,
                    TaskStatus.SUCCEEDED,
                    completed=True,
                    exit_code=exit_code if isinstance(exit_code, int) else 0,
                )
            elif status == "failed":
                _LOG.error("task_engine_failed", task_id=task_id, exit_code=exit_code)
                await self._set_status(
                    task_id,
                    TaskStatus.FAILED,
                    completed=True,
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                    error_summary=event.payload.get("error_summary")
                    or event.payload.get("message"),
                )
        elif event.event_type == "system":
            subtype = event.payload.get("subtype")
            if subtype == "task_paused":
                _LOG.info("task_paused", task_id=task_id)
                await self._set_status(task_id, TaskStatus.PAUSED)
            elif subtype == "task_failed":
                payload = event.payload
                rc = payload.get("returncode") or payload.get("exit_code")
                err = (
                    payload.get("error_summary")
                    or payload.get("message")
                    or self._extract_nested_error(payload)
                )
                await self._set_status(
                    task_id,
                    TaskStatus.FAILED,
                    completed=True,
                    exit_code=rc if isinstance(rc, int) else None,
                    error_summary=err,
                )
            elif subtype == "task_completed":
                latest = self.get_task(task_id)
                if latest.status in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                    await self._set_status(
                        task_id,
                        TaskStatus.SUCCEEDED,
                        completed=True,
                        exit_code=0,
                    )

    def _buffer_streaming_delta(self, task_id: str, kind: str, content: str) -> None:
        """Buffer a streaming delta event in memory (no SQLite write)."""
        seq = self._next_seq(task_id)
        evt = TaskOutputEvent(
            task_id=task_id,
            seq=seq,
            kind=kind,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        with self._stream_lock:
            self._stream_buffers.setdefault(task_id, []).append(evt)

    def _clear_stream_buffer(self, task_id: str, block_id: str | None) -> None:
        """Remove buffered deltas for a completed streaming block."""
        with self._stream_lock:
            buf = self._stream_buffers.get(task_id)
            if buf is None:
                return
            if block_id is None:
                # No block_id — clear all pending for this task
                self._stream_buffers.pop(task_id, None)
                return
            # Remove only deltas matching this block_id (parse JSON, don't substring-match)
            remaining = [e for e in buf if not self._event_matches_block_id(e, block_id)]
            if remaining:
                self._stream_buffers[task_id] = remaining
            else:
                self._stream_buffers.pop(task_id, None)

    @staticmethod
    def _event_matches_block_id(event: TaskOutputEvent, block_id: str) -> bool:
        """Check whether a buffered delta event belongs to the given block_id."""
        try:
            payload = json.loads(event.content)
            return isinstance(payload, dict) and payload.get("block_id") == block_id
        except (json.JSONDecodeError, AttributeError):
            return False

    @staticmethod
    def _extract_nested_error(payload: dict[str, Any]) -> str | None:
        """Try to extract an error message from nested payload structures.

        Different engines encode errors differently:
        - codex-app-server: ``{"turn": {"error": {"message": "..."}}}``
        - claude-code: ``{"error": "..."}``
        """
        # codex: turn.error.message
        turn = payload.get("turn")
        if isinstance(turn, dict):
            err = turn.get("error")
            if isinstance(err, dict):
                return err.get("message")
            if isinstance(err, str):
                return err
        # claude-code: top-level error
        err = payload.get("error")
        if isinstance(err, str):
            return err
        return None

    async def _record_token_usage(self, task_id: str, usage: dict, *, replace: bool) -> None:
        await asyncio.to_thread(self._record_token_usage_sync, task_id, usage, replace)

    def _record_token_usage_sync(self, task_id: str, usage: dict, replace: bool) -> None:
        # Hold _token_usage_lock during the read-modify-write cycle to prevent
        # concurrent merges from silently dropping token data when two engine
        # events for the same task race through the thread pool.
        with self._token_usage_lock:
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
        # Flush any remaining streaming deltas when task reaches a terminal state
        if completed:
            with self._stream_lock:
                self._stream_buffers.pop(task_id, None)
        _LOG.debug(
            "task_status_changed", task_id=task_id, to_status=status.value, exit_code=exit_code
        )

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
            api_base_url=_col(row, "api_base_url"),
            api_key=_col(row, "api_key"),
            codex_base_url=_col(row, "codex_base_url"),
            codex_api_key=_col(row, "codex_api_key"),
            codex_model=_col(row, "codex_model"),
            codex_app_server_command=_col(row, "codex_app_server_command"),
            codex_approval_policy=_col(row, "codex_approval_policy"),
        )

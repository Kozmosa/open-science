from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.tasks.models import ManagedTask, ManagedTaskStatus, TaskTerminalBinding
from ainrf.terminal.models import TerminalAttachmentMode, TerminalAttachmentTarget, UserEnvironmentBinding, utc_now
from ainrf.terminal.sessions import SessionManager, TerminalSessionOperationError
from ainrf.terminal.tmux import TmuxAdapter, TmuxCommandError, TmuxWindowInfo

_WINDOW_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_TERMINAL_STATUSES = {
    ManagedTaskStatus.COMPLETED,
    ManagedTaskStatus.FAILED,
    ManagedTaskStatus.CANCELLED,
}


class TaskOperationError(RuntimeError):
    pass


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class TaskManager:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: InMemoryEnvironmentService,
        session_manager: SessionManager,
        tmux_adapter: TmuxAdapter,
        cancel_grace_seconds: float = 5.0,
        cancel_poll_interval_seconds: float = 0.25,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "terminal_state.sqlite3"
        self._environment_service = environment_service
        self._session_manager = session_manager
        self._tmux_adapter = tmux_adapter
        self._cancel_grace_seconds = cancel_grace_seconds
        self._cancel_poll_interval_seconds = cancel_poll_interval_seconds
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS managed_tasks (
                    task_id TEXT PRIMARY KEY,
                    binding_id TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    command TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    exit_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(binding_id) REFERENCES user_environment_bindings(binding_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_terminal_bindings (
                    task_id TEXT PRIMARY KEY,
                    binding_id TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    agent_session_name TEXT NOT NULL,
                    window_id TEXT NOT NULL,
                    window_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    readonly INTEGER NOT NULL,
                    last_output_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES managed_tasks(task_id)
                )
                """
            )
            connection.commit()
        self._initialized = True

    def create_task(
        self,
        environment: EnvironmentRegistryEntry,
        *,
        title: str,
        command: str,
        working_directory: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
        self.initialize()
        try:
            binding, pair = self._session_manager.ensure_agent_session(environment, working_directory)
        except TerminalSessionOperationError as exc:
            raise TaskOperationError(str(exc)) from exc

        agent_session_name = pair.agent_session_name or self._session_manager.agent_session_name_for(
            environment.id
        )
        task_id = str(uuid4())
        window_name_hint = self._window_name_for(title, task_id)
        try:
            window = self._tmux_adapter.create_window(
                binding,
                environment,
                agent_session_name,
                window_name=window_name_hint,
                working_directory=working_directory,
                command=command,
            )
        except TmuxCommandError as exc:
            raise TaskOperationError(str(exc)) from exc

        now = utc_now()
        task = self._store_task(
            ManagedTask(
                task_id=task_id,
                binding_id=binding.binding_id,
                environment_id=environment.id,
                title=title,
                command=command,
                working_directory=working_directory,
                status=ManagedTaskStatus.RUNNING,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
        )
        terminal_binding = self._store_terminal_binding(
            TaskTerminalBinding(
                task_id=task.task_id,
                binding_id=binding.binding_id,
                environment_id=environment.id,
                agent_session_name=agent_session_name,
                window_id=window.window_id,
                window_name=window.window_name,
                status=ManagedTaskStatus.RUNNING,
                mode=TerminalAttachmentMode.OBSERVE,
                readonly=True,
                last_output_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        return task, terminal_binding

    def list_tasks(self, environment_id: str) -> list[tuple[ManagedTask, TaskTerminalBinding | None]]:
        self.initialize()
        items: list[tuple[ManagedTask, TaskTerminalBinding | None]] = []
        for task in self._load_tasks_for_environment(environment_id):
            items.append(self._refresh_task_bundle(task))
        return items

    def get_task(self, task_id: str) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        self.initialize()
        task = self._load_task(task_id)
        if task is None:
            raise TaskOperationError("Task not found")
        return self._refresh_task_bundle(task)

    def get_task_terminal_binding(self, task_id: str) -> TaskTerminalBinding:
        task, terminal_binding = self.get_task(task_id)
        _ = task
        if terminal_binding is None:
            raise TaskOperationError("Task terminal binding not found")
        return terminal_binding

    def open_task_terminal(
        self,
        task_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding, TerminalAttachmentTarget]:
        task, terminal_binding = self.get_task(task_id)
        if terminal_binding is None:
            raise TaskOperationError("Task terminal binding not found")

        environment = self._resolve_environment(task.environment_id)
        binding = self._resolve_user_binding(task.binding_id)
        assert environment is not None
        assert binding is not None
        window = self._inspect_window(binding, environment, terminal_binding)
        if window is None:
            raise TaskOperationError("Task terminal window is unavailable")

        target = TerminalAttachmentTarget(
            binding_id=binding.binding_id,
            session_id=terminal_binding.window_id,
            session_name=terminal_binding.agent_session_name,
            user_id=binding.user_id,
            environment_id=environment.id,
            environment_alias=environment.alias,
            target_kind=self._tmux_adapter.target_kind_for(environment),
            working_directory=task.working_directory,
            attach_command=self._tmux_adapter.build_window_attach_command(
                binding,
                environment,
                terminal_binding.agent_session_name,
                terminal_binding.window_id,
            ),
            spawn_working_directory=self._state_root,
            readonly=True,
            mode=TerminalAttachmentMode.OBSERVE,
            window_id=terminal_binding.window_id,
            window_name=window.window_name,
        )
        return task, terminal_binding, target

    def cancel_task(self, task_id: str) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        task, terminal_binding = self.get_task(task_id)
        if terminal_binding is None or task.status in _TERMINAL_STATUSES:
            return task, terminal_binding

        environment = self._resolve_environment(task.environment_id)
        binding = self._resolve_user_binding(task.binding_id)
        assert environment is not None
        assert binding is not None
        try:
            self._tmux_adapter.send_window_interrupt(
                binding,
                environment,
                terminal_binding.window_id,
            )
        except TmuxCommandError as exc:
            raise TaskOperationError(str(exc)) from exc

        deadline = time.monotonic() + self._cancel_grace_seconds
        while time.monotonic() < deadline:
            window = self._inspect_window(binding, environment, terminal_binding, raise_on_error=False)
            if window is None or window.is_dead:
                cancelled_at = utc_now()
                cancelled_task = self._store_task(
                    replace(
                        task,
                        status=ManagedTaskStatus.CANCELLED,
                        updated_at=cancelled_at,
                        completed_at=cancelled_at,
                        exit_code=window.exit_status if window is not None else task.exit_code,
                        detail=None,
                    )
                )
                cancelled_binding = self._store_terminal_binding(
                    replace(
                        terminal_binding,
                        status=ManagedTaskStatus.CANCELLED,
                        window_name=window.window_name if window is not None else terminal_binding.window_name,
                        last_output_at=cancelled_at,
                        updated_at=cancelled_at,
                    )
                )
                return cancelled_task, cancelled_binding
            time.sleep(self._cancel_poll_interval_seconds)

        running_at = utc_now()
        task = self._store_task(
            replace(
                task,
                updated_at=running_at,
                detail="Cancellation signal sent; waiting for task to exit",
            )
        )
        terminal_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                updated_at=running_at,
            )
        )
        return task, terminal_binding

    def reconcile(self) -> None:
        self.initialize()
        for task in self._list_tasks():
            self._refresh_task_bundle(task)

    def _refresh_task_bundle(
        self,
        task: ManagedTask,
    ) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        terminal_binding = self._load_terminal_binding(task.task_id)
        if terminal_binding is None:
            return task, None
        environment = self._resolve_environment(task.environment_id, raise_on_error=False)
        binding = self._resolve_user_binding(task.binding_id, raise_on_error=False)
        if environment is None:
            failure_at = utc_now()
            return self._store_task(
                replace(
                    task,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                    completed_at=task.completed_at or failure_at,
                    detail="Environment not found during task reconcile",
                )
            ), self._store_terminal_binding(
                replace(
                    terminal_binding,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                )
            )
        if binding is None:
            failure_at = utc_now()
            return self._store_task(
                replace(
                    task,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                    completed_at=task.completed_at or failure_at,
                    detail="Terminal binding not found during task reconcile",
                )
            ), self._store_terminal_binding(
                replace(
                    terminal_binding,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                )
            )
        window = self._inspect_window(binding, environment, terminal_binding, raise_on_error=False)
        if window is None:
            if task.status in _TERMINAL_STATUSES:
                return task, terminal_binding
            failure_at = utc_now()
            return self._store_task(
                replace(
                    task,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                    completed_at=failure_at,
                    detail="Task tmux window is not available",
                )
            ), self._store_terminal_binding(
                replace(
                    terminal_binding,
                    status=ManagedTaskStatus.FAILED,
                    updated_at=failure_at,
                )
            )
        return self._apply_window_state(task, terminal_binding, window)

    def _apply_window_state(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        window: TmuxWindowInfo,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
        now = utc_now()
        if window.is_dead:
            final_status = self._final_status_for(task.status, window.exit_status)
            detail: str | None
            if final_status is ManagedTaskStatus.FAILED and window.exit_status is not None:
                detail = f"Task exited with code {window.exit_status}"
            else:
                detail = None
            updated_task = self._store_task(
                replace(
                    task,
                    status=final_status,
                    updated_at=now,
                    completed_at=task.completed_at or now,
                    exit_code=window.exit_status,
                    detail=detail,
                )
            )
            updated_binding = self._store_terminal_binding(
                replace(
                    terminal_binding,
                    window_name=window.window_name,
                    status=final_status,
                    last_output_at=now,
                    updated_at=now,
                )
            )
            return updated_task, updated_binding

        updated_task = self._store_task(
            replace(
                task,
                status=ManagedTaskStatus.RUNNING,
                updated_at=now,
                started_at=task.started_at or now,
                detail=None,
            )
        )
        updated_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                window_name=window.window_name,
                status=ManagedTaskStatus.RUNNING,
                last_output_at=now,
                updated_at=now,
            )
        )
        return updated_task, updated_binding

    def _resolve_environment(
        self,
        environment_id: str,
        *,
        raise_on_error: bool = True,
    ) -> EnvironmentRegistryEntry | None:
        try:
            return self._environment_service.get_environment(environment_id)
        except EnvironmentNotFoundError:
            if raise_on_error:
                raise TaskOperationError("Environment not found")
            return None

    def _resolve_user_binding(
        self,
        binding_id: str,
        *,
        raise_on_error: bool = True,
    ) -> UserEnvironmentBinding | None:
        binding = self._session_manager.get_binding_by_id(binding_id)
        if binding is None and raise_on_error:
            raise TaskOperationError("Terminal binding not found")
        return binding

    def _inspect_window(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        terminal_binding: TaskTerminalBinding,
        *,
        raise_on_error: bool = True,
    ) -> TmuxWindowInfo | None:
        try:
            return self._tmux_adapter.inspect_window(
                binding,
                environment,
                terminal_binding.agent_session_name,
                terminal_binding.window_id,
            )
        except TmuxCommandError:
            if raise_on_error:
                raise
            return None

    @staticmethod
    def _final_status_for(
        current_status: ManagedTaskStatus,
        exit_code: int | None,
    ) -> ManagedTaskStatus:
        if current_status is ManagedTaskStatus.CANCELLED or exit_code == 130:
            return ManagedTaskStatus.CANCELLED
        if exit_code == 0:
            return ManagedTaskStatus.COMPLETED
        return ManagedTaskStatus.FAILED

    @staticmethod
    def _window_name_for(title: str, task_id: str) -> str:
        normalized = _WINDOW_NAME_RE.sub("-", title.strip()).strip("-").lower()
        if not normalized:
            normalized = "task"
        return f"{normalized[:20]}-{task_id[:8]}"

    def _list_tasks(self) -> list[ManagedTask]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, binding_id, environment_id, title, command, working_directory,
                       status, created_at, updated_at, started_at, completed_at, exit_code, detail
                FROM managed_tasks
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def _load_tasks_for_environment(self, environment_id: str) -> list[ManagedTask]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, binding_id, environment_id, title, command, working_directory,
                       status, created_at, updated_at, started_at, completed_at, exit_code, detail
                FROM managed_tasks
                WHERE environment_id = ?
                ORDER BY created_at DESC
                """,
                (environment_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def _load_task(self, task_id: str) -> ManagedTask | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task_id, binding_id, environment_id, title, command, working_directory,
                       status, created_at, updated_at, started_at, completed_at, exit_code, detail
                FROM managed_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def _load_terminal_binding(self, task_id: str) -> TaskTerminalBinding | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task_id, binding_id, environment_id, agent_session_name, window_id,
                       window_name, status, mode, readonly, last_output_at, created_at, updated_at
                FROM task_terminal_bindings
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_terminal_binding(row)

    def _store_task(self, task: ManagedTask) -> ManagedTask:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO managed_tasks (
                    task_id, binding_id, environment_id, title, command, working_directory,
                    status, created_at, updated_at, started_at, completed_at, exit_code, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    binding_id = excluded.binding_id,
                    environment_id = excluded.environment_id,
                    title = excluded.title,
                    command = excluded.command,
                    working_directory = excluded.working_directory,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    exit_code = excluded.exit_code,
                    detail = excluded.detail
                """,
                (
                    task.task_id,
                    task.binding_id,
                    task.environment_id,
                    task.title,
                    task.command,
                    task.working_directory,
                    task.status.value,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.started_at.isoformat() if task.started_at is not None else None,
                    task.completed_at.isoformat() if task.completed_at is not None else None,
                    task.exit_code,
                    task.detail or "",
                ),
            )
            connection.commit()
        return task

    def _store_terminal_binding(self, terminal_binding: TaskTerminalBinding) -> TaskTerminalBinding:
        created_at = terminal_binding.created_at or utc_now()
        updated_at = terminal_binding.updated_at or created_at
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_terminal_bindings (
                    task_id, binding_id, environment_id, agent_session_name, window_id, window_name,
                    status, mode, readonly, last_output_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    binding_id = excluded.binding_id,
                    environment_id = excluded.environment_id,
                    agent_session_name = excluded.agent_session_name,
                    window_id = excluded.window_id,
                    window_name = excluded.window_name,
                    status = excluded.status,
                    mode = excluded.mode,
                    readonly = excluded.readonly,
                    last_output_at = excluded.last_output_at,
                    updated_at = excluded.updated_at
                """,
                (
                    terminal_binding.task_id,
                    terminal_binding.binding_id,
                    terminal_binding.environment_id,
                    terminal_binding.agent_session_name,
                    terminal_binding.window_id,
                    terminal_binding.window_name,
                    terminal_binding.status.value,
                    terminal_binding.mode.value,
                    int(terminal_binding.readonly),
                    terminal_binding.last_output_at.isoformat()
                    if terminal_binding.last_output_at is not None
                    else None,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )
            connection.commit()
        return replace(terminal_binding, created_at=created_at, updated_at=updated_at)

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> ManagedTask:
        return ManagedTask(
            task_id=row["task_id"],
            binding_id=row["binding_id"],
            environment_id=row["environment_id"],
            title=row["title"],
            command=row["command"],
            working_directory=row["working_directory"],
            status=ManagedTaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
            exit_code=row["exit_code"],
            detail=row["detail"] or None,
        )

    @staticmethod
    def _row_to_terminal_binding(row: sqlite3.Row) -> TaskTerminalBinding:
        return TaskTerminalBinding(
            task_id=row["task_id"],
            binding_id=row["binding_id"],
            environment_id=row["environment_id"],
            agent_session_name=row["agent_session_name"],
            window_id=row["window_id"],
            window_name=row["window_name"],
            status=ManagedTaskStatus(row["status"]),
            mode=TerminalAttachmentMode(row["mode"]),
            readonly=bool(row["readonly"]),
            last_output_at=_parse_datetime(row["last_output_at"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

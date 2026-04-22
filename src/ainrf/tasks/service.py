from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.tasks.models import (
    ManagedTask,
    ManagedTaskStatus,
    TaskAgentWriteState,
    TaskTakeoverLease,
    TaskTakeoverLeaseStatus,
    TaskTerminalBinding,
    TaskTerminalBindingStatus,
)
from ainrf.tasks.runtime import build_runtime_run_command, runtime_dir_for_task
from ainrf.terminal.models import (
    TerminalAttachment,
    TerminalAttachmentMode,
    TerminalAttachmentTarget,
    UserEnvironmentBinding,
    utc_now,
)
from ainrf.terminal.sessions import SessionManager, TerminalSessionOperationError
from ainrf.terminal.tmux import TmuxAdapter, TmuxCommandError, TmuxWindowInfo

_WINDOW_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_FINAL_TASK_STATUSES = {
    ManagedTaskStatus.COMPLETED,
    ManagedTaskStatus.FAILED,
    ManagedTaskStatus.CANCELLED,
}


class TaskOperationError(RuntimeError):
    pass


class TaskNotFoundError(TaskOperationError):
    pass


class TaskConflictError(TaskOperationError):
    pass


class TaskRuntimeControlError(TaskOperationError):
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
        takeover_ack_timeout_seconds: float = 5.0,
        takeover_disconnect_grace_seconds: float = 5.0,
        final_window_retention_seconds: float = 60.0 * 60.0,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "terminal_state.sqlite3"
        self._environment_service = environment_service
        self._session_manager = session_manager
        self._tmux_adapter = tmux_adapter
        self._cancel_grace_seconds = cancel_grace_seconds
        self._cancel_poll_interval_seconds = cancel_poll_interval_seconds
        self._takeover_ack_timeout_seconds = takeover_ack_timeout_seconds
        self._takeover_disconnect_grace_seconds = takeover_disconnect_grace_seconds
        self._final_window_retention_seconds = final_window_retention_seconds
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
                    ownership_user_id TEXT,
                    agent_write_state TEXT NOT NULL DEFAULT 'running',
                    pause_requested_at TEXT,
                    pause_acknowledged_at TEXT,
                    last_takeover_at TEXT,
                    last_output_at TEXT,
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES managed_tasks(task_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_takeover_leases (
                    lease_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    grace_started_at TEXT,
                    grace_expires_at TEXT,
                    released_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES managed_tasks(task_id)
                )
                """
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "ownership_user_id",
                "ALTER TABLE task_terminal_bindings ADD COLUMN ownership_user_id TEXT",
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "agent_write_state",
                (
                    "ALTER TABLE task_terminal_bindings "
                    "ADD COLUMN agent_write_state TEXT NOT NULL DEFAULT 'running'"
                ),
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "pause_requested_at",
                "ALTER TABLE task_terminal_bindings ADD COLUMN pause_requested_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "pause_acknowledged_at",
                "ALTER TABLE task_terminal_bindings ADD COLUMN pause_acknowledged_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "last_takeover_at",
                "ALTER TABLE task_terminal_bindings ADD COLUMN last_takeover_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_terminal_bindings",
                "archived_at",
                "ALTER TABLE task_terminal_bindings ADD COLUMN archived_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_takeover_leases",
                "grace_started_at",
                "ALTER TABLE task_takeover_leases ADD COLUMN grace_started_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_takeover_leases",
                "grace_expires_at",
                "ALTER TABLE task_takeover_leases ADD COLUMN grace_expires_at TEXT",
            )
            connection.commit()
        self._initialized = True

    def create_task(
        self,
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        *,
        title: str,
        command: str,
        working_directory: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
        self.initialize()
        try:
            binding, pair = self._session_manager.ensure_agent_session(
                app_user_id,
                environment,
                working_directory,
            )
        except TerminalSessionOperationError as exc:
            raise TaskOperationError(str(exc)) from exc

        agent_session_name = (
            pair.agent_session_name
            or self._session_manager.agent_session_name_for(
                app_user_id,
                environment.id,
            )
        )
        task_id = str(uuid4())
        window_name_hint = self._window_name_for(title, task_id)
        runtime_command = build_runtime_run_command(
            task_id=task_id,
            runtime_dir=runtime_dir_for_task(working_directory, task_id),
            working_directory=working_directory,
            command=command,
            shell=binding.default_shell or "/bin/bash",
        )
        try:
            window = self._tmux_adapter.create_window(
                binding,
                environment,
                agent_session_name,
                window_name=window_name_hint,
                working_directory=working_directory,
                command=runtime_command,
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
                binding_status=TaskTerminalBindingStatus.RUNNING_OBSERVE,
                mode=TerminalAttachmentMode.OBSERVE,
                readonly=True,
                agent_write_state=TaskAgentWriteState.RUNNING,
                last_output_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        return task, terminal_binding

    def list_tasks(
        self,
        environment_id: str,
        app_user_id: str,
    ) -> list[tuple[ManagedTask, TaskTerminalBinding | None]]:
        self.initialize()
        _ = app_user_id
        items: list[tuple[ManagedTask, TaskTerminalBinding | None]] = []
        for task in self._load_tasks_for_environment(environment_id):
            items.append(self._refresh_task_bundle(task))
        return items

    def get_task(
        self,
        task_id: str,
        app_user_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        self.initialize()
        _ = app_user_id
        task = self._load_task(task_id)
        if task is None:
            raise TaskNotFoundError("Task not found")
        return self._refresh_task_bundle(task)

    def get_task_terminal_binding(
        self,
        task_id: str,
        app_user_id: str,
    ) -> TaskTerminalBinding:
        _, terminal_binding = self.get_task(task_id, app_user_id)
        if terminal_binding is None:
            raise TaskNotFoundError("Task terminal binding not found")
        return terminal_binding

    def open_task_terminal(
        self,
        task_id: str,
        app_user_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding, TerminalAttachmentTarget]:
        task, terminal_binding = self.get_task(task_id, app_user_id)
        if terminal_binding is None:
            raise TaskNotFoundError("Task terminal binding not found")
        if terminal_binding.binding_status is TaskTerminalBindingStatus.ARCHIVED:
            raise TaskConflictError("Task terminal has been archived")

        current_lease = self._load_live_lease(task_id)
        if (
            current_lease is not None
            and current_lease.user_id == app_user_id
            and current_lease.status is TaskTakeoverLeaseStatus.GRACE_PENDING
            and self._is_grace_lease_reclaimable(current_lease)
        ):
            terminal_binding, _ = self._reactivate_grace_lease(
                task,
                terminal_binding,
                current_lease,
            )
            return self._build_task_attachment(
                task,
                terminal_binding,
                mode=TerminalAttachmentMode.WRITE,
                readonly=False,
                owner_user_id=app_user_id,
            )

        _, _, target = self._build_task_attachment(
            task,
            terminal_binding,
            mode=TerminalAttachmentMode.OBSERVE,
            readonly=True,
            owner_user_id=terminal_binding.ownership_user_id,
        )
        return task, terminal_binding, target

    def takeover(
        self,
        task_id: str,
        app_user_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding, TerminalAttachmentTarget]:
        task, terminal_binding = self.get_task(task_id, app_user_id)
        if terminal_binding is None:
            raise TaskNotFoundError("Task terminal binding not found")
        if terminal_binding.binding_status is TaskTerminalBindingStatus.ARCHIVED:
            raise TaskConflictError("Task terminal has been archived")
        if task.status is not ManagedTaskStatus.RUNNING:
            raise TaskConflictError("Task is not running")

        live_lease = self._load_live_lease(task_id)
        if live_lease is not None:
            if live_lease.user_id != app_user_id:
                raise TaskConflictError("Task is already taken over by another user")
            if (
                live_lease.status is TaskTakeoverLeaseStatus.GRACE_PENDING
                and self._is_grace_lease_reclaimable(live_lease)
            ):
                terminal_binding, _ = self._reactivate_grace_lease(
                    task,
                    terminal_binding,
                    live_lease,
                )
                return self._build_task_attachment(
                    task,
                    terminal_binding,
                    mode=TerminalAttachmentMode.WRITE,
                    readonly=False,
                    owner_user_id=app_user_id,
                )
            return self._build_task_attachment(
                task,
                terminal_binding,
                mode=TerminalAttachmentMode.WRITE,
                readonly=False,
                owner_user_id=app_user_id,
            )

        requested_at = utc_now()
        original_binding = terminal_binding
        pending_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                agent_write_state=TaskAgentWriteState.PAUSE_REQUESTED,
                pause_requested_at=requested_at,
                updated_at=requested_at,
            )
        )
        try:
            self._run_task_runtime_action(
                task, "pause", timeout_seconds=self._takeover_ack_timeout_seconds
            )
        except TaskRuntimeControlError:
            self._store_terminal_binding(original_binding)
            raise

        self._store_lease(
            TaskTakeoverLease(
                lease_id=str(uuid4()),
                task_id=task_id,
                user_id=app_user_id,
                status=TaskTakeoverLeaseStatus.ACTIVE,
                acquired_at=requested_at,
                grace_started_at=None,
                grace_expires_at=None,
            )
        )
        acknowledged_at = utc_now()
        taken_over_binding = self._store_terminal_binding(
            replace(
                pending_binding,
                binding_status=TaskTerminalBindingStatus.TAKEN_OVER,
                mode=TerminalAttachmentMode.WRITE,
                readonly=False,
                ownership_user_id=app_user_id,
                agent_write_state=TaskAgentWriteState.PAUSED_BY_USER,
                pause_acknowledged_at=acknowledged_at,
                last_takeover_at=acknowledged_at,
                archived_at=None,
                updated_at=acknowledged_at,
            )
        )
        return self._build_task_attachment(
            task,
            taken_over_binding,
            mode=TerminalAttachmentMode.WRITE,
            readonly=False,
            owner_user_id=app_user_id,
        )

    def release(
        self,
        task_id: str,
        app_user_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding, TerminalAttachmentTarget]:
        task, terminal_binding = self.get_task(task_id, app_user_id)
        if terminal_binding is None:
            raise TaskNotFoundError("Task terminal binding not found")

        live_lease = self._load_live_lease(task_id)
        if live_lease is None or live_lease.user_id != app_user_id:
            raise TaskConflictError("Task is not taken over by the current user")

        released_binding = self._release_takeover(
            task,
            terminal_binding,
            live_lease,
            released_at=utc_now(),
            resume_runtime=task.status is ManagedTaskStatus.RUNNING,
        )
        return self._build_task_attachment(
            task,
            released_binding,
            mode=TerminalAttachmentMode.OBSERVE,
            readonly=True,
            owner_user_id=None,
        )

    def handle_task_attachment_disconnect(self, attachment: TerminalAttachment) -> None:
        self.initialize()
        if attachment.task_id is None:
            return
        if attachment.mode is not TerminalAttachmentMode.WRITE:
            return
        if attachment.owner_user_id is None:
            return

        live_lease = self._load_live_lease(attachment.task_id)
        if live_lease is None:
            return
        if live_lease.status is not TaskTakeoverLeaseStatus.ACTIVE:
            return
        if live_lease.user_id != attachment.owner_user_id:
            return

        now = utc_now()
        self._store_lease(
            replace(
                live_lease,
                status=TaskTakeoverLeaseStatus.GRACE_PENDING,
                grace_started_at=now,
                grace_expires_at=now + timedelta(seconds=self._takeover_disconnect_grace_seconds),
            )
        )
        terminal_binding = self._load_terminal_binding(attachment.task_id)
        if terminal_binding is None:
            return
        self._store_terminal_binding(
            replace(
                terminal_binding,
                binding_status=TaskTerminalBindingStatus.TAKEN_OVER,
                mode=TerminalAttachmentMode.WRITE,
                readonly=False,
                ownership_user_id=attachment.owner_user_id,
                agent_write_state=TaskAgentWriteState.PAUSED_BY_USER,
                updated_at=now,
            )
        )

    def sweep_time_based_state(self) -> None:
        self.initialize()
        now = utc_now()
        for task in self._list_tasks():
            self._refresh_task_bundle(task, now=now)

    def cancel_task(
        self,
        task_id: str,
        app_user_id: str,
    ) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        task, terminal_binding = self.get_task(task_id, app_user_id)
        if terminal_binding is None or task.status in _FINAL_TASK_STATUSES:
            return task, terminal_binding

        environment = self._resolve_environment(task.environment_id)
        binding = self._resolve_user_binding(task.binding_id)
        assert environment is not None
        assert binding is not None
        try:
            self._run_task_runtime_action(task, "interrupt", timeout_seconds=1.0)
        except TaskRuntimeControlError:
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
            window = self._inspect_window(
                binding, environment, terminal_binding, raise_on_error=False
            )
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
                live_lease = self._load_live_lease(task_id)
                if live_lease is not None:
                    self._store_lease(
                        replace(
                            live_lease,
                            status=TaskTakeoverLeaseStatus.RELEASED,
                            released_at=cancelled_at,
                        )
                    )
                cancelled_binding = self._store_terminal_binding(
                    replace(
                        terminal_binding,
                        binding_status=TaskTerminalBindingStatus.COMPLETED,
                        mode=TerminalAttachmentMode.OBSERVE,
                        readonly=True,
                        ownership_user_id=None,
                        agent_write_state=TaskAgentWriteState.RUNNING,
                        window_name=window.window_name
                        if window is not None
                        else terminal_binding.window_name,
                        last_output_at=cancelled_at,
                        archived_at=None,
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
        startup_at = utc_now()
        for task in self._list_tasks():
            self._refresh_task_bundle(task, now=startup_at, startup_reconcile=True)

    def _refresh_task_bundle(
        self,
        task: ManagedTask,
        *,
        now: datetime | None = None,
        startup_reconcile: bool = False,
    ) -> tuple[ManagedTask, TaskTerminalBinding | None]:
        terminal_binding = self._load_terminal_binding(task.task_id)
        if terminal_binding is None:
            return task, None
        refresh_at = now or utc_now()
        live_lease = self._load_live_lease(task.task_id)
        if terminal_binding.binding_status is TaskTerminalBindingStatus.ARCHIVED:
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=refresh_at,
                    )
                )
            return task, terminal_binding

        environment = self._resolve_environment(task.environment_id, raise_on_error=False)
        binding = self._resolve_user_binding(task.binding_id, raise_on_error=False)
        if environment is None:
            failure_at = refresh_at
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=failure_at,
                    )
                )
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
                    binding_status=TaskTerminalBindingStatus.FAILED,
                    mode=TerminalAttachmentMode.OBSERVE,
                    readonly=True,
                    ownership_user_id=None,
                    agent_write_state=TaskAgentWriteState.RUNNING,
                    archived_at=None,
                    updated_at=failure_at,
                )
            )
        if binding is None:
            failure_at = refresh_at
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=failure_at,
                    )
                )
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
                    binding_status=TaskTerminalBindingStatus.FAILED,
                    mode=TerminalAttachmentMode.OBSERVE,
                    readonly=True,
                    ownership_user_id=None,
                    agent_write_state=TaskAgentWriteState.RUNNING,
                    archived_at=None,
                    updated_at=failure_at,
                )
            )
        window = self._inspect_window(binding, environment, terminal_binding, raise_on_error=False)
        if window is None:
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=refresh_at,
                    )
                )
            if task.status in _FINAL_TASK_STATUSES:
                return self._archive_terminal_binding(task, terminal_binding, refresh_at)
            failure_at = refresh_at
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
                    binding_status=TaskTerminalBindingStatus.FAILED,
                    mode=TerminalAttachmentMode.OBSERVE,
                    readonly=True,
                    ownership_user_id=None,
                    agent_write_state=TaskAgentWriteState.RUNNING,
                    updated_at=failure_at,
                )
            )
        if task.status in _FINAL_TASK_STATUSES:
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=refresh_at,
                    )
                )
            return self._refresh_final_task_bundle(
                task,
                terminal_binding,
                binding,
                environment,
                window,
                refresh_at,
            )
        if (
            live_lease is not None
            and live_lease.status is TaskTakeoverLeaseStatus.GRACE_PENDING
            and self._is_grace_lease_expired(live_lease, refresh_at)
            and not startup_reconcile
        ):
            terminal_binding = self._release_takeover(
                task,
                terminal_binding,
                live_lease,
                released_at=refresh_at,
                resume_runtime=True,
            )
            live_lease = None
        if startup_reconcile and live_lease is not None and not window.is_dead:
            live_lease = self._store_lease(
                replace(
                    live_lease,
                    status=TaskTakeoverLeaseStatus.GRACE_PENDING,
                    grace_started_at=refresh_at,
                    grace_expires_at=refresh_at
                    + timedelta(seconds=self._takeover_disconnect_grace_seconds),
                )
            )
        updated_task, updated_binding = self._apply_window_state(
            task,
            terminal_binding,
            window,
            live_lease,
            now=refresh_at,
        )
        if updated_task.status in _FINAL_TASK_STATUSES:
            return self._refresh_final_task_bundle(
                updated_task,
                updated_binding,
                binding,
                environment,
                window,
                refresh_at,
            )
        return updated_task, updated_binding

    def _apply_window_state(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        window: TmuxWindowInfo,
        live_lease: TaskTakeoverLease | None,
        *,
        now: datetime,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
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
            if live_lease is not None:
                self._store_lease(
                    replace(
                        live_lease,
                        status=TaskTakeoverLeaseStatus.RELEASED,
                        released_at=now,
                    )
                )
            updated_binding = self._store_terminal_binding(
                replace(
                    terminal_binding,
                    window_name=window.window_name,
                    binding_status=self._binding_status_for_task(final_status),
                    mode=TerminalAttachmentMode.OBSERVE,
                    readonly=True,
                    ownership_user_id=None,
                    agent_write_state=TaskAgentWriteState.RUNNING,
                    last_output_at=now,
                    archived_at=None,
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
        owner_user_id = live_lease.user_id if live_lease is not None else None
        binding_status = (
            TaskTerminalBindingStatus.TAKEN_OVER
            if live_lease is not None
            else TaskTerminalBindingStatus.RUNNING_OBSERVE
        )
        updated_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                window_name=window.window_name,
                binding_status=binding_status,
                mode=TerminalAttachmentMode.WRITE
                if live_lease is not None
                else TerminalAttachmentMode.OBSERVE,
                readonly=live_lease is None,
                ownership_user_id=owner_user_id,
                agent_write_state=TaskAgentWriteState.PAUSED_BY_USER
                if live_lease is not None
                else TaskAgentWriteState.RUNNING,
                last_output_at=now,
                archived_at=None,
                updated_at=now,
            )
        )
        return updated_task, updated_binding

    def _refresh_final_task_bundle(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        window: TmuxWindowInfo,
        now: datetime,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
        final_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                window_name=window.window_name,
                binding_status=self._binding_status_for_task(task.status),
                mode=TerminalAttachmentMode.OBSERVE,
                readonly=True,
                ownership_user_id=None,
                agent_write_state=TaskAgentWriteState.RUNNING,
                archived_at=None,
                updated_at=now,
            )
        )
        if not self._should_archive_terminal_window(task, now):
            return task, final_binding
        try:
            self._tmux_adapter.kill_window(binding, environment, final_binding.window_id)
        except TmuxCommandError as exc:
            raise TaskOperationError(str(exc)) from exc
        return self._archive_terminal_binding(task, final_binding, now)

    def _archive_terminal_binding(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        archived_at: datetime,
    ) -> tuple[ManagedTask, TaskTerminalBinding]:
        archived_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                binding_status=TaskTerminalBindingStatus.ARCHIVED,
                mode=TerminalAttachmentMode.OBSERVE,
                readonly=True,
                ownership_user_id=None,
                agent_write_state=TaskAgentWriteState.RUNNING,
                archived_at=archived_at,
                updated_at=archived_at,
            )
        )
        return task, archived_binding

    def _should_archive_terminal_window(self, task: ManagedTask, now: datetime) -> bool:
        completed_at = task.completed_at or task.updated_at
        return now >= completed_at + timedelta(seconds=self._final_window_retention_seconds)

    def _is_grace_lease_reclaimable(self, lease: TaskTakeoverLease) -> bool:
        return not self._is_grace_lease_expired(lease, utc_now())

    @staticmethod
    def _is_grace_lease_expired(lease: TaskTakeoverLease, now: datetime) -> bool:
        if lease.status is not TaskTakeoverLeaseStatus.GRACE_PENDING:
            return False
        if lease.grace_expires_at is None:
            return True
        return lease.grace_expires_at <= now

    def _reactivate_grace_lease(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        lease: TaskTakeoverLease,
    ) -> tuple[TaskTerminalBinding, TaskTakeoverLease]:
        reactivated_at = utc_now()
        reactivated_lease = self._store_lease(
            replace(
                lease,
                status=TaskTakeoverLeaseStatus.ACTIVE,
                grace_started_at=None,
                grace_expires_at=None,
                released_at=None,
            )
        )
        reactivated_binding = self._store_terminal_binding(
            replace(
                terminal_binding,
                binding_status=TaskTerminalBindingStatus.TAKEN_OVER,
                mode=TerminalAttachmentMode.WRITE,
                readonly=False,
                ownership_user_id=lease.user_id,
                agent_write_state=TaskAgentWriteState.PAUSED_BY_USER,
                last_takeover_at=reactivated_at,
                archived_at=None,
                updated_at=reactivated_at,
            )
        )
        return reactivated_binding, reactivated_lease

    def _release_takeover(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        lease: TaskTakeoverLease,
        *,
        released_at: datetime,
        resume_runtime: bool,
    ) -> TaskTerminalBinding:
        release_binding = terminal_binding
        if resume_runtime:
            release_binding = self._store_terminal_binding(
                replace(
                    terminal_binding,
                    agent_write_state=TaskAgentWriteState.RESUME_REQUESTED,
                    updated_at=released_at,
                )
            )
            self._run_task_runtime_action(
                task,
                "resume",
                timeout_seconds=self._takeover_ack_timeout_seconds,
            )
        self._store_lease(
            replace(
                lease,
                status=TaskTakeoverLeaseStatus.RELEASED,
                released_at=released_at,
            )
        )
        return self._store_terminal_binding(
            replace(
                release_binding,
                binding_status=self._binding_status_for_task(task.status),
                mode=TerminalAttachmentMode.OBSERVE,
                readonly=True,
                ownership_user_id=None,
                agent_write_state=TaskAgentWriteState.RUNNING,
                archived_at=None,
                updated_at=released_at,
            )
        )

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

    def _build_task_attachment(
        self,
        task: ManagedTask,
        terminal_binding: TaskTerminalBinding,
        *,
        mode: TerminalAttachmentMode,
        readonly: bool,
        owner_user_id: str | None,
    ) -> tuple[ManagedTask, TaskTerminalBinding, TerminalAttachmentTarget]:
        environment = self._resolve_environment(task.environment_id)
        binding = self._resolve_user_binding(task.binding_id)
        assert environment is not None
        assert binding is not None
        window = self._inspect_window(binding, environment, terminal_binding)
        if window is None:
            raise TaskOperationError("Task terminal window is unavailable")
        target = self._build_task_attachment_target(
            task,
            binding,
            environment,
            window.window_name,
            terminal_binding,
            mode=mode,
            readonly=readonly,
            owner_user_id=owner_user_id,
        )
        return task, terminal_binding, target

    def _build_task_attachment_target(
        self,
        task: ManagedTask,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        window_name: str,
        terminal_binding: TaskTerminalBinding,
        *,
        mode: TerminalAttachmentMode,
        readonly: bool,
        owner_user_id: str | None,
    ) -> TerminalAttachmentTarget:
        return TerminalAttachmentTarget(
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
            readonly=readonly,
            mode=mode,
            window_id=terminal_binding.window_id,
            window_name=window_name,
            owner_user_id=owner_user_id,
            task_id=task.task_id,
            binding_status=terminal_binding.binding_status.value,
        )

    def _run_task_runtime_action(
        self,
        task: ManagedTask,
        action: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        environment = self._resolve_environment(task.environment_id)
        binding = self._resolve_user_binding(task.binding_id)
        assert environment is not None
        assert binding is not None
        runtime_dir = runtime_dir_for_task(task.working_directory, task.task_id)
        try:
            payload = self._tmux_adapter.run_task_runtime_control(
                binding,
                environment,
                runtime_dir=runtime_dir,
                action=action,
                timeout_seconds=timeout_seconds,
            )
        except TmuxCommandError as exc:
            raise TaskRuntimeControlError(str(exc)) from exc
        if not bool(payload.get("ok")):
            detail = str(payload.get("detail") or f"Task runtime {action} failed")
            raise TaskRuntimeControlError(detail)
        return payload

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
    def _binding_status_for_task(status: ManagedTaskStatus) -> TaskTerminalBindingStatus:
        if status is ManagedTaskStatus.RUNNING:
            return TaskTerminalBindingStatus.RUNNING_OBSERVE
        if status in {ManagedTaskStatus.COMPLETED, ManagedTaskStatus.CANCELLED}:
            return TaskTerminalBindingStatus.COMPLETED
        return TaskTerminalBindingStatus.FAILED

    @staticmethod
    def _window_name_for(title: str, task_id: str) -> str:
        normalized = _WINDOW_NAME_RE.sub("-", title.strip()).strip("-").lower()
        if not normalized:
            normalized = "task"
        return f"{normalized[:20]}-{task_id[:8]}"

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        statement: str,
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(statement)

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

    def _load_tasks_for_environment(
        self,
        environment_id: str,
    ) -> list[ManagedTask]:
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
                       window_name, status, mode, readonly, ownership_user_id, agent_write_state,
                       pause_requested_at, pause_acknowledged_at, last_takeover_at,
                       last_output_at, archived_at, created_at, updated_at
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
        stored = replace(terminal_binding, created_at=created_at, updated_at=updated_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_terminal_bindings (
                    task_id, binding_id, environment_id, agent_session_name, window_id, window_name,
                    status, mode, readonly, ownership_user_id, agent_write_state,
                    pause_requested_at, pause_acknowledged_at, last_takeover_at,
                    last_output_at, archived_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    binding_id = excluded.binding_id,
                    environment_id = excluded.environment_id,
                    agent_session_name = excluded.agent_session_name,
                    window_id = excluded.window_id,
                    window_name = excluded.window_name,
                    status = excluded.status,
                    mode = excluded.mode,
                    readonly = excluded.readonly,
                    ownership_user_id = excluded.ownership_user_id,
                    agent_write_state = excluded.agent_write_state,
                    pause_requested_at = excluded.pause_requested_at,
                    pause_acknowledged_at = excluded.pause_acknowledged_at,
                    last_takeover_at = excluded.last_takeover_at,
                    last_output_at = excluded.last_output_at,
                    archived_at = excluded.archived_at,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.task_id,
                    stored.binding_id,
                    stored.environment_id,
                    stored.agent_session_name,
                    stored.window_id,
                    stored.window_name,
                    stored.binding_status.value,
                    stored.mode.value,
                    int(stored.readonly),
                    stored.ownership_user_id,
                    stored.agent_write_state.value,
                    stored.pause_requested_at.isoformat()
                    if stored.pause_requested_at is not None
                    else None,
                    stored.pause_acknowledged_at.isoformat()
                    if stored.pause_acknowledged_at is not None
                    else None,
                    stored.last_takeover_at.isoformat()
                    if stored.last_takeover_at is not None
                    else None,
                    stored.last_output_at.isoformat()
                    if stored.last_output_at is not None
                    else None,
                    stored.archived_at.isoformat() if stored.archived_at is not None else None,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )
            connection.commit()
        return stored

    def _load_live_lease(self, task_id: str) -> TaskTakeoverLease | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lease_id, task_id, user_id, status, acquired_at,
                       grace_started_at, grace_expires_at, released_at
                FROM task_takeover_leases
                WHERE task_id = ? AND status IN (?, ?)
                ORDER BY acquired_at DESC
                LIMIT 1
                """,
                (
                    task_id,
                    TaskTakeoverLeaseStatus.ACTIVE.value,
                    TaskTakeoverLeaseStatus.GRACE_PENDING.value,
                ),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_lease(row)

    def _store_lease(self, lease: TaskTakeoverLease) -> TaskTakeoverLease:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_takeover_leases (
                    lease_id, task_id, user_id, status, acquired_at,
                    grace_started_at, grace_expires_at, released_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    user_id = excluded.user_id,
                    status = excluded.status,
                    acquired_at = excluded.acquired_at,
                    grace_started_at = excluded.grace_started_at,
                    grace_expires_at = excluded.grace_expires_at,
                    released_at = excluded.released_at
                """,
                (
                    lease.lease_id,
                    lease.task_id,
                    lease.user_id,
                    lease.status.value,
                    lease.acquired_at.isoformat(),
                    lease.grace_started_at.isoformat()
                    if lease.grace_started_at is not None
                    else None,
                    lease.grace_expires_at.isoformat()
                    if lease.grace_expires_at is not None
                    else None,
                    lease.released_at.isoformat() if lease.released_at is not None else None,
                ),
            )
            connection.commit()
        return lease

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
        raw_status = row["status"]
        if raw_status in {item.value for item in TaskTerminalBindingStatus}:
            binding_status = TaskTerminalBindingStatus(raw_status)
        else:
            legacy_status = ManagedTaskStatus(raw_status)
            if legacy_status is ManagedTaskStatus.RUNNING:
                binding_status = TaskTerminalBindingStatus.RUNNING_OBSERVE
            elif legacy_status in {ManagedTaskStatus.COMPLETED, ManagedTaskStatus.CANCELLED}:
                binding_status = TaskTerminalBindingStatus.COMPLETED
            else:
                binding_status = TaskTerminalBindingStatus.FAILED
        agent_write_state_raw = row["agent_write_state"] or TaskAgentWriteState.RUNNING.value
        return TaskTerminalBinding(
            task_id=row["task_id"],
            binding_id=row["binding_id"],
            environment_id=row["environment_id"],
            agent_session_name=row["agent_session_name"],
            window_id=row["window_id"],
            window_name=row["window_name"],
            binding_status=binding_status,
            mode=TerminalAttachmentMode(row["mode"]),
            readonly=bool(row["readonly"]),
            ownership_user_id=row["ownership_user_id"],
            agent_write_state=TaskAgentWriteState(agent_write_state_raw),
            pause_requested_at=_parse_datetime(row["pause_requested_at"]),
            pause_acknowledged_at=_parse_datetime(row["pause_acknowledged_at"]),
            last_takeover_at=_parse_datetime(row["last_takeover_at"]),
            last_output_at=_parse_datetime(row["last_output_at"]),
            archived_at=_parse_datetime(row["archived_at"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )

    @staticmethod
    def _row_to_lease(row: sqlite3.Row) -> TaskTakeoverLease:
        return TaskTakeoverLease(
            lease_id=row["lease_id"],
            task_id=row["task_id"],
            user_id=row["user_id"],
            status=TaskTakeoverLeaseStatus(row["status"]),
            acquired_at=datetime.fromisoformat(row["acquired_at"]),
            grace_started_at=_parse_datetime(row["grace_started_at"]),
            grace_expires_at=_parse_datetime(row["grace_expires_at"]),
            released_at=_parse_datetime(row["released_at"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

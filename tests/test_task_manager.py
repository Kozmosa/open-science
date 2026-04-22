from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ainrf.environments.service import InMemoryEnvironmentService
from ainrf.tasks.models import (
    ManagedTask,
    ManagedTaskStatus,
    TaskAgentWriteState,
    TaskTakeoverLeaseStatus,
    TaskTerminalBinding,
    TaskTerminalBindingStatus,
)
from ainrf.tasks.service import TaskConflictError, TaskManager
from ainrf.terminal.attachments import TerminalAttachmentBroker
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter, TmuxWindowInfo


def make_task_manager(
    tmp_path: Path,
    *,
    takeover_disconnect_grace_seconds: float = 5.0,
    final_window_retention_seconds: float = 60.0 * 60.0,
) -> tuple[TaskManager, SessionManager, InMemoryEnvironmentService]:
    environment_service = InMemoryEnvironmentService()
    session_manager = SessionManager(
        state_root=tmp_path,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(tmp_path),
        default_shell="/bin/bash",
    )
    manager = TaskManager(
        state_root=tmp_path,
        environment_service=environment_service,
        session_manager=session_manager,
        tmux_adapter=session_manager.tmux_adapter,
        takeover_disconnect_grace_seconds=takeover_disconnect_grace_seconds,
        final_window_retention_seconds=final_window_retention_seconds,
    )
    return manager, session_manager, environment_service


def configure_task_runtime(
    manager: TaskManager,
    monkeypatch: pytest.MonkeyPatch,
    *,
    window_state: dict[str, TmuxWindowInfo | None],
    runtime_actions: list[str],
) -> None:
    adapter = manager._tmux_adapter
    monkeypatch.setattr(adapter, "ensure_agent_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        adapter,
        "create_window",
        lambda *args, **kwargs: TmuxWindowInfo(window_id="@1", window_name="train-task"),
    )
    monkeypatch.setattr(
        adapter,
        "inspect_window",
        lambda *args, **kwargs: window_state["window"],
    )
    monkeypatch.setattr(
        adapter,
        "build_window_attach_command",
        lambda *args, **kwargs: (
            "tmux",
            "attach-session",
            "-t",
            "agent-session",
            ";",
            "select-window",
            "-t",
            "@1",
        ),
    )
    monkeypatch.setattr(
        adapter,
        "run_task_runtime_control",
        lambda *args, action, **kwargs: (
            runtime_actions.append(action)
            or {"ok": True, "state": "paused" if action == "pause" else "running"}
        ),
    )


def create_running_task(
    manager: TaskManager,
    environment_service: InMemoryEnvironmentService,
) -> tuple[ManagedTask, TaskTerminalBinding]:
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="127.0.0.1",
        default_workdir="/workspace/project",
    )
    return manager.create_task(
        "browser-user",
        environment,
        title="Train Task",
        command="python train.py",
        working_directory="/workspace/project",
    )


def test_write_disconnect_enters_grace_and_same_user_open_reclaims_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _session_manager, environment_service = make_task_manager(tmp_path)
    runtime_actions: list[str] = []
    window_state: dict[str, TmuxWindowInfo | None] = {
        "window": TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False)
    }
    configure_task_runtime(
        manager,
        monkeypatch,
        window_state=window_state,
        runtime_actions=runtime_actions,
    )
    task, _binding = create_running_task(manager, environment_service)
    broker = TerminalAttachmentBroker()

    _, taken_over_binding, target = manager.takeover(task.task_id, "browser-user")
    attachment = broker.create_attachment("http://testserver/", target)

    manager.handle_task_attachment_disconnect(attachment)

    grace_lease = manager._load_live_lease(task.task_id)
    assert grace_lease is not None
    assert grace_lease.status is TaskTakeoverLeaseStatus.GRACE_PENDING
    assert grace_lease.grace_started_at is not None
    assert grace_lease.grace_expires_at is not None
    assert runtime_actions == ["pause"]

    _, reopened_binding, reopened_target = manager.open_task_terminal(task.task_id, "browser-user")

    reactivated_lease = manager._load_live_lease(task.task_id)
    assert taken_over_binding.ownership_user_id == "browser-user"
    assert reopened_binding.ownership_user_id == "browser-user"
    assert reopened_target.mode == "write"
    assert reopened_target.readonly is False
    assert reactivated_lease is not None
    assert reactivated_lease.status is TaskTakeoverLeaseStatus.ACTIVE
    assert reactivated_lease.grace_started_at is None
    assert reactivated_lease.grace_expires_at is None


def test_grace_conflicts_other_user_and_sweep_releases_takeover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = datetime(2026, 4, 22, 8, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "ainrf.tasks.service.utc_now",
        lambda: current_time,
    )
    manager, _session_manager, environment_service = make_task_manager(tmp_path)
    runtime_actions: list[str] = []
    window_state: dict[str, TmuxWindowInfo | None] = {
        "window": TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False)
    }
    configure_task_runtime(
        manager,
        monkeypatch,
        window_state=window_state,
        runtime_actions=runtime_actions,
    )
    task, _binding = create_running_task(manager, environment_service)
    broker = TerminalAttachmentBroker()

    _, _taken_over_binding, target = manager.takeover(task.task_id, "browser-user")
    attachment = broker.create_attachment("http://testserver/", target)
    manager.handle_task_attachment_disconnect(attachment)

    with pytest.raises(TaskConflictError):
        manager.takeover(task.task_id, "other-user")

    current_time = current_time + timedelta(seconds=6)
    manager.sweep_time_based_state()

    refreshed_binding = manager.get_task_terminal_binding(task.task_id, "browser-user")
    released_lease = manager._load_live_lease(task.task_id)

    assert runtime_actions == ["pause", "resume"]
    assert released_lease is None
    assert refreshed_binding.binding_status is TaskTerminalBindingStatus.RUNNING_OBSERVE
    assert refreshed_binding.ownership_user_id is None
    assert refreshed_binding.agent_write_state is TaskAgentWriteState.RUNNING


def test_reconcile_moves_running_active_lease_into_fresh_grace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _session_manager, environment_service = make_task_manager(tmp_path)
    runtime_actions: list[str] = []
    window_state: dict[str, TmuxWindowInfo | None] = {
        "window": TmuxWindowInfo(window_id="@1", window_name="train-task", is_dead=False)
    }
    configure_task_runtime(
        manager,
        monkeypatch,
        window_state=window_state,
        runtime_actions=runtime_actions,
    )
    task, _binding = create_running_task(manager, environment_service)
    manager.takeover(task.task_id, "browser-user")

    restored_session_manager = SessionManager(
        state_root=tmp_path,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(tmp_path),
        default_shell="/bin/bash",
    )
    restored_manager = TaskManager(
        state_root=tmp_path,
        environment_service=environment_service,
        session_manager=restored_session_manager,
        tmux_adapter=restored_session_manager.tmux_adapter,
    )
    monkeypatch.setattr(
        restored_manager._tmux_adapter,
        "inspect_window",
        lambda *args, **kwargs: window_state["window"],
    )
    startup_at = datetime(2026, 4, 22, 9, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("ainrf.tasks.service.utc_now", lambda: startup_at)

    restored_manager.reconcile()

    reconciled_binding = restored_manager.get_task_terminal_binding(task.task_id, "browser-user")
    reconciled_lease = restored_manager._load_live_lease(task.task_id)

    assert runtime_actions == ["pause"]
    assert reconciled_binding.binding_status is TaskTerminalBindingStatus.TAKEN_OVER
    assert reconciled_binding.ownership_user_id == "browser-user"
    assert reconciled_lease is not None
    assert reconciled_lease.status is TaskTakeoverLeaseStatus.GRACE_PENDING
    assert reconciled_lease.grace_started_at == startup_at
    assert reconciled_lease.grace_expires_at == startup_at + timedelta(seconds=5)


def test_final_task_window_missing_is_archived_instead_of_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _session_manager, environment_service = make_task_manager(tmp_path)
    runtime_actions: list[str] = []
    window_state: dict[str, TmuxWindowInfo | None] = {"window": None}
    configure_task_runtime(
        manager,
        monkeypatch,
        window_state=window_state,
        runtime_actions=runtime_actions,
    )
    task, binding = create_running_task(manager, environment_service)
    completed_at = datetime(2026, 4, 22, 7, 0, 0, tzinfo=UTC)
    manager._store_task(
        replace(
            task,
            status=ManagedTaskStatus.COMPLETED,
            updated_at=completed_at,
            completed_at=completed_at,
            exit_code=0,
        )
    )
    manager._store_terminal_binding(
        replace(
            binding,
            binding_status=TaskTerminalBindingStatus.COMPLETED,
            updated_at=completed_at,
        )
    )

    refreshed_task, refreshed_binding = manager.get_task(task.task_id, "browser-user")

    assert refreshed_task.status is ManagedTaskStatus.COMPLETED
    assert refreshed_binding is not None
    assert refreshed_binding.binding_status is TaskTerminalBindingStatus.ARCHIVED


def test_completed_task_older_than_retention_kills_window_and_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _session_manager, environment_service = make_task_manager(
        tmp_path,
        final_window_retention_seconds=60.0,
    )
    runtime_actions: list[str] = []
    window_state: dict[str, TmuxWindowInfo | None] = {
        "window": TmuxWindowInfo(
            window_id="@1", window_name="train-task", is_dead=True, exit_status=0
        )
    }
    configure_task_runtime(
        manager,
        monkeypatch,
        window_state=window_state,
        runtime_actions=runtime_actions,
    )
    task, binding = create_running_task(manager, environment_service)
    completed_at = datetime(2026, 4, 22, 7, 0, 0, tzinfo=UTC)
    now = completed_at + timedelta(minutes=61)
    manager._store_task(
        replace(
            task,
            status=ManagedTaskStatus.COMPLETED,
            updated_at=completed_at,
            completed_at=completed_at,
            exit_code=0,
        )
    )
    manager._store_terminal_binding(
        replace(
            binding,
            binding_status=TaskTerminalBindingStatus.COMPLETED,
            updated_at=completed_at,
        )
    )
    killed_windows: list[str] = []
    monkeypatch.setattr(
        manager._tmux_adapter,
        "kill_window",
        lambda binding, environment, window_id: killed_windows.append(window_id),
    )
    monkeypatch.setattr("ainrf.tasks.service.utc_now", lambda: now)

    refreshed_task, refreshed_binding = manager.get_task(task.task_id, "browser-user")

    assert refreshed_task.status is ManagedTaskStatus.COMPLETED
    assert refreshed_binding is not None
    assert refreshed_binding.binding_status is TaskTerminalBindingStatus.ARCHIVED
    assert killed_windows == ["@1"]
    assert runtime_actions == []

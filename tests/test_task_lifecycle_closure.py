"""B6 TaskApplicationService lifecycle closure contracts."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService, TaskApplicationService
from ainrf.domain.service import DomainConflictError, DomainPermissionError
from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


@dataclass(frozen=True, slots=True)
class _TaskScope:
    owner: dict[str, object]
    environment_id: str
    project_id: str
    workspace_id: str
    context_version_id: str


def _member(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def _project_with_context(
    state_root: Path,
    domain: DomainService,
    owner: dict[str, object],
    *,
    label: str,
) -> tuple[str, str]:
    project = domain.create_project(owner, name=f"{label} Project")
    project_id = str(project["project_id"])
    context = ProjectContextService(state_root)
    context.save_draft(project_id, f"{label} context", owner)
    version = context.publish(project_id, owner, idempotency_key=f"publish-{label}")
    return project_id, str(version["context_version_id"])


def _task_scope(
    state_root: Path,
    tmp_path: Path,
    *,
    owner_id: str = "owner",
    label: str = "source",
) -> _TaskScope:
    owner = _member(owner_id)
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = DomainService(state_root)
    environment = domain.create_environment(
        admin,
        alias=f"host-{label}",
        display_name=f"Host {label}",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id=owner_id,
        max_tasks=None,
        granted_by="admin",
        reason="task lifecycle contract",
    )
    project_id, context_version_id = _project_with_context(state_root, domain, owner, label=label)
    workspace_path = tmp_path / f"workspace-{label}"
    workspace_path.mkdir()
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label=f"{label} Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, owner, idempotency_key=f"attach-{label}")
    return _TaskScope(
        owner=owner,
        environment_id=environment_id,
        project_id=project_id,
        workspace_id=workspace_id,
        context_version_id=context_version_id,
    )


def _create_task(
    service: TaskApplicationService,
    scope: _TaskScope,
    *,
    idempotency_key: str,
    prompt: str = "Investigate the lifecycle.",
) -> dict[str, str]:
    return service.create_task(
        scope.owner,
        project_id=scope.project_id,
        workspace_id=scope.workspace_id,
        title="Lifecycle task",
        prompt=prompt,
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key=idempotency_key,
    )


def test_task_create_idempotency_is_actor_scoped_and_request_bound(
    state_root: Path, tmp_path: Path
) -> None:
    first_scope = _task_scope(state_root, tmp_path, owner_id="owner-a", label="owner-a")
    second_scope = _task_scope(state_root, tmp_path, owner_id="owner-b", label="owner-b")
    tasks = TaskApplicationService(state_root)

    first = _create_task(tasks, first_scope, idempotency_key="shared-create")
    assert _create_task(tasks, first_scope, idempotency_key="shared-create") == first

    with pytest.raises(DomainConflictError, match="different request"):
        _create_task(
            tasks,
            first_scope,
            idempotency_key="shared-create",
            prompt="This is a distinct request.",
        )

    second = _create_task(tasks, second_scope, idempotency_key="shared-create")
    assert second["task_id"] != first["task_id"]


def test_task_application_fails_closed_during_domain_maintenance(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="task application maintenance test")

    with pytest.raises(MaintenanceModeError, match="paused for maintenance"):
        _create_task(TaskApplicationService(state_root), scope, idempotency_key="blocked")


def test_context_writers_use_the_same_maintenance_fence_as_task_lifecycle(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="context-maintenance-create")
    context = ProjectContextService(state_root)
    context.save_draft(scope.project_id, "Revised context before maintenance", scope.owner)
    context.publish(
        scope.project_id,
        scope.owner,
        idempotency_key="context-maintenance-publish",
    )
    preview = tasks.preview_task_context_update(created["task_id"], scope.project_id, scope.owner)
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        before = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = ?",
            (created["task_id"],),
        ).fetchone()
    assert before is not None

    DomainMaintenanceService(state_root).enter(
        actor_id="operator", reason="context maintenance fence test"
    )

    with pytest.raises(MaintenanceModeError, match="paused for maintenance"):
        tasks.preview_task_context_update(created["task_id"], scope.project_id, scope.owner)
    with pytest.raises(MaintenanceModeError, match="paused for maintenance"):
        tasks.confirm_task_context_update(
            created["task_id"],
            scope.project_id,
            str(preview["preview_id"]),
            scope.owner,
            idempotency_key="context-maintenance-confirm",
        )
    with pytest.raises(MaintenanceModeError, match="paused for maintenance"):
        context.save_draft(scope.project_id, "Forbidden draft", scope.owner)

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        confirmed = conn.execute(
            """SELECT confirmed_snapshot_id FROM task_context_update_previews
               WHERE preview_id = ?""",
            (preview["preview_id"],),
        ).fetchone()
        task = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = ?",
            (created["task_id"],),
        ).fetchone()

    assert confirmed is not None
    assert confirmed["confirmed_snapshot_id"] is None
    assert task is not None
    assert task["project_context_snapshot_id"] == before["project_context_snapshot_id"]


def test_project_archive_blocks_retry_and_cancels_only_unstarted_dispatch(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-project-archive")

    archived = tasks.archive_project(
        scope.project_id,
        scope.owner,
        reason="project archived by owner",
        idempotency_key="archive-project",
    )
    assert (
        tasks.archive_project(
            scope.project_id,
            scope.owner,
            reason="project archived by owner",
            idempotency_key="archive-project",
        )
        == archived
    )
    with pytest.raises(DomainConflictError, match="different request"):
        tasks.archive_project(
            scope.project_id,
            scope.owner,
            reason="a different project archive reason",
            idempotency_key="archive-project",
        )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        project = conn.execute(
            "SELECT status, archived_at FROM projects WHERE project_id = ?", (scope.project_id,)
        ).fetchone()
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (created["attempt_id"],)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status, launch_state FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()

    assert project is not None
    assert project["status"] == "archived"
    assert project["archived_at"] is not None
    assert attempt is not None
    assert attempt["status"] in {"cancelled", "stopped_by_project_archive"}
    assert dispatch is not None
    assert dispatch["status"] == "cancelled"
    assert dispatch["launch_state"] == "none"
    with pytest.raises(DomainConflictError, match="archived"):
        tasks.retry_task(created["task_id"], scope.owner, idempotency_key="retry-archived-project")


def test_project_unarchive_is_idempotent_and_never_requeues_stopped_work(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-unarchive")
    tasks.archive_project(
        scope.project_id,
        scope.owner,
        reason="temporary archive",
        idempotency_key="archive-temporary-project",
    )

    tasks.unarchive_project(
        scope.project_id,
        scope.owner,
        idempotency_key="unarchive-project",
    )
    tasks.unarchive_project(
        scope.project_id,
        scope.owner,
        idempotency_key="unarchive-project",
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        project = conn.execute(
            "SELECT status, archived_at FROM projects WHERE project_id = ?", (scope.project_id,)
        ).fetchone()
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (created["attempt_id"],)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()

    assert project is not None
    assert (project["status"], project["archived_at"]) == ("active", None)
    assert attempt is not None
    assert attempt["status"] != "queued"
    assert dispatch is not None
    assert dispatch["status"] == "cancelled"


def test_domain_service_project_archive_uses_lifecycle_transaction(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-domain-project-archive")

    DomainService(state_root).archive_project(
        scope.project_id,
        scope.owner,
        reason="compatibility facade archive",
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (created["attempt_id"],)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()

    assert attempt is not None
    assert attempt["status"] == "cancelled"
    assert dispatch is not None
    assert dispatch["status"] == "cancelled"


def test_task_archive_is_reversible_without_implicitly_creating_an_attempt(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-task-archive")

    tasks.archive_task(
        created["task_id"],
        scope.owner,
        reason="user archived task",
        idempotency_key="archive-task",
    )
    tasks.unarchive_task(
        created["task_id"],
        scope.owner,
        idempotency_key="unarchive-task",
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task = conn.execute(
            "SELECT archived_at, archive_reason, latest_attempt_id FROM tasks WHERE task_id = ?",
            (created["task_id"],),
        ).fetchone()
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM agent_task_attempts WHERE task_id = ?", (created["task_id"],)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()

    assert task is not None
    assert task["archived_at"] is None
    assert task["archive_reason"] is None
    assert task["latest_attempt_id"] == created["attempt_id"]
    assert attempt_count is not None
    assert attempt_count[0] == 1
    assert dispatch is not None
    assert dispatch["status"] == "cancelled"


def test_resume_keeps_the_same_paused_attempt_and_records_a_durable_control_request(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-resume")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'paused' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute("UPDATE tasks SET status = 'paused' WHERE task_id = ?", (created["task_id"],))
        conn.commit()

    resumed = tasks.resume_task(
        created["task_id"], scope.owner, idempotency_key="resume-paused-attempt"
    )

    assert resumed["attempt_id"] == created["attempt_id"]
    assert resumed["action"] == "resume"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM agent_task_attempts WHERE task_id = ?", (created["task_id"],)
        ).fetchone()
        control = conn.execute(
            "SELECT action, status FROM task_attempt_control_requests WHERE control_request_id = ?",
            (resumed["control_request_id"],),
        ).fetchone()

    assert attempt_count is not None
    assert attempt_count[0] == 1
    assert control is not None
    assert (control["action"], control["status"]) == ("resume", "requested")


def test_resume_rejects_a_runtime_that_has_not_paused(state_root: Path, tmp_path: Path) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-invalid-resume")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'running' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute("UPDATE tasks SET status = 'running' WHERE task_id = ?", (created["task_id"],))
        conn.commit()

    with pytest.raises(DomainConflictError, match="not paused"):
        tasks.resume_task(
            created["task_id"],
            scope.owner,
            idempotency_key="invalid-running-resume",
        )


def test_terminal_continuation_creates_an_attempt_with_the_durable_follow_up_input(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(
        tasks,
        scope,
        idempotency_key="create-before-terminal-continuation",
        prompt="Original research request.",
    )
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'failed' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute(
            "UPDATE task_dispatch_outbox SET status = 'failed' WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        )
        conn.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (created["task_id"],))
        conn.commit()

    continued = tasks.continue_task(
        created["task_id"],
        scope.owner,
        prompt="Please compare the two methods.",
        idempotency_key="continue-terminal-attempt",
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            """SELECT trigger, context_snapshot_id, message_start_seq, message_end_seq
               FROM agent_task_attempts WHERE attempt_id = ?""",
            (continued["attempt_id"],),
        ).fetchone()
        snapshot = conn.execute(
            "SELECT content FROM context_snapshots WHERE context_snapshot_id = ?",
            (continued["context_snapshot_id"],),
        ).fetchone()
        message = conn.execute(
            "SELECT content FROM task_outputs WHERE task_id = ? AND seq = ?",
            (created["task_id"], continued["message_sequence"]),
        ).fetchone()

    assert attempt is not None
    assert attempt["trigger"] == "continue"
    assert attempt["context_snapshot_id"] == continued["context_snapshot_id"]
    assert (attempt["message_start_seq"], attempt["message_end_seq"]) == (
        continued["message_sequence"],
        continued["message_sequence"],
    )
    assert snapshot is not None
    assert "Original research request." in snapshot["content"]
    assert "Please compare the two methods." in snapshot["content"]
    assert message is not None
    assert "Please compare the two methods." in message["content"]


def test_cancel_starting_attempt_persists_control_instead_of_claiming_it_cancelled(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-starting-cancel")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'starting' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute(
            """UPDATE task_dispatch_outbox
               SET status = 'claimed', launch_state = 'starting', claim_token = 'test-token',
                   dispatcher_id = 'test-dispatcher', claim_expires_at = '2099-01-01T00:00:00+00:00',
                   runtime_launch_key = 'test-launch-key'
               WHERE dispatch_id = ?""",
            (created["dispatch_id"],),
        )
        conn.commit()

    cancelled = tasks.cancel_task(
        created["task_id"],
        scope.owner,
        reason="user requested cancellation",
        idempotency_key="cancel-starting-attempt",
    )

    assert cancelled["status"] == "requested"
    assert cancelled["action"] == "cancel"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        attempt = conn.execute(
            "SELECT status, stop_requested_at FROM agent_task_attempts WHERE attempt_id = ?",
            (created["attempt_id"],),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status, launch_state FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()

    assert attempt is not None
    assert attempt["status"] == "starting"
    assert attempt["stop_requested_at"] is not None
    assert dispatch is not None
    assert (dispatch["status"], dispatch["launch_state"]) == ("claimed", "starting")


def test_cancel_queued_attempt_updates_the_task_projection(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-queued-cancel")

    cancelled = tasks.cancel_task(
        created["task_id"],
        scope.owner,
        reason="cancel queued work",
        idempotency_key="cancel-queued-attempt",
    )

    assert cancelled["status"] == "cancelled"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task = conn.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (created["task_id"],)
        ).fetchone()
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (created["attempt_id"],)
        ).fetchone()

    assert task is not None
    assert task["status"] == "cancelled"
    assert attempt is not None
    assert attempt["status"] == "cancelled"


def test_launch_unknown_attempt_cannot_be_retried_without_explicit_reconciliation(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-unknown-retry")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'launch_unknown' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute(
            "UPDATE tasks SET status = 'launch_unknown' WHERE task_id = ?", (created["task_id"],)
        )
        conn.commit()

    with pytest.raises(DomainConflictError, match="active Attempt"):
        tasks.retry_task(created["task_id"], scope.owner, idempotency_key="retry-launch-unknown")


def test_retry_and_move_require_current_workspace_ownership(
    state_root: Path, tmp_path: Path
) -> None:
    source = _task_scope(state_root, tmp_path)
    domain = DomainService(state_root)
    target_project_id, target_context_version_id = _project_with_context(
        state_root, domain, source.owner, label="ownership-target"
    )
    domain.attach_workspace(
        target_project_id,
        source.workspace_id,
        source.owner,
        idempotency_key="attach-ownership-workspace",
    )
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, source, idempotency_key="create-before-ownership-change")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'failed' WHERE attempt_id = ?",
            (created["attempt_id"],),
        )
        conn.execute(
            "UPDATE task_dispatch_outbox SET status = 'failed' WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        )
        conn.execute(
            "UPDATE workspaces SET owner_user_id = 'other-owner' WHERE workspace_id = ?",
            (source.workspace_id,),
        )
        conn.commit()

    with pytest.raises(DomainPermissionError, match="Workspace owner"):
        tasks.retry_task(created["task_id"], source.owner, idempotency_key="retry-after-transfer")
    with pytest.raises(DomainPermissionError, match="Workspace owner"):
        tasks.move_task(
            created["task_id"],
            source.owner,
            project_id=target_project_id,
            context_version_id=target_context_version_id,
            idempotency_key="move-after-transfer",
        )


def test_move_preserves_workspace_and_fork_changes_workspace_with_derived_from(
    state_root: Path, tmp_path: Path
) -> None:
    source = _task_scope(state_root, tmp_path)
    domain = DomainService(state_root)
    target_project_id, target_context_version_id = _project_with_context(
        state_root, domain, source.owner, label="target"
    )
    domain.attach_workspace(
        target_project_id,
        source.workspace_id,
        source.owner,
        idempotency_key="attach-source-workspace-to-target",
    )
    second_workspace_path = tmp_path / "workspace-fork"
    second_workspace_path.mkdir()
    second_workspace = domain.create_workspace(
        source.owner,
        environment_id=source.environment_id,
        canonical_path=str(second_workspace_path),
        label="Fork Workspace",
    )
    second_workspace_id = str(second_workspace["workspace_id"])
    domain.attach_workspace(
        target_project_id,
        second_workspace_id,
        source.owner,
        idempotency_key="attach-fork-workspace-to-target",
    )
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, source, idempotency_key="create-before-move")

    moved = tasks.move_task(
        created["task_id"],
        source.owner,
        project_id=target_project_id,
        context_version_id=target_context_version_id,
        idempotency_key="move-task",
    )
    replayed_move = tasks.move_task(
        created["task_id"],
        source.owner,
        project_id=target_project_id,
        context_version_id=target_context_version_id,
        idempotency_key="move-task",
    )
    forked = tasks.fork_task(
        created["task_id"],
        source.owner,
        workspace_id=second_workspace_id,
        prompt="Fork with a different working directory.",
        title="Forked lifecycle task",
        idempotency_key="fork-task",
    )

    assert moved == replayed_move
    assert moved["task_id"] == created["task_id"]
    assert forked["task_id"] != created["task_id"]
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        moved_task = conn.execute(
            "SELECT project_id, workspace_id, project_context_version_id FROM tasks WHERE task_id = ?",
            (created["task_id"],),
        ).fetchone()
        forked_task = conn.execute(
            "SELECT project_id, workspace_id FROM tasks WHERE task_id = ?", (forked["task_id"],)
        ).fetchone()
        relationship = conn.execute(
            """SELECT relationship_type FROM task_relationships
               WHERE source_task_id = ? AND target_task_id = ?""",
            (forked["task_id"], created["task_id"]),
        ).fetchone()

    assert moved_task is not None
    assert (
        moved_task["project_id"],
        moved_task["workspace_id"],
        moved_task["project_context_version_id"],
    ) == (target_project_id, source.workspace_id, target_context_version_id)
    assert forked_task is not None
    assert (forked_task["project_id"], forked_task["workspace_id"]) == (
        target_project_id,
        second_workspace_id,
    )
    assert relationship is not None
    assert relationship["relationship_type"] == "derived_from"


def test_context_preview_and_confirm_are_owned_by_task_application_service(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path)
    tasks = TaskApplicationService(state_root)
    created = _create_task(tasks, scope, idempotency_key="create-before-context-update")
    context = ProjectContextService(state_root)
    context.save_draft(scope.project_id, "Updated lifecycle context", scope.owner)
    second_version = context.publish(
        scope.project_id,
        scope.owner,
        idempotency_key="publish-context-update",
    )

    preview = tasks.preview_task_context_update(created["task_id"], scope.project_id, scope.owner)
    confirmed = tasks.confirm_task_context_update(
        created["task_id"],
        scope.project_id,
        str(preview["preview_id"]),
        scope.owner,
        idempotency_key="confirm-context-update",
    )
    replay = tasks.confirm_task_context_update(
        created["task_id"],
        scope.project_id,
        str(preview["preview_id"]),
        scope.owner,
        idempotency_key="confirm-context-update",
    )

    assert preview["task_id"] == created["task_id"]
    assert preview["project_id"] == scope.project_id
    assert preview["diff"]
    assert confirmed == replay
    assert confirmed["context_version_id"] == second_version["context_version_id"]
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        queued_attempt = conn.execute(
            "SELECT context_snapshot_id FROM agent_task_attempts WHERE attempt_id = ?",
            (created["attempt_id"],),
        ).fetchone()

    assert queued_attempt is not None
    assert queued_attempt["context_snapshot_id"] == confirmed["context_snapshot_id"]

"""B4 Project Context assembly, provenance, and Task pinning contracts."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import cast

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService
from ainrf.domain.context import ContextAssembler, ContextSource
from ainrf.domain.service import DomainConflictError, DomainPermissionError

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _user(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def _legacy_task(
    state_root: Path, project_id: str, *, owner_user_id: str = "owner"
) -> tuple[AgenticResearcherService, str]:
    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    task = tasks.create_task(
        project_id,
        "workspace-missing",
        "environment-missing",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "Investigate the source record.",
        owner_user_id,
    )
    return tasks, task.task_id


def test_assembler_order_budget_and_fingerprint_are_deterministic() -> None:
    assembler = ContextAssembler(byte_budget=72, platform_constraints="platform")
    sources = (
        assembler.platform_source(),
        ContextSource("project_brief", "version-1", "brief-sha", "Project Brief", "project"),
        ContextSource(
            "workspace_context", "workspace-1", "workspace-v1", "Workspace Context", "workspace"
        ),
        ContextSource("task_request", "task-1", "request-sha", "Task Request", "request"),
    )

    first = assembler.assemble(sources)
    second = assembler.assemble(sources)

    assert first.fingerprint == second.fingerprint
    assert len(first.content.encode("utf-8")) <= 72
    assert [entry["source_type"] for entry in first.source_manifest] == [
        "platform_constraints",
        "project_brief",
        "workspace_context",
        "task_request",
    ]
    assert first.truncated is True
    with pytest.raises(ValueError, match="required fixed order"):
        assembler.assemble(tuple(reversed(sources)))


def test_candidate_acceptance_changes_only_draft_and_publish_requires_capability(
    state_root: Path,
) -> None:
    owner = _user("owner")
    editor = _user("editor")
    domain = DomainService(state_root)
    context = ProjectContextService(state_root)
    project_id = str(domain.create_project(owner, name="Context project")["project_id"])
    domain.add_member(project_id, "editor", "editor", False, owner)

    context.save_draft(project_id, "active brief", owner)
    first = context.publish(project_id, owner, idempotency_key="publish-first")
    candidate = context.create_candidate(
        project_id,
        "candidate evidence",
        editor,
        source_metadata={"origin": "task-output"},
    )
    accepted = context.accept_candidate(project_id, str(candidate["candidate_id"]), editor)
    accepted_candidate = cast(dict[str, object], accepted["candidate"])

    assert accepted_candidate["status"] == "accepted"
    state = context.get_context(project_id, owner)
    active_version = cast(dict[str, object], state["active_version"])
    draft = cast(dict[str, object], state["draft"])
    assert active_version["context_version_id"] == first["context_version_id"]
    assert "candidate evidence" in str(draft["content"])
    with pytest.raises(DomainPermissionError):
        context.publish(project_id, editor, idempotency_key="editor-cannot-publish")

    domain.add_member(project_id, "editor", "editor", True, owner)
    second = context.publish(project_id, editor, idempotency_key="editor-publishes")
    assert second["context_version_id"] != first["context_version_id"]
    assert "candidate evidence" in str(second["content"])
    context.save_draft(project_id, "a changed draft", editor)
    with pytest.raises(DomainConflictError, match="different request"):
        context.publish(project_id, editor, idempotency_key="editor-publishes")


def test_task_context_preview_confirm_is_idempotent_and_started_attempt_never_drifts(
    state_root: Path,
) -> None:
    owner = _user("owner")
    domain = DomainService(state_root)
    context = ProjectContextService(state_root)
    project_id = str(domain.create_project(owner, name="Task context project")["project_id"])
    context.save_draft(project_id, "first brief", owner)
    first = context.publish(project_id, owner, idempotency_key="first")
    tasks, task_id = _legacy_task(state_root, project_id)
    original_snapshot_id = context.pin_active_context(task_id, project_id)
    execution_context = tasks._build_execution_context(tasks.get_task(task_id))
    assert "## Project Brief\nfirst brief" in execution_context.rendered_prompt
    assert "## Task Request\nInvestigate the source record." in execution_context.rendered_prompt

    context.save_draft(project_id, "second brief", owner)
    second = context.publish(project_id, owner, idempotency_key="second")
    preview = context.preview_task_context_update(task_id, project_id, owner)
    current = cast(dict[str, object], preview["current"])
    proposed = cast(dict[str, object], preview["proposed"])
    assert current["context_snapshot_id"] == original_snapshot_id
    assert proposed["context_version_id"] == second["context_version_id"]
    assert "second brief" in str(preview["diff"])

    confirmed = context.confirm_task_context_update(
        task_id,
        project_id,
        str(preview["preview_id"]),
        owner,
        idempotency_key="confirm-second",
    )
    repeated = context.confirm_task_context_update(
        task_id,
        project_id,
        str(preview["preview_id"]),
        owner,
        idempotency_key="confirm-second",
    )
    assert repeated == confirmed
    assert confirmed["context_snapshot_id"] != original_snapshot_id

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            """INSERT INTO agent_task_attempts
               (attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, started_at, created_at)
               VALUES ('attempt-started', ?, 1, 'initial', 'running', ?, ?, ?)""",
            (
                task_id,
                original_snapshot_id,
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:00:00+00:00",
            ),
        )
        conn.commit()

    context.save_draft(project_id, "third brief", owner)
    third = context.publish(project_id, owner, idempotency_key="third")
    started_preview = context.preview_task_context_update(task_id, project_id, owner)
    started_confirmed = context.confirm_task_context_update(
        task_id,
        project_id,
        str(started_preview["preview_id"]),
        owner,
        idempotency_key="confirm-third",
    )
    assert started_confirmed["context_version_id"] == third["context_version_id"]

    with tasks._connect() as conn:
        task_row = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        attempt_row = conn.execute(
            "SELECT context_snapshot_id FROM agent_task_attempts WHERE attempt_id = 'attempt-started'"
        ).fetchone()
        with pytest.raises(
            sqlite3.IntegrityError, match="started Attempts keep their Context snapshot"
        ):
            conn.execute(
                """UPDATE agent_task_attempts SET context_snapshot_id = ?
                   WHERE attempt_id = 'attempt-started'""",
                (str(started_confirmed["context_snapshot_id"]),),
            )
    assert task_row is not None
    assert task_row["project_context_snapshot_id"] == started_confirmed["context_snapshot_id"]
    assert attempt_row is not None
    assert attempt_row["context_snapshot_id"] == original_snapshot_id
    assert first["context_version_id"] != second["context_version_id"]

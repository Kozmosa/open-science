"""B4 Project Context assembly, provenance, and Task pinning contracts."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import cast

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService, TaskApplicationService
from ainrf.domain.context import ContextAssembler, ContextFragment, ContextSource
from ainrf.domain.service import DomainConflictError, DomainPermissionError

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _user(identifier: str) -> dict[str, object]:
    return {"id": identifier, "role": "member"}


def _domain(state_root: Path, artifact_sha: str) -> DomainService:
    return DomainService(state_root, artifact_sha=artifact_sha)


def _context(state_root: Path, artifact_sha: str) -> ProjectContextService:
    return ProjectContextService(state_root, artifact_sha=artifact_sha)


def _tasks(state_root: Path, artifact_sha: str) -> TaskApplicationService:
    return TaskApplicationService(state_root, artifact_sha=artifact_sha)


def _project_workspace(
    state_root: Path,
    tmp_path: Path,
    artifact_sha: str,
    owner: dict[str, object],
    *,
    label: str,
) -> tuple[DomainService, ProjectContextService, TaskApplicationService, str, str]:
    """Create a fully authorized v2 Project/Workspace scope for Context tests."""

    domain = _domain(state_root, artifact_sha)
    context = _context(state_root, artifact_sha)
    tasks = _tasks(state_root, artifact_sha)
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    environment = domain.create_environment(
        admin,
        alias=f"context-{label}",
        display_name=f"Context {label}",
        connection={},
        idempotency_key=f"context-environment-{label}",
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    owner_id = str(owner["id"])
    auth.grant_environment(
        env_id=environment_id,
        user_id=owner_id,
        max_tasks=None,
        granted_by="admin",
        reason="project context closure test",
    )
    project = domain.create_project(
        owner,
        name=f"Context {label}",
        idempotency_key=f"context-project-{label}",
    )
    project_id = str(project["project_id"])
    workspace_path = tmp_path / f"workspace-{label}"
    workspace_path.mkdir()
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label=f"Workspace {label}",
        idempotency_key=f"context-workspace-{label}",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(
        project_id,
        workspace_id,
        owner,
        idempotency_key=f"context-link-{label}",
    )
    return domain, context, tasks, project_id, workspace_id


def _create_task(
    tasks: TaskApplicationService,
    owner: dict[str, object],
    *,
    project_id: str,
    workspace_id: str,
    idempotency_key: str,
) -> dict[str, str]:
    return tasks.create_task(
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        title="Context task",
        prompt="Investigate the source record.",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key=idempotency_key,
    )


def _persist_task_output(state_root: Path, task_id: str, *, sequence: int, content: str) -> None:
    """Seed one durable Task result for Context Candidate provenance tests."""

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
               VALUES (?, ?, 'result', ?, '2026-07-13T00:00:00+00:00')""",
            (task_id, sequence, content),
        )
        conn.execute(
            "UPDATE tasks SET latest_output_seq = ? WHERE task_id = ?",
            (sequence, task_id),
        )
        conn.commit()


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


def test_direct_task_context_pin_facades_are_retired(state_root: Path) -> None:
    """TaskApplicationService is the sole public writer of Task Context pins."""

    context = _context(state_root, "b" * 64)
    with pytest.raises(DomainConflictError, match="Task Context mutations"):
        context.pin_active_context("task-direct", "project-direct")
    with pytest.raises(DomainConflictError, match="Task Context mutations"):
        context.ensure_task_snapshot("task-direct")


def test_assembler_keeps_fragment_provenance_and_rejects_tampered_fingerprint() -> None:
    assembler = ContextAssembler(byte_budget=1024, platform_constraints="platform")
    fragment = ContextFragment(
        fragment_id="fragment-reference",
        source_type="manual_reference",
        source_version="reference-v1",
        content="immutable evidence",
        source_metadata={"reference": "doi:10.1/example"},
        sort_order=3,
        byte_budget=9,
        created_by_user_id="owner",
        created_at="2026-07-12T00:00:00+00:00",
    )
    sources = (
        assembler.platform_source(),
        ContextSource(
            "project_brief",
            "version-1",
            "brief-sha",
            "Project Brief",
            "project",
            fragments=(fragment,),
        ),
        ContextSource(
            "workspace_context", "workspace-1", "workspace-v1", "Workspace Context", "workspace"
        ),
        ContextSource("task_request", "task-1", "request-sha", "Task Request", "request"),
    )

    assembly = assembler.assemble(sources)
    project_manifest = assembly.source_manifest[1]
    fragments = cast(list[dict[str, object]], project_manifest["fragments"])

    assert "### Context Fragment: manual_reference\nimmutable\n" in assembly.content
    assert project_manifest["truncated"] is True
    assert fragments == [
        {
            "position": 0,
            "fragment_id": "fragment-reference",
            "source_type": "manual_reference",
            "source_id": "fragment-reference",
            "source_version": "reference-v1",
            "fingerprint": fragment.fingerprint,
            "source_metadata": {"reference": "doi:10.1/example"},
            "sort_order": 3,
            "byte_budget": 9,
            "created_by_user_id": "owner",
            "created_at": "2026-07-12T00:00:00+00:00",
            "input_bytes": len("immutable evidence"),
            "local_included_bytes": len("immutable"),
            "rendered_bytes": len("### Context Fragment: manual_reference\nimmutable\n\n"),
            "included_bytes": len("### Context Fragment: manual_reference\nimmutable\n\n"),
            "locally_truncated": True,
            "globally_truncated": False,
            "truncated": True,
        }
    ]

    tampered = ContextFragment(
        fragment_id="fragment-tampered",
        source_type="manual_reference",
        source_version="reference-v1",
        content="immutable evidence",
        source_fingerprint="not-the-content-fingerprint",
    )
    with pytest.raises(ValueError, match="provenance fingerprint"):
        assembler.assemble(
            (
                assembler.platform_source(),
                ContextSource(
                    "project_brief",
                    "version-1",
                    "brief-sha",
                    "Project Brief",
                    "project",
                    fragments=(tampered,),
                ),
                ContextSource(
                    "workspace_context",
                    "workspace-1",
                    "workspace-v1",
                    "Workspace Context",
                    "workspace",
                ),
                ContextSource("task_request", "task-1", "request-sha", "Task Request", "request"),
            )
        )


def test_persisted_fragment_is_included_in_a_task_snapshot_with_provenance(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    owner = _user("owner")
    _domain_service, context, tasks, project_id, workspace_id = _project_workspace(
        state_root,
        tmp_path,
        committed_v2_state,
        owner,
        label="fragment",
    )
    fragment = context.create_fragment(
        project_id,
        "immutable evidence",
        owner,
        source_type="manual_reference",
        source_metadata={"reference": "doi:10.1/example"},
        source_version="reference-v1",
        sort_order=3,
        byte_budget=9,
    )
    # Fragments become executable Context only when their reviewed set is
    # captured by a published immutable Version.
    context.publish(project_id, owner, idempotency_key="publish-fragment-version")
    created = _create_task(
        tasks,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="fragment-task",
    )
    task_id = created["task_id"]
    snapshot = context.task_context(task_id, owner)
    source_manifest = cast(list[dict[str, object]], snapshot["source_manifest"])
    project_manifest = source_manifest[1]
    fragments = cast(list[dict[str, object]], project_manifest["fragments"])

    assert snapshot["context_version_id"] is not None
    assert "### Context Fragment: manual_reference\nimmutable\n" in str(snapshot["content"])
    assert fragments[0]["fragment_id"] == fragment["fragment_id"]
    assert fragments[0]["source_version"] == "reference-v1"
    assert fragments[0]["fingerprint"] == fragment["source_fingerprint"]
    assert fragments[0]["source_metadata"] == {"reference": "doi:10.1/example"}
    assert fragments[0]["created_by_user_id"] == "owner"
    assert fragments[0]["locally_truncated"] is True


def test_fragment_create_replays_the_original_result_for_an_idempotency_key(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    owner = _user("owner")
    _domain_service, context, _tasks, project_id, _workspace_id = _project_workspace(
        state_root,
        tmp_path,
        committed_v2_state,
        owner,
        label="fragment-idempotency",
    )

    first = context.create_fragment(
        project_id,
        "immutable evidence",
        owner,
        source_type="manual_reference",
        source_metadata={"reference": "doi:10.1/example"},
        idempotency_key="fragment-create",
    )
    replayed = context.create_fragment(
        project_id,
        "immutable evidence",
        owner,
        source_type="manual_reference",
        source_metadata={"reference": "doi:10.1/example"},
        idempotency_key="fragment-create",
    )

    assert replayed == first
    with pytest.raises(DomainConflictError, match="different request"):
        context.create_fragment(
            project_id,
            "changed evidence",
            owner,
            source_type="manual_reference",
            source_metadata={"reference": "doi:10.1/example"},
            idempotency_key="fragment-create",
        )


def test_published_context_version_freezes_fragment_manifest_and_fingerprint(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    """Later Fragment rows must not alter an already-published Version."""

    owner = _user("owner")
    _domain_service, context, tasks, project_id, workspace_id = _project_workspace(
        state_root,
        tmp_path,
        committed_v2_state,
        owner,
        label="frozen",
    )

    initial = cast(dict[str, object], context.get_context(project_id, owner)["active_version"])
    assert initial["content"] == ""
    assert initial["fragment_manifest"] == []

    first_fragment = context.create_fragment(
        project_id,
        "first reviewed source",
        owner,
        source_type="manual_reference",
        source_version="source-a-v1",
    )
    context.save_draft(project_id, "Stable project brief", owner)
    first_version = context.publish(project_id, owner, idempotency_key="freeze-first")

    first_task_id = _create_task(
        tasks,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="frozen-first-task",
    )["task_id"]
    first_snapshot = context.task_context(first_task_id, owner)
    assert "first reviewed source" in str(first_snapshot["content"])

    # This Fragment is reviewed only by the next publish.  It must not leak
    # into a new Snapshot pinned to the still-active first Version.
    second_fragment = context.create_fragment(
        project_id,
        "second future source",
        owner,
        source_type="manual_reference",
        source_version="source-b-v1",
    )
    second_task_id = _create_task(
        tasks,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="frozen-second-task",
    )["task_id"]
    still_first_snapshot = context.task_context(second_task_id, owner)
    assert "first reviewed source" in str(still_first_snapshot["content"])
    assert "second future source" not in str(still_first_snapshot["content"])

    stored_first = context.get_version(project_id, str(first_version["context_version_id"]), owner)
    assert stored_first["fingerprint"] == first_version["fingerprint"]
    assert [
        item["fragment_id"]
        for item in cast(list[dict[str, object]], stored_first["fragment_manifest"])
    ] == [first_fragment["fragment_id"]]

    second_version = context.publish(project_id, owner, idempotency_key="freeze-second")
    third_task_id = _create_task(
        tasks,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="frozen-third-task",
    )["task_id"]
    second_snapshot = context.task_context(third_task_id, owner)
    assert "second future source" in str(second_snapshot["content"])
    assert second_snapshot["fingerprint"] != first_snapshot["fingerprint"]
    assert second_version["fingerprint"] != first_version["fingerprint"]
    assert [
        item["fragment_id"]
        for item in cast(list[dict[str, object]], second_version["fragment_manifest"])
    ] == [first_fragment["fragment_id"], second_fragment["fragment_id"]]

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="context versions are immutable"):
            conn.execute(
                """UPDATE project_context_versions SET fragment_manifest_json = '[]'
                   WHERE context_version_id = ?""",
                (str(first_version["context_version_id"]),),
            )


def test_candidate_acceptance_changes_only_draft_and_publish_requires_capability(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    owner = _user("owner")
    domain, context, tasks_service, project_id, workspace_id = _project_workspace(
        state_root,
        tmp_path,
        committed_v2_state,
        owner,
        label="candidate",
    )
    auth = AuthService(state_root=state_root)
    auth.initialize()
    durable_editor = auth.register(
        username="editor", display_name="Editor", password="context-test-password"
    )
    editor = _user(durable_editor.id)
    domain.add_member(project_id, durable_editor.id, "editor", False, owner)

    context.save_draft(project_id, "active brief", owner)
    first = context.publish(project_id, owner, idempotency_key="publish-first")
    task = _create_task(
        tasks_service,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="candidate-source-task",
    )
    with pytest.raises(DomainConflictError, match="source Task"):
        context.create_candidate(
            project_id,
            "missing source",
            owner,
            source_output_start_seq=1,
            source_output_end_seq=1,
        )
    with pytest.raises(DomainConflictError, match="not persisted"):
        context.create_candidate(
            project_id,
            "invented output",
            owner,
            source_task_id=task["task_id"],
            source_output_start_seq=1,
            source_output_end_seq=1,
        )
    _persist_task_output(state_root, task["task_id"], sequence=1, content="candidate source")
    candidate = context.create_candidate(
        project_id,
        "candidate evidence",
        owner,
        source_metadata={"origin": "task-output"},
        source_task_id=task["task_id"],
        source_attempt_id=task["attempt_id"],
        source_output_start_seq=1,
        source_output_end_seq=1,
    )
    assert candidate["status"] == "proposed"
    with pytest.raises(DomainPermissionError, match="Task owner"):
        context.create_candidate(
            project_id,
            "editor cannot propose another user's output",
            editor,
            source_task_id=task["task_id"],
            source_output_start_seq=1,
            source_output_end_seq=1,
        )
    accepted = context.accept_candidate(project_id, str(candidate["candidate_id"]), editor)
    accepted_candidate = cast(dict[str, object], accepted["candidate"])

    assert accepted_candidate["status"] == "accepted"
    assert accepted_candidate["created_by_user_id"] == "owner"
    state = context.get_context(project_id, owner)
    active_version = cast(dict[str, object], state["active_version"])
    draft = cast(dict[str, object], state["draft"])
    assert active_version["context_version_id"] == first["context_version_id"]
    assert "candidate evidence" in str(draft["content"])
    with pytest.raises(DomainPermissionError):
        context.publish(project_id, editor, idempotency_key="editor-cannot-publish")
    with pytest.raises(DomainPermissionError):
        context.create_fragment(
            project_id,
            "Unpublished editor material",
            editor,
            source_type="manual_reference",
        )

    domain.add_member(project_id, durable_editor.id, "editor", True, owner)
    second = context.publish(project_id, editor, idempotency_key="editor-publishes")
    assert second["context_version_id"] != first["context_version_id"]
    assert "candidate evidence" in str(second["content"])
    context.save_draft(project_id, "a changed draft", editor)
    with pytest.raises(DomainConflictError, match="different request"):
        context.publish(project_id, editor, idempotency_key="editor-publishes")


def test_task_context_preview_confirm_is_idempotent_and_started_attempt_never_drifts(
    state_root: Path, tmp_path: Path, committed_v2_state: str
) -> None:
    owner = _user("owner")
    _domain_service, context, tasks, project_id, workspace_id = _project_workspace(
        state_root,
        tmp_path,
        committed_v2_state,
        owner,
        label="task-context",
    )
    context.save_draft(project_id, "first brief", owner)
    first = context.publish(project_id, owner, idempotency_key="first")
    created = _create_task(
        tasks,
        owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="task-context-create",
    )
    task_id = created["task_id"]
    original_snapshot = context.task_context(task_id, owner)
    original_snapshot_id = str(original_snapshot["context_snapshot_id"])
    assert "## Project Brief\nfirst brief" in str(original_snapshot["content"])
    assert "## Task Request\nInvestigate the source record." in str(original_snapshot["content"])

    context.save_draft(project_id, "second brief", owner)
    second = context.publish(project_id, owner, idempotency_key="second")
    preview = tasks.preview_task_context_update(task_id, project_id, owner)
    current = cast(dict[str, object], preview["current"])
    proposed = cast(dict[str, object], preview["proposed"])
    assert current["context_snapshot_id"] == original_snapshot_id
    assert proposed["context_version_id"] == second["context_version_id"]
    assert "second brief" in str(preview["diff"])

    confirmed = tasks.confirm_task_context_update(
        task_id,
        project_id,
        str(preview["preview_id"]),
        owner,
        idempotency_key="confirm-second",
    )
    repeated = tasks.confirm_task_context_update(
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
            """UPDATE agent_task_attempts
               SET status = 'running', started_at = ?
               WHERE attempt_id = ?""",
            (
                "2026-07-12T00:00:00+00:00",
                created["attempt_id"],
            ),
        )
        conn.commit()

    context.save_draft(project_id, "third brief", owner)
    third = context.publish(project_id, owner, idempotency_key="third")
    started_preview = tasks.preview_task_context_update(task_id, project_id, owner)
    started_confirmed = tasks.confirm_task_context_update(
        task_id,
        project_id,
        str(started_preview["preview_id"]),
        owner,
        idempotency_key="confirm-third",
    )
    assert started_confirmed["context_version_id"] == third["context_version_id"]

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task_row = conn.execute(
            "SELECT project_context_snapshot_id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        attempt_row = conn.execute(
            "SELECT context_snapshot_id FROM agent_task_attempts WHERE attempt_id = ?",
            (created["attempt_id"],),
        ).fetchone()
        with pytest.raises(
            sqlite3.IntegrityError, match="started Attempts keep their Context snapshot"
        ):
            conn.execute(
                """UPDATE agent_task_attempts SET context_snapshot_id = ?
                   WHERE attempt_id = ?""",
                (str(started_confirmed["context_snapshot_id"]), created["attempt_id"]),
            )
    assert task_row is not None
    assert task_row["project_context_snapshot_id"] == started_confirmed["context_snapshot_id"]
    assert attempt_row is not None
    # The first confirmed update happened while this Attempt was queued, so
    # it legitimately adopted that Snapshot before being marked running.  The
    # later confirmation cannot drift a started Attempt again.
    assert attempt_row["context_snapshot_id"] == confirmed["context_snapshot_id"]
    assert first["context_version_id"] != second["context_version_id"]

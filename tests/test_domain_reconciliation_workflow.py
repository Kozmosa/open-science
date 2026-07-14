"""Typed, auditable remediation workflow for domain migration issues."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from ainrf.db import connect, run_pending
from ainrf.domain_control import DomainCutoverController, DomainMaintenanceService
from ainrf.domain_migration import DomainImporter
from tests.domain_cutover_fixtures import enter_maintenance_with_required_participants
from ainrf.domain_migration.reconciliation import DomainReconciliationService

pytestmark = [pytest.mark.unit]

_NOW = "2026-07-12T00:00:00+00:00"


def _value(result: object, name: str) -> object:
    if isinstance(result, Mapping):
        return cast(Mapping[str, object], result)[name]
    return getattr(result, name)


def _as_issue_ids(issues: Iterable[object]) -> set[str]:
    return {str(_value(issue, "issue_id")) for issue in issues}


def _manifest(run_id: str) -> tuple[str, str]:
    manifest = json.dumps(
        {"run": run_id, "sources": [{"path": "runtime/projects.json", "sha256": "a" * 64}]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return manifest, hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _seed_run(
    state_root: Path,
    run_id: str,
    *,
    status: str = "completed",
    phase: str = "completed",
) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    manifest, manifest_sha256 = _manifest(run_id)
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO domain_migration_runs (
                run_id, mode, source_manifest_json, source_manifest_sha256, code_version,
                status, phase, checkpoint_json, artifact_sha, heartbeat_at,
                resume_metadata_json, started_at, finished_at
            ) VALUES (?, 'apply', ?, ?, 'test', ?, ?, '{}', NULL, ?, '{}', ?, ?)
            """,
            (
                run_id,
                manifest,
                manifest_sha256,
                status,
                phase,
                _NOW,
                _NOW,
                _NOW if status == "completed" else None,
            ),
        )
        conn.commit()


def _seed_control_plane(state_root: Path, run_id: str) -> None:
    _seed_auth_user(state_root, "owner-1")
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                status, created_at, updated_at
            ) VALUES
                ('environment-old', 'old', 'owner-1', 'Old environment', '{}', 'disabled', ?, ?),
                ('environment-new', 'new', 'owner-1', 'New environment', '{}', 'active', ?, ?)
            """,
            (_NOW, _NOW, _NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES ('project-1', 'legacy-owner', 'Migrated project', 'active', 1, ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                status, created_at, updated_at
            ) VALUES (
                'workspace-1', 'owner-1', 'environment-old', '/tmp/domain-workspace-1',
                'Migrated workspace', 'active', ?, ?
            )
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-1', 'workspace-1', 'active', 0, 'legacy-owner', ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-1', 'project-1', 'workspace-1', 'environment-old', 'general',
                'claude_code', 'completed', 'Migrated task', 'test prompt', ?, ?, 'owner-1'
            )
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, created_at
            ) VALUES ('attempt-1', 'task-1', 1, 'migration', 'completed', ?)
            """,
            (_NOW,),
        )
        conn.execute(
            """
            INSERT INTO legacy_domain_records (
                legacy_record_id, run_id, record_type, payload_json, created_at
            ) VALUES ('legacy-session-1', ?, 'session', '{"id":"legacy-session-1"}', ?)
            """,
            (run_id, _NOW),
        )
        conn.commit()


def _seed_auth_user(state_root: Path, user_id: str) -> None:
    auth_path = state_root / "runtime" / "auth.sqlite3"
    with closing(connect(auth_path)) as conn:
        run_pending(conn, "auth")
        conn.execute(
            """
            INSERT OR IGNORE INTO users (
                id, username, password_hash, display_name, role, status, created_at
            ) VALUES (?, ?, 'not-used-in-test', 'Migration owner', 'member', 'active', ?)
            """,
            (user_id, user_id, _NOW),
        )
        conn.commit()


def _seed_domain_project_environment(
    state_root: Path,
    *,
    include_workspace: bool = False,
) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                status, created_at, updated_at
            ) VALUES ('environment-1', 'environment-one', 'owner-1', 'Environment one', '{}',
                      'active', ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES ('project-1', 'owner-1', 'Migrated Project', 'active', 1, ?, ?)
            """,
            (_NOW, _NOW),
        )
        if include_workspace:
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, owner_user_id, environment_id, canonical_path, label,
                    status, created_at, updated_at
                ) VALUES ('workspace-1', 'owner-1', 'environment-1', '/tmp/project-workspace',
                          'Project workspace', 'active', ?, ?)
                """,
                (_NOW, _NOW),
            )
            conn.execute(
                """
                INSERT INTO project_workspace_links (
                    project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
                ) VALUES ('project-1', 'workspace-1', 'active', 1, 'owner-1', ?, ?)
                """,
                (_NOW, _NOW),
            )
        conn.commit()


def _seed_finalizable_control_plane(state_root: Path) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES ('project-ready', 'owner-ready', 'Ready project', 'active', 1, ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.commit()


def _seed_issue(
    state_root: Path,
    run_id: str,
    issue_id: str,
    *,
    category: str,
    record_type: str,
    record_id: str,
    severity: str = "blocking",
) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO domain_migration_issues (
                issue_id, run_id, category, record_type, record_id, severity, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'requires explicit operator resolution', ?)
            """,
            (issue_id, run_id, category, record_type, record_id, severity, _NOW),
        )
        conn.commit()


def _seed_primary_control_plane_before_import(state_root: Path) -> None:
    """Seed v2 facts without changing the importer-visible legacy Task source."""
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                status, created_at, updated_at
            ) VALUES ('environment-1', 'one', 'owner-1', 'Environment one', '{}', 'active', ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES ('project-1', 'owner-1', 'Migrated project', 'active', 1, ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                status, created_at, updated_at
            ) VALUES (
                'workspace-1', 'owner-1', 'environment-1', '/tmp/domain-workspace-1',
                'Migrated workspace', 'active', ?, ?
            )
            """,
            (_NOW, _NOW),
        )
        conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-1', 'workspace-1', 'active', 0, 'owner-1', ?, ?)
            """,
            (_NOW, _NOW),
        )
        conn.commit()


def _audit_events(state_root: Path) -> list[tuple[str, str, str, str]]:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT actor_id, event_type, subject_type, subject_id
            FROM domain_audit_events ORDER BY created_at, event_id
            """
        ).fetchall()
    return [
        (
            str(row["actor_id"]),
            str(row["event_type"]),
            str(row["subject_type"]),
            str(row["subject_id"]),
        )
        for row in rows
    ]


def test_primary_workspace_resolution_is_explicit_and_audited(state_root: Path) -> None:
    run_id = "run-primary"
    _seed_run(state_root, run_id)
    _seed_control_plane(state_root, run_id)
    _seed_issue(
        state_root,
        run_id,
        "issue-primary",
        category="primary_workspace_missing",
        record_type="project",
        record_id="project-1",
    )
    service = DomainReconciliationService(state_root)

    assert _as_issue_ids(service.list_issues(run_id)) == {"issue-primary"}
    inspected = service.inspect_issue("issue-primary")
    assert _value(inspected, "run_id") == run_id
    assert _value(inspected, "resolution_status") == "open"

    with pytest.raises(ValueError):
        service.resolve_issue(run_id, "issue-primary", "ignore", {}, actor_id="operator-1")
    with pytest.raises(ValueError):
        service.resolve_issue(
            run_id,
            "issue-primary",
            "assign_project_owner",
            {"owner_user_id": "owner-1"},
            actor_id="operator-1",
        )
    with pytest.raises((LookupError, ValueError)):
        service.resolve_issue(
            "other-run",
            "issue-primary",
            "set_primary_workspace",
            {"workspace_id": "workspace-1"},
            actor_id="operator-1",
        )

    resolved = service.resolve_issue(
        run_id,
        "issue-primary",
        "set_primary_workspace",
        {"workspace_id": "workspace-1"},
        actor_id="operator-1",
    )

    assert _value(resolved, "resolution_status") == "resolved"
    assert _value(service.inspect_issue("issue-primary"), "resolution_status") == "resolved"
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        primary = conn.execute(
            """
            SELECT is_primary FROM project_workspace_links
            WHERE project_id = 'project-1' AND workspace_id = 'workspace-1'
            """
        ).fetchone()
    assert primary is not None
    assert primary[0] == 1
    assert (
        "operator-1",
        "domain_migration_issue.resolved",
        "migration_issue",
        "issue-primary",
    ) in (_audit_events(state_root))


def test_typed_resolutions_update_only_their_matching_domain_record(state_root: Path) -> None:
    run_id = "run-typed"
    _seed_run(state_root, run_id)
    _seed_control_plane(state_root, run_id)
    _seed_issue(
        state_root,
        run_id,
        "issue-owner",
        category="owner_missing",
        record_type="project",
        record_id="project-1",
    )
    _seed_issue(
        state_root,
        run_id,
        "issue-environment",
        category="workspace_environment_missing",
        record_type="workspace",
        record_id="workspace-1",
    )
    _seed_issue(
        state_root,
        run_id,
        "issue-session",
        category="session_mapping_missing",
        record_type="session",
        record_id="legacy-session-1",
        severity="non_blocking",
    )
    service = DomainReconciliationService(state_root)

    service.resolve_issue(
        run_id,
        "issue-owner",
        "assign_project_owner",
        {"owner_user_id": "owner-1"},
        actor_id="operator-2",
    )
    service.resolve_issue(
        run_id,
        "issue-environment",
        "assign_workspace_environment",
        {"environment_id": "environment-new"},
        actor_id="operator-2",
    )
    service.resolve_issue(
        run_id,
        "issue-session",
        "map_runtime_session",
        {"attempt_id": "attempt-1"},
        actor_id="operator-2",
    )

    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        project = conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = 'project-1'"
        ).fetchone()
        workspace = conn.execute(
            "SELECT environment_id FROM workspaces WHERE workspace_id = 'workspace-1'"
        ).fetchone()
        resolution_statuses = {
            str(row["issue_id"]): str(row["resolution_status"])
            for row in conn.execute(
                """
                SELECT issue_id, resolution_status FROM domain_migration_issues
                WHERE run_id = ?
                """,
                (run_id,),
            )
        }
    assert project is not None and project[0] == "owner-1"
    assert workspace is not None and workspace[0] == "environment-new"
    assert resolution_statuses == {
        "issue-owner": "resolved",
        "issue-environment": "resolved",
        "issue-session": "resolved",
    }
    assert {
        ("operator-2", "domain_migration_issue.resolved", "migration_issue", "issue-owner"),
        ("operator-2", "domain_migration_issue.resolved", "migration_issue", "issue-environment"),
        ("operator-2", "domain_migration_issue.resolved", "migration_issue", "issue-session"),
    } <= set(_audit_events(state_root))


def test_owner_resolution_rehydrates_an_archived_import_record(state_root: Path) -> None:
    _seed_auth_user(state_root, "owner-1")
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "projects.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "project_id": "owner-1_default",
                        "name": "Recovered project",
                        "owner_user_id": "not-a-user",
                        "is_default": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = DomainImporter(state_root).run()
    service = DomainReconciliationService(state_root)
    issue = next(iter(service.list_issues(imported.run_id)))

    resolved = service.resolve_issue(
        imported.run_id,
        issue.issue_id,
        "assign_project_owner",
        {"owner_user_id": "owner-1"},
        actor_id="operator-4",
    )

    assert resolved.category == "owner_unmapped"
    db_path = runtime / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        project = conn.execute(
            """
            SELECT owner_user_id, name, is_default FROM projects
            WHERE project_id = 'owner-1_default'
            """
        ).fetchone()
        context = conn.execute(
            """
            SELECT 1 FROM project_context_versions
            WHERE project_id = 'owner-1_default' AND is_active = 1
            """
        ).fetchone()
    assert project is not None
    assert tuple(project) == ("owner-1", "Recovered project", 1)
    assert context is not None


def test_workspace_owner_resolution_rehydrates_only_after_explicit_environment_choice(
    state_root: Path,
) -> None:
    _seed_auth_user(state_root, "owner-1")
    _seed_domain_project_environment(state_root)
    runtime = state_root / "runtime"
    (runtime / "workspaces.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "workspace_id": "workspace-unmapped-owner",
                        "owner_user_id": "legacy-owner",
                        "project_id": "project-1",
                        "environment_id": "environment-1",
                        "default_workdir": "/tmp/unmapped-owner-workspace",
                        "label": "Recovered workspace",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = DomainImporter(state_root).run()
    service = DomainReconciliationService(state_root)
    issue = next(
        item
        for item in service.list_issues(imported.run_id)
        if item.category == "workspace_owner_unmapped"
    )

    with pytest.raises(ValueError, match="active environment_id"):
        service.resolve_issue(
            imported.run_id,
            issue.issue_id,
            "assign_workspace_owner",
            {"owner_user_id": "owner-1"},
            actor_id="operator-5",
        )
    resolved = service.resolve_issue(
        imported.run_id,
        issue.issue_id,
        "assign_workspace_owner",
        {"owner_user_id": "owner-1", "environment_id": "environment-1"},
        actor_id="operator-5",
    )

    assert resolved.resolution_type == "owner_mapping"
    db_path = runtime / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        workspace = conn.execute(
            """
            SELECT owner_user_id, environment_id, canonical_path
            FROM workspaces WHERE workspace_id = 'workspace-unmapped-owner'
            """
        ).fetchone()
        link = conn.execute(
            """
            SELECT status, is_primary FROM project_workspace_links
            WHERE project_id = 'project-1' AND workspace_id = 'workspace-unmapped-owner'
            """
        ).fetchone()
    assert workspace is not None
    assert tuple(workspace) == (
        "owner-1",
        "environment-1",
        "/tmp/unmapped-owner-workspace",
    )
    assert link is not None and tuple(link) == ("active", 0)
    assert (
        "operator-5",
        "domain_migration_issue.resolved",
        "migration_issue",
        issue.issue_id,
    ) in _audit_events(state_root)


def test_task_owner_resolution_pins_context_and_creates_a_legacy_attempt(
    state_root: Path,
) -> None:
    _seed_auth_user(state_root, "owner-1")
    _seed_domain_project_environment(state_root, include_workspace=True)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-unmapped-owner', 'project-1', 'workspace-1', 'environment-1',
                'general', 'claude_code', 'queued', 'Recovered task', 'legacy prompt', ?, ?,
                'legacy-owner'
            )
            """,
            (_NOW, _NOW),
        )
        conn.commit()

    imported = DomainImporter(state_root).run()
    service = DomainReconciliationService(state_root)
    issues = service.list_issues(imported.run_id)
    issue = next(item for item in issues if item.category == "task_owner_unmapped")
    assert "task_domain_mapping_invalid" not in {item.category for item in issues}

    resolved = service.resolve_issue(
        imported.run_id,
        issue.issue_id,
        "assign_task_owner",
        {"owner_user_id": "owner-1"},
        actor_id="operator-6",
    )

    assert resolved.resolution_type == "owner_mapping"
    with closing(connect(db_path)) as conn:
        task = conn.execute(
            """
            SELECT owner_user_id, project_context_version_id, project_context_snapshot_id,
                   latest_attempt_id
            FROM tasks WHERE task_id = 'task-unmapped-owner'
            """
        ).fetchone()
        attempt = conn.execute(
            """
            SELECT attempt_id, status, context_snapshot_id
            FROM agent_task_attempts WHERE task_id = 'task-unmapped-owner'
            """
        ).fetchone()
    assert task is not None
    assert tuple(task) == (
        "owner-1",
        "legacy-empty-project-1",
        "legacy-snapshot-task-unmapped-owner",
        "legacy-task-attempt-task-unmapped-owner",
    )
    assert attempt is not None
    assert tuple(attempt) == (
        "legacy-task-attempt-task-unmapped-owner",
        "queued",
        "legacy-snapshot-task-unmapped-owner",
    )


def test_reconcile_rejects_a_resolved_issue_when_its_primary_invariant_is_broken(
    state_root: Path,
) -> None:
    _seed_primary_control_plane_before_import(state_root)
    imported = DomainImporter(state_root).run()
    _seed_issue(
        state_root,
        imported.run_id,
        "issue-primary",
        category="primary_workspace_missing",
        record_type="project",
        record_id="project-1",
    )
    service = DomainReconciliationService(state_root)
    service.resolve_issue(
        imported.run_id,
        "issue-primary",
        "set_primary_workspace",
        {"workspace_id": "workspace-1"},
        actor_id="operator-2",
    )

    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            UPDATE project_workspace_links SET is_primary = 0
            WHERE project_id = 'project-1' AND workspace_id = 'workspace-1'
            """
        )
        conn.commit()

    reconciliation = service.reconcile(imported.run_id)

    assert not reconciliation.cutover_allowed
    assert "primary_workspace_missing" in reconciliation.blocking_issues


def test_finalization_requires_completed_unblocked_run_and_valid_restore_evidence(
    state_root: Path,
) -> None:
    _seed_run(state_root, "run-incomplete", status="running", phase="importing")
    _seed_run(state_root, "run-blocked")
    _seed_issue(
        state_root,
        "run-blocked",
        "issue-blocking",
        category="owner_missing",
        record_type="project",
        record_id="project-1",
    )
    ready_run = DomainImporter(state_root).run(artifact_sha="c" * 64)
    _seed_finalizable_control_plane(state_root)
    service = DomainReconciliationService(state_root)
    evidence: dict[str, object] = {
        "manifest_sha256": "b" * 64,
        "validated_at": _NOW,
        "status": "valid",
    }

    with pytest.raises(ValueError):
        service.finalize_run("run-incomplete", "operator-3", "c" * 64, evidence)
    with pytest.raises(ValueError):
        service.finalize_run("run-blocked", "operator-3", "c" * 64, evidence)

    maintenance = DomainMaintenanceService(state_root)
    enter_maintenance_with_required_participants(
        maintenance,
        actor_id="operator-3",
        reason="finalize Task reference constraints",
    )
    try:
        constraints = DomainCutoverController(state_root).finalize_constraints(
            actor_id="operator-3",
            run_id=ready_run.run_id,
            stability_window_seconds=0,
        )
        assert constraints.cutover_allowed
        with pytest.raises(ValueError):
            service.finalize_run(
                ready_run.run_id,
                "operator-3",
                "c" * 64,
                {"manifest_sha256": "b" * 64, "validated_at": _NOW, "status": "invalid"},
            )

        finalized = service.finalize_run(ready_run.run_id, "operator-3", "c" * 64, evidence)
    finally:
        maintenance.exit(actor_id="operator-3")

    assert bool(_value(finalized, "cutover_allowed"))
    assert _value(finalized, "run_id") == ready_run.run_id
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        run = conn.execute(
            """
            SELECT source_manifest_json, final_manifest_json, source_manifest_sha256,
                   final_manifest_sha256, artifact_sha, cutover_allowed,
                   restore_evidence_verified_at
            FROM domain_migration_runs WHERE run_id = ?
            """,
            (ready_run.run_id,),
        ).fetchone()
        cutover_state = conn.execute(
            """
            SELECT state, cutover_ready, cutover_run_id, first_v2_write_at
            FROM domain_cutover_state WHERE singleton = 1
            """
        ).fetchone()
    assert run is not None
    assert run[0] == run[1]
    assert run[2] == run[3]
    assert tuple(run[4:]) == ("c" * 64, 1, _NOW)
    assert cutover_state is not None
    assert tuple(cutover_state) == ("legacy", 0, None, None)
    assert ("operator-3", "domain_migration_run.finalized", "migration_run", ready_run.run_id) in (
        _audit_events(state_root)
    )
    assert (
        "operator-3",
        "domain_cutover.constraints_finalized",
        "domain_constraints",
        "tasks",
    ) in (_audit_events(state_root))


def test_issue_status_tampering_is_rejected_without_a_typed_resolution(
    state_root: Path,
) -> None:
    run_id = "run-tampered"
    _seed_run(state_root, run_id)
    _seed_issue(
        state_root,
        run_id,
        "issue-tampered",
        category="owner_missing",
        record_type="project",
        record_id="project-1",
    )
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                UPDATE domain_migration_issues SET resolution_status = 'resolved'
                WHERE issue_id = 'issue-tampered'
                """
            )
        status = conn.execute(
            "SELECT resolution_status FROM domain_migration_issues WHERE issue_id = 'issue-tampered'"
        ).fetchone()
    assert status is not None
    assert status[0] == "open"

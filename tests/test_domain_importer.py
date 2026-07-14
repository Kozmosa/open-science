"""Shadow importer and reconciliation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect, run_pending
from ainrf.domain_migration import DomainImporter

pytestmark = [pytest.mark.unit]


def _write_json(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"items": items}), encoding="utf-8")


def test_importer_is_idempotent_and_reports_unmapped_owner(state_root: Path) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    runtime = state_root / "runtime"
    _write_json(
        runtime / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": user.id}],
    )
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "w1",
                "project_id": "p1",
                "owner_user_id": user.id,
                "default_workdir": "/tmp/domain-import-w1",
            }
        ],
    )

    importer = DomainImporter(state_root)
    first = importer.run()
    second = importer.run()

    assert first.status == "completed"
    assert first.imported_count >= 3
    assert second.run_id == first.run_id
    assert not first.cutover_allowed


def test_importer_marks_unmapped_owner_blocking(state_root: Path) -> None:
    runtime = state_root / "runtime"
    _write_json(
        runtime / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": "missing"}],
    )

    report = DomainImporter(state_root).run()

    assert report.blocking_issue_count == 1
    assert report.attention_needed_count == 1


def test_reconciliation_refuses_cutover_when_constraints_or_default_are_missing(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    _write_json(
        state_root / "runtime" / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": user.id}],
    )

    importer = DomainImporter(state_root)
    run = importer.run()
    reconciliation = importer.reconcile(run.run_id)

    assert not reconciliation.cutover_allowed
    assert "default_project_missing" in reconciliation.blocking_issues
    assert "constraints_not_ready" in reconciliation.blocking_issues


def test_importer_maps_members_relationships_attempts_and_runtime_checkpoint(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    runtime = state_root / "runtime"
    with auth._connect() as conn:
        conn.execute(
            """
            INSERT INTO project_collaborators (project_id, user_id, role, added_by_user_id, added_at)
            VALUES ('alice_default', ?, 'member', ?, '2026-07-12T00:00:00+00:00')
            """,
            (user.id, user.id),
        )
        conn.commit()
    _write_json(
        runtime / "projects.json",
        [
            {
                "project_id": "alice_default",
                "name": "Alice default",
                "owner_user_id": user.id,
                "default_workspace_id": "workspace-1",
            }
        ],
    )
    workspace_path = state_root / "workspaces" / "one"
    workspace_path.mkdir(parents=True)
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "workspace-1",
                "project_id": "alice_default",
                "owner_user_id": user.id,
                "default_workdir": str(workspace_path),
            }
        ],
    )
    _write_json(
        runtime / "task_edges.json",
        [
            {
                "edge_id": "edge-1",
                "project_id": "alice_default",
                "source_task_id": "task-1",
                "target_task_id": "task-2",
            }
        ],
    )
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        run_pending(conn, "agentic_researcher")
        for task_id in ("task-1", "task-2"):
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, workspace_id, environment_id, researcher_type,
                    harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
                ) VALUES (?, 'alice_default', 'workspace-1', 'env-localhost', 'general',
                    'claude_code', 'completed', ?, 'legacy prompt',
                    '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00', ?)
                """,
                (task_id, task_id, user.id),
            )
        conn.execute(
            """
            INSERT INTO task_outputs (task_id, seq, kind, content, created_at)
            VALUES ('task-1', 7, 'assistant', 'legacy output', '2026-07-12T00:00:01+00:00')
            """
        )
        conn.commit()
    with connect(runtime / "sessions.sqlite3") as conn:
        run_pending(conn, "sessions")
        conn.execute(
            """
            INSERT INTO task_sessions (id, project_id, title, created_at, updated_at, owner_user_id)
            VALUES ('session-1', 'alice_default', 'Legacy session',
                '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00', ?)
            """,
            (user.id,),
        )
        conn.execute(
            """
            INSERT INTO task_attempts (
                id, session_id, task_id, attempt_seq, status, started_at, finished_at,
                token_usage_json, created_at
            ) VALUES ('session-attempt-1', 'session-1', 'task-1', 1, 'completed',
                '2026-07-12T00:00:00+00:00', '2026-07-12T00:01:00+00:00', '{}',
                '2026-07-12T00:00:00+00:00')
            """
        )
        conn.commit()
    checkpoint = state_root / "session-states" / "task-1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "checkpoint.json").write_text(
        json.dumps({"task_id": "task-1", "session_id": "runtime-session-1", "version": 1}),
        encoding="utf-8",
    )

    report = DomainImporter(state_root).run(artifact_sha="c" * 64)

    assert report.status == "completed"
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        member = conn.execute(
            "SELECT role, can_publish FROM project_members WHERE project_id = 'alice_default' AND user_id = ?",
            (user.id,),
        ).fetchone()
        assert member is not None
        assert tuple(member) == ("viewer", 0)
        relationship = conn.execute(
            "SELECT relationship_type FROM task_relationships WHERE source_task_id = 'task-1'"
        ).fetchone()
        assert relationship is not None
        assert relationship[0] == "depends_on"
        attempt = conn.execute(
            """
            SELECT output_start_seq, output_end_seq FROM agent_task_attempts
            WHERE task_id = 'task-1' ORDER BY attempt_seq DESC LIMIT 1
            """
        ).fetchone()
        assert attempt is not None
        assert tuple(attempt) == (7, 7)
        runtime_session = conn.execute(
            "SELECT engine_name, engine_session_key FROM agent_runtime_sessions"
        ).fetchone()
        assert runtime_session is not None
        assert tuple(runtime_session) == ("legacy", "runtime-session-1")


def test_importer_imports_non_seed_environment_without_copying_credentials(
    state_root: Path,
) -> None:
    runtime = state_root / "runtime"
    _write_json(
        runtime / "environments.json",
        [
            {
                "id": "env-remote",
                "alias": "remote",
                "display_name": "Remote compute",
                "host": "compute.example",
                "port": 2202,
                "user": "researcher",
                "identity_file": "/secure/keys/researcher",
                "default_workdir": "/workspace/research",
                "credential_ref": "secret://environment/remote",
                "password": "must-not-be-copied",
                "api_key": "must-not-be-copied",
            }
        ],
    )

    report = DomainImporter(state_root).run()

    assert report.status == "completed"
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT connection_json, connection_fingerprint, credential_ref, status
            FROM environments WHERE environment_id = 'env-remote'
            """
        ).fetchone()
        assert row is not None
        connection = json.loads(str(row["connection_json"]))
        assert connection["host"] == "compute.example"
        assert "password" not in connection
        assert "api_key" not in connection
        assert row["connection_fingerprint"]
        assert row["credential_ref"] == "secret://environment/remote"
        assert row["status"] == "active"
        archived = conn.execute(
            "SELECT COUNT(*) FROM legacy_domain_records WHERE run_id = ? AND record_type = 'environment'",
            (report.run_id,),
        ).fetchone()
    assert archived is not None
    assert archived[0] == 0


def test_importer_refuses_ambiguous_workspace_environment_for_active_work(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    runtime = state_root / "runtime"
    workspace_path = state_root / "workspaces" / "ambiguous"
    workspace_path.mkdir(parents=True)
    _write_json(
        runtime / "projects.json",
        [
            {
                "project_id": "p1",
                "name": "Project",
                "owner_user_id": user.id,
                "default_environment_id": "env-two",
            }
        ],
    )
    _write_json(
        runtime / "environments.json",
        [
            {"id": "env-one", "alias": "one", "display_name": "One", "host": "one"},
            {"id": "env-two", "alias": "two", "display_name": "Two", "host": "two"},
        ],
    )
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "w1",
                "project_id": "p1",
                "owner_user_id": user.id,
                "default_workdir": str(workspace_path),
            }
        ],
    )
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-1', 'p1', 'w1', 'env-one', 'general', 'claude_code', 'queued',
                'Legacy task', 'prompt', '2026-07-12T00:00:00+00:00',
                '2026-07-12T00:00:00+00:00', ?
            )
            """,
            (user.id,),
        )
        conn.commit()

    report = DomainImporter(state_root).run()

    assert report.blocking_issue_count >= 1
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        issue = conn.execute(
            """
            SELECT severity FROM domain_migration_issues
            WHERE run_id = ? AND category = 'workspace_environment_ambiguous' AND record_id = 'w1'
            """,
            (report.run_id,),
        ).fetchone()
        workspace = conn.execute(
            "SELECT environment_id FROM workspaces WHERE workspace_id = 'w1'"
        ).fetchone()
        result = conn.execute(
            """
            SELECT status FROM domain_migration_record_results
            WHERE run_id = ? AND record_type = 'workspace' AND source_record_id = 'w1'
            """,
            (report.run_id,),
        ).fetchone()
    assert issue is not None
    assert issue["severity"] == "blocking"
    assert workspace is not None
    assert str(workspace["environment_id"]).startswith("legacy-unresolved-workspace-")
    assert result is not None
    assert result["status"] == "attention_needed"


def test_importer_marks_workspace_and_task_owner_mapping_failures_blocking(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    runtime = state_root / "runtime"
    workspace_path = state_root / "workspaces" / "owner"
    workspace_path.mkdir(parents=True)
    _write_json(
        runtime / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": user.id}],
    )
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "w-owner-missing",
                "project_id": "p1",
                "owner_user_id": "retired-user",
                "default_workdir": str(workspace_path),
            },
            {
                "workspace_id": "w-task-owner",
                "project_id": "p1",
                "owner_user_id": user.id,
                "default_workdir": str(workspace_path / "task"),
            },
        ],
    )
    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
            ) VALUES (
                'task-owner-missing', 'p1', 'w-task-owner', 'env-localhost', 'general',
                'claude_code', 'completed', 'Legacy task', 'prompt',
                '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00', 'retired-user'
            )
            """
        )
        conn.commit()

    report = DomainImporter(state_root).run()

    with connect(runtime / "agentic_researcher.sqlite3") as conn:
        issues = {
            str(row["category"]): str(row["severity"])
            for row in conn.execute(
                "SELECT category, severity FROM domain_migration_issues WHERE run_id = ?",
                (report.run_id,),
            ).fetchall()
        }
        workspace_result = conn.execute(
            """
            SELECT status FROM domain_migration_record_results
            WHERE run_id = ? AND record_type = 'workspace' AND source_record_id = 'w-owner-missing'
            """,
            (report.run_id,),
        ).fetchone()
        task_result = conn.execute(
            """
            SELECT status FROM domain_migration_record_results
            WHERE run_id = ? AND record_type = 'task' AND source_record_id = 'task-owner-missing'
            """,
            (report.run_id,),
        ).fetchone()
    assert issues["workspace_owner_unmapped"] == "blocking"
    assert issues["task_owner_unmapped"] == "blocking"
    assert workspace_result is not None and workspace_result["status"] == "attention_needed"
    assert task_result is not None and task_result["status"] == "attention_needed"

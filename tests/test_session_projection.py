"""V2 Session API projection tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.db import connect, run_pending
from ainrf.domain import SessionProjectionService, TaskProjectionService
from ainrf.domain.service import DomainNotFoundError

pytestmark = [pytest.mark.unit]


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, Mapping)
    return {str(key): item for key, item in cast(Mapping[object, object], value).items()}


def _first_runtime(attempt: dict[str, object]) -> dict[str, object]:
    values = attempt["runtime_sessions"]
    assert isinstance(values, list)
    assert values
    return _mapping(values[0])


def test_task_attempts_project_to_session_and_attempts(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    viewer: dict[str, object] = {"id": "viewer", "role": "member"}
    outsider: dict[str, object] = {"id": "outsider", "role": "member"}
    administrator: dict[str, object] = {"id": "administrator", "role": "admin"}
    project_id = "session-projection-project"
    durable_output = json.dumps(
        {
            "role": "assistant",
            "content": (
                "Authorization: Bearer viewer-output-token; "
                "API key: sk-viewer-output-secret; "
                "cwd=/home/ainrf_tenants/owner/private-workspace"
            ),
            "metadata": {
                "OPENAI_API_KEY": "sk-viewer-output-secret",
                "cwd": "/home/ainrf_tenants/owner/private-workspace",
            },
        },
        separators=(",", ":"),
    )
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """INSERT INTO projects(
                   project_id, owner_user_id, name, status, is_default, created_at, updated_at
               ) VALUES (?, ?, 'Project', 'active', 0, ?, ?)""",
            (project_id, "owner", "2026-07-12T00:00:00+00:00", "2026-07-12T00:00:00+00:00"),
        )
        conn.commit()
    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    task = tasks.create_task(
        project_id,
        "workspace",
        "environment",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "prompt",
        "owner",
    )
    attempt_id = "attempt-session-projection"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        # Projection fixtures seed immutable historical Attempt facts directly;
        # production Attempt creation is deliberately only available through
        # TaskApplicationService.
        conn.execute(
            """INSERT INTO agent_task_attempts(
                   attempt_id, task_id, attempt_seq, trigger, status, created_at
               ) VALUES (?, ?, 1, 'initial', 'succeeded', ?)""",
            (attempt_id, task.task_id, "2026-07-12T00:00:00+00:00"),
        )
        conn.execute(
            """UPDATE agent_task_attempts
               SET status = 'succeeded', token_usage_json = ?, cost_usd = ?,
                   failure_reason = ?, stop_reason = ?, authorization_environment_id = ?,
                   authorization_grant_version = ?, authorization_checked_at = ?,
                   stop_requested_at = ?, stop_requested_reason = ?
               WHERE attempt_id = ?""",
            (
                json.dumps(
                    {
                        "total": {
                            "input_tokens": 7,
                            "output_tokens": 5,
                            "cache_creation_input_tokens": 1,
                            "cache_read_input_tokens": 2,
                            "cost_usd": 0.12,
                        }
                    }
                ),
                0.42,
                "/home/tenant/private-attempt-error",
                "/home/tenant/private-stop-reason",
                "environment-private-id",
                7,
                "2026-07-12T00:00:01+00:00",
                "2026-07-12T00:00:02+00:00",
                "/home/tenant/private-stop-request",
                attempt_id,
            ),
        )
        conn.execute(
            """INSERT INTO agent_runtime_sessions (
                   runtime_session_id, attempt_id, launch_key, status, created_at,
                   started_at, finished_at, engine_name
               ) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)""",
            (
                "runtime-session-1",
                attempt_id,
                "launch-session-projection-1",
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:00:01+00:00",
                "2026-07-12T00:00:03+00:00",
                "claude-code",
            ),
        )
        conn.execute(
            """UPDATE agent_runtime_sessions
               SET engine_session_key = ?, failure_reason = ?
               WHERE runtime_session_id = ?""",
            ("tenant-runtime-secret", "/home/tenant/private-runtime-error", "runtime-session-1"),
        )
        conn.execute(
            """INSERT INTO task_dispatch_outbox (
                   dispatch_id, task_id, attempt_id, status, created_at, updated_at,
                   launch_state, runtime_launch_key, dispatcher_id, last_error
               ) VALUES (?, ?, ?, 'completed', ?, ?, 'launched', ?, ?, ?)""",
            (
                "dispatch-session-projection-1",
                task.task_id,
                attempt_id,
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:00:03+00:00",
                "runtime-launch-secret",
                "dispatcher-secret",
                "/home/tenant/private-dispatch-error",
            ),
        )
        conn.execute(
            """INSERT INTO project_members (
                   project_id, user_id, role, can_publish, created_at, updated_at
               ) VALUES (?, ?, 'viewer', 0, ?, ?)""",
            (project_id, "viewer", "2026-07-12T00:00:00+00:00", "2026-07-12T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
               VALUES (?, 1, 'message', ?, ?)""",
            (task.task_id, durable_output, "2026-07-12T00:00:02+00:00"),
        )
        conn.execute(
            "UPDATE tasks SET error_summary = ? WHERE task_id = ?",
            ("engine failed at /home/ainrf_tenants/owner/private-workspace", task.task_id),
        )
        conn.commit()

    projection = SessionProjectionService(state_root)
    task_projection = TaskProjectionService(state_root)
    session, attempts = projection.get_session(task.task_id, owner)

    assert session["id"] == task.task_id
    assert session["task_count"] == 1
    assert session["total_duration_ms"] == 2000
    assert session["total_cost_usd"] == 0.42
    assert attempts[0]["task_id"] == task.task_id
    assert attempts[0]["duration_ms"] == 2000

    listed, total, has_more, next_cursor = projection.list_sessions(
        project_id=project_id,
        user=owner,
        status=None,
        cursor=None,
        limit=20,
    )
    assert total == 1
    assert has_more is False
    assert next_cursor is None
    assert listed == [session]
    assert projection.batch_details([task.task_id, "not-visible"], owner) == {
        task.task_id: attempts,
        "not-visible": [],
    }

    # B3 viewers can read the Project's Task dialogue and Attempt projection,
    # but an unrelated guessed Task remains a 404-shaped absence.
    shared_task = task_projection.task(task.task_id, viewer)
    assert shared_task["task_id"] == task.task_id
    assert shared_task["error_summary"] is None
    assert task_projection.task(task.task_id, owner)["error_summary"] == (
        "engine failed at /home/ainrf_tenants/owner/private-workspace"
    )
    assert task_projection.task(task.task_id, administrator)["error_summary"] == (
        "engine failed at /home/ainrf_tenants/owner/private-workspace"
    )
    viewer_attempt = task_projection.attempts(task.task_id, viewer)[0]
    assert viewer_attempt["attempt_id"] == attempt_id
    viewer_runtime = _first_runtime(viewer_attempt)
    viewer_dispatch = _mapping(viewer_attempt["dispatch"])
    assert viewer_runtime["engine_session_key"] is None
    assert viewer_runtime["failure_reason"] is None
    assert viewer_dispatch["runtime_launch_key"] is None
    assert viewer_dispatch["dispatcher_id"] is None
    assert viewer_dispatch["last_error"] is None
    assert viewer_attempt["failure_reason"] is None
    assert viewer_attempt["stop_reason"] is None
    assert viewer_attempt["authorization_environment_id"] is None
    assert viewer_attempt["authorization_grant_version"] is None
    assert viewer_attempt["authorization_checked_at"] is None
    assert viewer_attempt["stop_requested_at"] is None
    assert viewer_attempt["stop_requested_reason"] is None
    administrator_attempt = task_projection.attempts(task.task_id, administrator)[0]
    administrator_runtime = _first_runtime(administrator_attempt)
    administrator_dispatch = _mapping(administrator_attempt["dispatch"])
    assert administrator_runtime["engine_session_key"] == "tenant-runtime-secret"
    assert administrator_runtime["failure_reason"] == "/home/tenant/private-runtime-error"
    assert administrator_dispatch["runtime_launch_key"] == "runtime-launch-secret"
    assert administrator_dispatch["dispatcher_id"] == "dispatcher-secret"
    assert administrator_dispatch["last_error"] == "/home/tenant/private-dispatch-error"
    assert administrator_attempt["failure_reason"] == "/home/tenant/private-attempt-error"
    assert administrator_attempt["stop_reason"] == "/home/tenant/private-stop-reason"
    assert administrator_attempt["authorization_environment_id"] == "environment-private-id"
    assert administrator_attempt["authorization_grant_version"] == 7
    assert administrator_attempt["authorization_checked_at"] == "2026-07-12T00:00:01+00:00"
    assert administrator_attempt["stop_requested_at"] == "2026-07-12T00:00:02+00:00"
    assert administrator_attempt["stop_requested_reason"] == "/home/tenant/private-stop-request"
    viewer_output = task_projection.outputs(task.task_id, viewer, after_seq=0, limit=20)[0].content
    assert "viewer-output-token" not in viewer_output
    assert "sk-viewer-output-secret" not in viewer_output
    assert "/home/ainrf_tenants/owner/private-workspace" not in viewer_output
    assert "[REDACTED]" in viewer_output
    assert "[REDACTED_PATH]" in viewer_output
    # The data remains raw evidence in SQLite for the Task owner and the
    # administrator-only troubleshooting surface; the redaction is a read
    # projection for collaborators, not a destructive mutation.
    assert task_projection.outputs(task.task_id, owner, after_seq=0, limit=20)[0].content == (
        durable_output
    )
    assert (
        task_projection.outputs(task.task_id, administrator, after_seq=0, limit=20)[0].content
        == durable_output
    )
    viewer_session, viewer_attempts = projection.get_session(task.task_id, viewer)
    assert viewer_session["id"] == task.task_id
    assert viewer_attempts == attempts
    viewer_listed, viewer_total, viewer_has_more, viewer_next_cursor = projection.list_sessions(
        project_id=project_id,
        user=viewer,
        status=None,
        cursor=None,
        limit=20,
    )
    assert viewer_listed == [session]
    assert (viewer_total, viewer_has_more, viewer_next_cursor) == (1, False, None)
    viewer_global_tasks = task_projection.list_tasks(
        viewer,
        project_id=None,
        include_archived=False,
        limit=20,
        sort="updated",
    )
    assert [item["task_id"] for item in viewer_global_tasks] == [task.task_id]
    viewer_global_sessions, viewer_global_total, _, _ = projection.list_sessions(
        project_id=None,
        user=viewer,
        status=None,
        cursor=None,
        limit=20,
    )
    assert viewer_global_sessions == [session]
    assert viewer_global_total == 1
    assert projection.batch_details([task.task_id], viewer) == {task.task_id: attempts}
    with pytest.raises(DomainNotFoundError):
        task_projection.task(task.task_id, outsider)
    with pytest.raises(DomainNotFoundError):
        projection.get_session(task.task_id, outsider)
    assert (
        task_projection.list_tasks(
            outsider,
            project_id=None,
            include_archived=False,
            limit=20,
            sort="updated",
        )
        == []
    )
    assert projection.batch_details([task.task_id], outsider) == {task.task_id: []}
    assert not (state_root / "runtime" / "sessions.sqlite3").exists()

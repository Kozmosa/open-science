"""V2 Session API projection tests."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.db import connect
from ainrf.domain import (
    AttemptService,
    DomainService,
    ProjectContextService,
    SessionProjectionService,
)

pytestmark = [pytest.mark.unit]


def test_task_attempts_project_to_session_and_attempts(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    domain = DomainService(state_root)
    project = domain.create_project(owner, name="Project")
    context = ProjectContextService(state_root)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    task = tasks.create_task(
        str(project["project_id"]),
        "workspace",
        "environment",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "prompt",
        "owner",
    )
    attempt_id = AttemptService(state_root).create_attempt(task.task_id, trigger="initial")
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            """UPDATE agent_task_attempts
               SET status = 'succeeded', token_usage_json = ?, cost_usd = ?
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
        conn.commit()

    projection = SessionProjectionService(state_root)
    session, attempts = projection.get_session(task.task_id, owner)

    assert session["id"] == task.task_id
    assert session["task_count"] == 1
    assert session["total_duration_ms"] == 2000
    assert session["total_cost_usd"] == 0.42
    assert attempts[0]["task_id"] == task.task_id
    assert attempts[0]["duration_ms"] == 2000

    listed, total, has_more, next_cursor = projection.list_sessions(
        project_id=str(project["project_id"]),
        owner_user_id="owner",
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
    assert not (state_root / "runtime" / "sessions.sqlite3").exists()

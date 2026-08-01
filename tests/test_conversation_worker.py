from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect, run_pending
from ainrf.domain.conversation_service import ConversationApplicationService
from ainrf.domain.conversation_worker import ConversationDispatcher
from ainrf.harness_engine.base import EngineEvent, ExecutionContext, HarnessEngineType
from ainrf.harness_engine.conversation_adapter import ConversationRuntimeAdapter
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine

pytestmark = [pytest.mark.engine]

_USER: dict[str, object] = {"id": "user-1", "role": "user"}


class FakeRuntimeAdapter(ConversationRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(CodexAppServerEngine())

    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        callback = emit
        await callback(  # type: ignore[operator]
            EngineEvent(event_type="message", payload={"role": "assistant", "content": "done"})
        )
        await callback(  # type: ignore[operator]
            EngineEvent(event_type="status", payload={"status": "succeeded"})
        )


class NoAcceptanceRuntimeAdapter(FakeRuntimeAdapter):
    async def start_turn(self, context: ExecutionContext, emit: object) -> None:
        _ = context, emit


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    root = tmp_path / "ainrf-state"
    db_path = root / "runtime" / "agentic_researcher.sqlite3"
    db_path.parent.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                connection_fingerprint, created_at, updated_at
            ) VALUES ('environment-1', 'local', 'user-1', 'Local', '{}', 'fp', 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO workspaces (
                workspace_id, label, owner_user_id, environment_id, canonical_path,
                created_at, updated_at
            ) VALUES ('workspace-1', 'ws', 'user-1', 'environment-1', ?, 'now', 'now')""",
            (str(workspace),),
        )
        conn.execute(
            """INSERT INTO projects (
                project_id, owner_user_id, name, status, created_at, updated_at
            ) VALUES ('project-1', 'user-1', 'Project', 'active', 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-1', 'workspace-1', 'active', 1, 'user-1', 'now', 'now')"""
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at,
                owner_user_id
            ) VALUES (
                'task-1', 'project-1', 'workspace-1', 'environment-1', 'general',
                'codex-app-server', 'queued', 'Conversation', 'hello', 'now', 'now', 'user-1'
            )
            """
        )
        conn.commit()
    application = ConversationApplicationService(root)
    application.initialize_task("task-1", _USER)
    application.create_turn("task-1", _USER, input={"text": "hello"}, idempotency_key="create-1")
    return root


@pytest.mark.anyio
async def test_dispatcher_projects_engine_events_to_canonical_items(state_root: Path) -> None:
    adapter = FakeRuntimeAdapter()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: adapter,
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    assert await dispatcher.run_once() is False

    task = ConversationApplicationService(state_root).read_task("task-1", _USER)
    turns = ConversationApplicationService(state_root).list_turns("task-1", _USER)
    items = ConversationApplicationService(state_root).list_items("task-1", _USER)
    assert task["runtime_status"] == "idle"
    assert turns[0]["status"] == "completed"
    assert [item["item_type"] for item in items] == ["user_message", "agent_message"]


@pytest.mark.anyio
async def test_worker_crash_before_delivery_reclaims_same_submission_without_extra_turn(
    state_root: Path,
) -> None:
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute("SELECT submission_id FROM turn_submissions").fetchone()
        conn.execute(
            """
            UPDATE turn_submissions
            SET status = 'claimed', claimed_at = '2000-01-01T00:00:00+00:00',
                updated_at = '2000-01-01T00:00:00+00:00'
            WHERE submission_id = ?
            """,
            (submission["submission_id"],),
        )
        conn.commit()
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: FakeRuntimeAdapter(),
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    turns = ConversationApplicationService(state_root).list_turns("task-1", _USER)
    items = ConversationApplicationService(state_root).list_items("task-1", _USER)
    assert len(turns) == 1
    assert [item["item_type"] for item in items].count("user_message") == 1


@pytest.mark.anyio
async def test_unproven_delivery_becomes_unknown_without_materializing_or_replaying_turn(
    state_root: Path,
) -> None:
    dispatcher = ConversationDispatcher(
        state_root,
        adapter_factory=lambda _engine_type: NoAcceptanceRuntimeAdapter(),
        context_factory=lambda claim: ExecutionContext(
            task_id=claim.task_id,
            working_directory="/tmp",
            rendered_prompt=str(claim.input["text"]),
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key=claim.submission_id,
        ),
    )

    assert await dispatcher.run_once() is True
    assert await dispatcher.run_once() is False
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute("SELECT status, failure_code FROM turn_submissions").fetchone()
        turn_count = conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0]
    assert submission["status"] == "delivery_unknown"
    assert submission["failure_code"] == "provider_acceptance_unproven"
    assert turn_count == 0

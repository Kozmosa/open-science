from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect, run_pending
from ainrf.domain.conversation_contracts import TurnItemActor, TurnItemType
from ainrf.domain.conversation_execution import ConversationExecutionService
from ainrf.domain.conversation_service import ConversationApplicationService

pytestmark = [pytest.mark.engine, pytest.mark.concurrent]

_USER: dict[str, object] = {"id": "user-1", "role": "user"}


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    root = tmp_path / "ainrf-state"
    db_path = root / "runtime" / "agentic_researcher.sqlite3"
    db_path.parent.mkdir(parents=True)
    with closing(connect(db_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                connection_fingerprint, created_at, updated_at
            ) VALUES ('environment-1', 'local', 'user-1', 'Local', '{}', 'fp', ?, ?)
            """,
            ("2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, label, owner_user_id, environment_id, canonical_path,
                created_at, updated_at
            ) VALUES ('workspace-1', 'ws', 'user-1', 'environment-1', '/tmp', ?, ?)
            """,
            ("2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, created_at, updated_at
            ) VALUES ('project-1', 'user-1', 'Project', 'active', ?, ?)
            """,
            ("2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-1', 'workspace-1', 'active', 1, 'user-1', ?, ?)
            """,
            ("2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at,
                owner_user_id
            ) VALUES (
                'task-1', 'project-1', 'workspace-1', 'environment-1', 'general',
                'codex-app-server', 'queued', 'Conversation', 'hello',
                '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00', 'user-1'
            )
            """
        )
        conn.commit()
    auth = AuthService(state_root=root)
    auth.initialize()
    auth.grant_environment(
        env_id="environment-1",
        user_id="user-1",
        max_tasks=None,
        granted_by="admin",
        reason="conversation execution fixture",
    )
    application = ConversationApplicationService(root)
    application.initialize_task("task-1", _USER)
    application.create_turn(
        "task-1",
        _USER,
        input={"text": "hello"},
        idempotency_key="create-1",
    )
    return root


def test_submission_claim_is_single_winner_and_opens_canonical_execution(
    state_root: Path,
) -> None:
    def claim() -> object:
        return ConversationExecutionService(state_root).claim_next_submission()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))

    winners = [candidate for candidate in claims if candidate is not None]
    assert len(winners) == 1
    claimed = winners[0]
    execution_service = ConversationExecutionService(state_root)
    execution_service.begin_delivery(claimed.submission_id)
    execution = execution_service.accept_and_open_execution(
        claimed,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_turn_kind="turn",
        native_turn_ref="native-turn-1",
        native_runtime_kind="process",
        native_runtime_ref="runtime-1",
        evidence={"source": "driver"},
    )
    item = execution_service.append_item(
        execution,
        item_type=TurnItemType.AGENT_MESSAGE,
        actor=TurnItemActor.AGENT,
        payload={"text": "done"},
        native_provenance={"source": "driver"},
        native_item_id="native-item-1",
    )

    assert execution.task_id == "task-1"
    assert execution.turn_id == claimed.reserved_turn_id
    assert item["task_item_seq"] == 2
    assert item["turn_item_seq"] == 2

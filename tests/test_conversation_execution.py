from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

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

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect, run_pending
from ainrf.domain.conversation_contracts import (
    ConversationContractError,
    TurnItemActor,
    TurnItemType,
    TurnStatus,
)
from ainrf.domain.conversation_execution import ConversationExecutionService
from ainrf.domain.conversation_service import ConversationApplicationService
from ainrf.domain.service import DomainConflictError

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
                harness_engine, title, prompt, created_at, updated_at,
                owner_user_id
            ) VALUES (
                'task-1', 'project-1', 'workspace-1', 'environment-1', 'vanilla',
                'codex-app-server', 'Conversation', 'hello',
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
        native_conversation_kind="thread",
        native_conversation_ref="thread-1",
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

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        turn = conn.execute(
            "SELECT binding_id FROM task_turns WHERE turn_id = ?",
            (execution.turn_id,),
        ).fetchone()
        runtime = conn.execute(
            "SELECT binding_id FROM runtime_executions WHERE runtime_execution_id = ?",
            (execution.runtime_execution_id,),
        ).fetchone()
        binding = conn.execute(
            "SELECT binding_id, status, native_conversation_ref FROM engine_conversation_bindings"
        ).fetchone()
    assert binding is not None and tuple(binding[1:]) == ("active", "thread-1")
    assert turn is not None and turn["binding_id"] == binding["binding_id"]
    assert runtime is not None and runtime["binding_id"] == binding["binding_id"]


def test_zero_environment_capacity_keeps_submission_reclaimable(state_root: Path) -> None:
    execution_service = ConversationExecutionService(state_root)
    claim = execution_service.claim_next_submission()
    assert claim is not None

    with pytest.raises(DomainConflictError, match="capacity is exhausted"):
        execution_service.begin_delivery(claim.submission_id, max_concurrent_tasks=0)

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        submission = conn.execute(
            "SELECT status, failure_code FROM turn_submissions WHERE submission_id = ?",
            (claim.submission_id,),
        ).fetchone()
    assert submission is not None and tuple(submission) == ("claimed", None)


def test_one_task_cannot_hold_two_external_delivery_slots(state_root: Path) -> None:
    application = ConversationApplicationService(state_root)
    second = application.create_turn(
        "task-1",
        _USER,
        input={"text": "second"},
        idempotency_key="create-second",
    )
    execution_service = ConversationExecutionService(state_root)
    first_claim = execution_service.claim_next_submission()
    assert first_claim is not None
    execution_service.begin_delivery(first_claim.submission_id)
    second_claim = execution_service.claim_next_submission()
    assert second_claim is not None and second_claim.submission_id == second["submission_id"]

    with pytest.raises(DomainConflictError, match="already holds"):
        execution_service.begin_delivery(second_claim.submission_id)


def test_new_native_conversation_supersedes_binding_without_repointing_history(
    state_root: Path,
) -> None:
    execution_service = ConversationExecutionService(state_root)
    first_claim = execution_service.claim_next_submission()
    assert first_claim is not None
    execution_service.begin_delivery(first_claim.submission_id)
    first = execution_service.accept_and_open_execution(
        first_claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-first",
        native_turn_kind="turn",
        native_turn_ref="native-turn-first",
        native_runtime_kind="process",
        native_runtime_ref="runtime-first",
        evidence={"source": "driver"},
    )
    execution_service.finish_execution(
        first,
        status=TurnStatus.COMPLETED,
        evidence={"source": "driver"},
    )

    application = ConversationApplicationService(state_root)
    application.create_turn(
        "task-1",
        _USER,
        input={"text": "next"},
        idempotency_key="create-next",
    )
    second_claim = execution_service.claim_next_submission()
    assert second_claim is not None
    execution_service.begin_delivery(second_claim.submission_id)
    second = execution_service.accept_and_open_execution(
        second_claim,
        engine_family="codex",
        engine_driver="codex-app-server",
        native_conversation_kind="thread",
        native_conversation_ref="thread-second",
        native_turn_kind="turn",
        native_turn_ref="native-turn-second",
        native_runtime_kind="process",
        native_runtime_ref="runtime-second",
        evidence={"source": "driver"},
    )
    with pytest.raises(ConversationContractError, match="binding identity"):
        application.accept_submission(
            first_claim.submission_id,
            native_turn_kind="turn",
            native_turn_ref="native-turn-first",
            engine_family="codex",
            engine_driver="codex-app-server",
            contract_version=1,
            delivery_evidence={"source": "driver-replay"},
            native_conversation_kind="thread",
            native_conversation_ref="thread-wrong",
        )
    first_replay = application.accept_submission(
        first_claim.submission_id,
        native_turn_kind="turn",
        native_turn_ref="native-turn-first",
        engine_family="codex",
        engine_driver="codex-app-server",
        contract_version=1,
        delivery_evidence={"source": "driver-replay"},
        native_conversation_kind="thread",
        native_conversation_ref="thread-first",
    )

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        bindings = conn.execute(
            "SELECT binding_id, binding_seq, status, native_conversation_ref "
            "FROM engine_conversation_bindings ORDER BY binding_seq"
        ).fetchall()
        turns = conn.execute(
            "SELECT turn_id, binding_id FROM task_turns ORDER BY turn_seq"
        ).fetchall()
        runtimes = conn.execute(
            "SELECT turn_id, binding_id FROM runtime_executions ORDER BY created_at"
        ).fetchall()

    assert [tuple(row[1:]) for row in bindings] == [
        (1, "superseded", "thread-first"),
        (2, "active", "thread-second"),
    ]
    assert first_replay["turn_id"] == first.turn_id
    assert [row["turn_id"] for row in turns] == [first.turn_id, second.turn_id]
    assert [row["binding_id"] for row in turns] == [
        bindings[0]["binding_id"],
        bindings[1]["binding_id"],
    ]
    assert [row["binding_id"] for row in runtimes] == [
        bindings[0]["binding_id"],
        bindings[1]["binding_id"],
    ]

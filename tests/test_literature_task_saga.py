"""Durable Literature research-Task intent recovery tests."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect, run_pending
from ainrf.domain import DomainService, ProjectContextService, TaskDispatcher
from ainrf.domain_control import (
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    MaintenanceModeError,
)
from ainrf.literature.tracking import LiteratureTrackingService, WorkItem
from ainrf.literature.work import execute_work_item, process_durable_work_item
from ainrf.literature.task_saga import (
    LiteratureTaskSagaService,
    ResearchTaskIdempotencyConflictError,
    ResearchTaskLeaseLostError,
    ResearchTaskWorkspaceRequiredError,
)
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import seed_user

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _ensure_v2_cutover(state_root: Path) -> None:
    """Build v2 evidence once for direct saga tests.

    A direct service invocation must exercise the same fuse as the HTTP and
    domain-worker paths.  The fixture creates only pytest-owned backup
    evidence beside the scratch state root.
    """

    if DomainCutoverController(state_root).status().state != "v2":
        prepare_committed_v2_cutover(state_root, state_root.parent)


def _saga(state_root: Path) -> LiteratureTaskSagaService:
    return LiteratureTaskSagaService(state_root, artifact_sha=V2_ARTIFACT_SHA)


def _scope(state_root: Path) -> tuple[dict[str, object], str, str]:
    _ensure_v2_cutover(state_root)
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    auth = AuthService(state_root=state_root)
    auth.initialize()
    seed_user(auth, username="literature-owner", role="member", user_id="owner")
    seed_user(auth, username="literature-admin", role="admin", user_id="admin")
    domain = DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="literature task saga test",
    )
    project = domain.create_project(owner, name="Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        owner,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/lit",
        label="Lit",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, owner, idempotency_key="attach")
    domain.set_primary_workspace(project_id, workspace_id, owner, idempotency_key="link")
    context = ProjectContextService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    context.save_draft(project_id, "context", owner)
    context.publish(project_id, owner)
    return owner, project_id, workspace_id


def _v2_scope(state_root: Path, tmp_path: Path) -> tuple[dict[str, object], str, str]:
    """Create an executable domain scope behind the committed v2 fuse."""

    prepare_committed_v2_cutover(state_root, tmp_path)
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    auth = AuthService(state_root=state_root)
    auth.initialize()
    seed_user(auth, username="v2-literature-owner", role="member", user_id="owner")
    seed_user(auth, username="v2-literature-admin", role="admin", user_id="admin")
    domain = DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    environment = domain.create_environment(
        admin, alias="v2-host", display_name="V2 Host", connection={}
    )
    environment_id = str(environment["environment_id"])
    auth.grant_environment(
        env_id=environment_id,
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="v2 literature worker test",
    )
    project = domain.create_project(owner, name="V2 Literature Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(tmp_path / "v2-literature-workspace"),
        label="V2 Literature Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, owner, idempotency_key="v2-attach")
    domain.set_primary_workspace(project_id, workspace_id, owner, idempotency_key="v2-link")
    context = ProjectContextService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    context.save_draft(project_id, "V2 context", owner)
    context.publish(project_id, owner, idempotency_key="v2-context")
    return owner, project_id, workspace_id


def _seed_legacy_paper(state_root: Path, *, user_id: str = "owner") -> None:
    literature_db = state_root / "runtime" / "literature.sqlite3"
    with connect(literature_db) as conn:
        run_pending(conn, "literature")
        conn.execute(
            """
            INSERT INTO literature_subscriptions(
                subscription_id, user_id, label, keywords_json, arxiv_categories_json,
                seed_paper_ids_json, frequency, is_active, created_at, max_results
            ) VALUES ('sub', ?, '', '[]', '[]', '[]', 'daily', 1, 'now', 10)
            """,
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO literature_papers(
                paper_id, title, authors_json, abstract, published_at, arxiv_category, created_at
            ) VALUES ('paper', 'Paper', '[]', 'Abstract', '', '', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO literature_subscription_papers(subscription_id, paper_id, created_at)
            VALUES ('sub', 'paper', 'now')
            """
        )
        conn.commit()


def _task_count(state_root: Path) -> int:
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
    assert row is not None
    return int(row[0])


def _retryable_intent_without_task(
    state_root: Path,
    *,
    owner: dict[str, object],
    project_id: str,
    workspace_id: str,
    idempotency_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Persist an intent whose API-side Task write fails once.

    This simulates an API process that committed its Literature outbox but
    failed before the independent domain transaction.  A fresh worker must
    later create the Task using the same deterministic idempotency key.
    """

    saga = LiteratureTaskSagaService(state_root, artifact_sha=V2_ARTIFACT_SHA)

    def fail_task_create(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise OSError("simulated domain Task write failure")

    monkeypatch.setattr(saga._tasks, "create_task", fail_task_create)
    failed = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
    )
    assert failed["status"] == "retryable_failed"
    assert failed["task_id"] is None
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        conn.execute(
            """
            UPDATE literature_research_task_intents
            SET next_retry_at = '2000-01-01T00:00:00+00:00'
            WHERE intent_id = ?
            """,
            (failed["intent_id"],),
        )
        conn.execute(
            """
            UPDATE literature_work_items
            SET available_at = '2000-01-01T00:00:00+00:00'
            WHERE work_item_id = ?
            """,
            (failed["work_item_id"],),
        )
        conn.commit()
    return failed


def _former_admin_scope(state_root: Path) -> tuple[dict[str, object], str, str, AuthService]:
    """Create a scope that an administrator can use but a member cannot."""

    _ensure_v2_cutover(state_root)
    former_admin: dict[str, object] = {"id": "former-admin", "role": "admin"}
    project_owner: dict[str, object] = {"id": "project-owner", "role": "member"}
    auth = AuthService(state_root=state_root)
    auth.initialize()
    seed_user(auth, username="former-admin", role="admin", user_id="former-admin")
    seed_user(auth, username="project-owner", role="member", user_id="project-owner")
    domain = DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    environment = domain.create_environment(
        former_admin, alias="former-admin-host", display_name="Former Admin Host", connection={}
    )
    project = domain.create_project(project_owner, name="Project owned by another user")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        former_admin,
        environment_id=str(environment["environment_id"]),
        canonical_path=str(state_root / "former-admin-workspace"),
        label="Former Admin Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(
        project_id, workspace_id, former_admin, idempotency_key="former-admin-attach"
    )
    domain.set_primary_workspace(
        project_id, workspace_id, former_admin, idempotency_key="former-admin-primary"
    )
    context = ProjectContextService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    context.save_draft(project_id, "context", project_owner)
    context.publish(project_id, project_owner)
    return former_admin, project_id, workspace_id, auth


def test_literature_recovery_uses_current_role_after_admin_demotion(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable intent cannot retain an administrator capability after demotion."""

    former_admin, project_id, workspace_id, auth = _former_admin_scope(state_root)
    _seed_legacy_paper(state_root, user_id="former-admin")
    failed = _retryable_intent_without_task(
        state_root,
        owner=former_admin,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="former-admin-demoted",
        monkeypatch=monkeypatch,
    )

    seed_user(auth, username="former-admin", role="member", user_id="former-admin")
    recovered = _saga(state_root).recover_pending(worker_id="former-admin-recovery")

    assert len(recovered) == 1
    assert recovered[0]["status"] == "retryable_failed"
    assert recovered[0]["task_id"] is None
    assert _task_count(state_root) == 0
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT actor_role, status, last_error
            FROM literature_research_task_intents
            WHERE intent_id = ?
            """,
            (failed["intent_id"],),
        ).fetchone()
    assert row is not None
    assert row["actor_role"] == "admin"
    assert row["status"] == "retryable_failed"
    assert isinstance(row["last_error"], str) and row["last_error"]


def test_literature_recovery_refuses_disabled_actor(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling an actor after intent persistence blocks later Task creation."""

    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    failed = _retryable_intent_without_task(
        state_root,
        owner=owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="disabled-owner",
        monkeypatch=monkeypatch,
    )

    auth = AuthService(state_root=state_root)
    auth.disable_user("owner")
    recovered = _saga(state_root).recover_pending(worker_id="disabled-owner-recovery")

    assert len(recovered) == 1
    assert recovered[0]["status"] == "retryable_failed"
    assert recovered[0]["task_id"] is None
    assert _task_count(state_root) == 0
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT status, last_error FROM literature_research_task_intents
            WHERE intent_id = ?
            """,
            (failed["intent_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] == "retryable_failed"
    assert row["last_error"] == "attention_required: Literature actor is inactive"


def test_direct_literature_saga_refuses_uncommitted_domain_before_creating_an_intent(
    state_root: Path,
) -> None:
    """A worker import cannot bypass the HTTP v2/cutover admission gate."""

    with pytest.raises(DomainCutoverError, match="committed v2 artifact SHA"):
        LiteratureTaskSagaService(state_root).create_research_task(
            {"id": "owner", "role": "member"},
            paper_id="paper",
            subscription_id="sub",
            project_id="project",
            workspace_id="workspace",
            idempotency_key="legacy-bypass",
        )
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        count = conn.execute("SELECT COUNT(*) FROM literature_research_task_intents").fetchone()
    assert count is not None
    assert int(count[0]) == 0


def test_legacy_literature_worker_refuses_research_task_work_before_task_creation(
    state_root: Path,
) -> None:
    """The legacy worker may not turn a durable intent into a v2 Task."""

    service = LiteratureTrackingService(state_root)
    service.initialize()
    with pytest.raises(DomainCutoverError, match="committed domain v2 cutover"):
        asyncio.run(
            execute_work_item(
                service,
                WorkItem(
                    work_item_id="legacy-research-work",
                    kind="research_task",
                    payload={"intent_id": "legacy-intent"},
                ),
            )
        )
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
    assert count is not None
    assert int(count[0]) == 0


def test_literature_research_task_intent_is_idempotent_and_allows_distinct_keys(
    state_root: Path,
) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)

    first = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=None,
        idempotency_key="research-a",
    )
    repeated = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=None,
        idempotency_key="research-a",
    )
    different = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        task_preset="overview",
        idempotency_key="research-b",
    )

    assert first == repeated
    assert first["status"] == "completed"
    assert first["workspace_id"] == workspace_id
    assert first["task_id"] is not None
    assert different["status"] == "completed"
    assert different["task_id"] != first["task_id"]
    assert _task_count(state_root) == 2

    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        outbox = conn.execute(
            """
            SELECT outbox.status, work.status
            FROM literature_research_task_intents AS intent
            JOIN literature_outbox AS outbox ON outbox.work_item_id = intent.work_item_id
            JOIN literature_work_items AS work ON work.work_item_id = intent.work_item_id
            WHERE intent.intent_id = ?
            """,
            (first["intent_id"],),
        ).fetchone()
    assert outbox is not None
    assert tuple(outbox) == ("published", "completed")


def test_literature_research_task_concurrent_same_key_creates_one_task(
    state_root: Path,
) -> None:
    """The Literature intent and the Task write remain single-winner under a race."""

    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    barrier = Barrier(2)

    def create() -> dict[str, object]:
        barrier.wait(timeout=10)
        return _saga(state_root).create_research_task(
            owner,
            paper_id="paper",
            subscription_id="sub",
            project_id=project_id,
            workspace_id=workspace_id,
            idempotency_key="concurrent-same-key",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _index: create(), range(2)))

    assert first["status"] == second["status"] == "completed"
    assert first["intent_id"] == second["intent_id"]
    assert first["task_id"] == second["task_id"]
    assert _task_count(state_root) == 1
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        count = conn.execute(
            """SELECT COUNT(*) FROM literature_research_task_intents
               WHERE user_id = 'owner' AND paper_id = 'paper'
                 AND idempotency_key = 'concurrent-same-key'"""
        ).fetchone()
    assert count is not None
    assert int(count[0]) == 1


def test_literature_research_task_key_rejects_changed_request(state_root: Path) -> None:
    owner, project_id, _workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=None,
        idempotency_key="same-key",
    )

    with pytest.raises(ResearchTaskIdempotencyConflictError):
        saga.create_research_task(
            owner,
            paper_id="paper",
            subscription_id="sub",
            project_id=project_id,
            workspace_id=None,
            title="Changed title",
            idempotency_key="same-key",
        )


def test_literature_research_task_reuses_same_key_after_workspace_state_changes(
    state_root: Path,
) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    first = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=None,
        idempotency_key="retry-after-detach",
    )
    DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA).detach_workspace(
        project_id,
        workspace_id,
        owner,
        idempotency_key="detach-after-create",
        allow_no_primary=True,
    )

    repeated = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=None,
        idempotency_key="retry-after-detach",
    )

    assert repeated == first
    assert _task_count(state_root) == 1


def test_literature_research_task_recovers_task_created_link_without_duplicate_task(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    original = saga._persist_completed_link

    def fail_link_once(intent_id: str, worker_id: str, task_id: str) -> None:
        raise OSError("simulated Literature link write failure")

    monkeypatch.setattr(saga, "_persist_completed_link", fail_link_once)
    failed = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="recover-link",
    )

    assert failed["status"] == "retryable_failed"
    assert failed["task_id"] is not None
    assert _task_count(state_root) == 1
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        conn.execute(
            """
            UPDATE literature_research_task_intents
            SET next_retry_at = '2000-01-01T00:00:00+00:00'
            WHERE intent_id = ?
            """,
            (failed["intent_id"],),
        )
        conn.commit()
    monkeypatch.setattr(saga, "_persist_completed_link", original)
    AuthService(state_root=state_root).disable_user("owner")

    recovered = saga.recover_pending(worker_id="test-domain-worker")

    assert len(recovered) == 1
    assert recovered[0]["status"] == "completed"
    assert recovered[0]["task_id"] == failed["task_id"]
    assert _task_count(state_root) == 1


def test_literature_research_task_recovers_after_crash_before_task_checkpoint(
    state_root: Path,
) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    created = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="crash-before-checkpoint",
    )
    task_id = str(created["task_id"])
    intent_id = str(created["intent_id"])
    work_item_id = str(created["work_item_id"])
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        conn.execute(
            """
            UPDATE literature_research_task_intents
            SET task_id = NULL, status = 'pending', lease_owner = NULL,
                lease_expires_at = NULL, completed_at = NULL
            WHERE intent_id = ?
            """,
            (intent_id,),
        )
        conn.execute(
            """
            UPDATE literature_work_items
            SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL
            WHERE work_item_id = ?
            """,
            (work_item_id,),
        )
        conn.execute(
            "UPDATE literature_outbox SET status = 'pending' WHERE work_item_id = ?",
            (work_item_id,),
        )
        conn.commit()
    DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA).detach_workspace(
        project_id,
        workspace_id,
        owner,
        idempotency_key="detach-after-crash",
        allow_no_primary=True,
    )

    recovered = saga.recover_work_item(work_item_id, worker_id="delivery-loss-worker")

    assert recovered is not None
    assert recovered["status"] == "completed"
    assert recovered["task_id"] == task_id
    assert _task_count(state_root) == 1


def test_literature_research_task_link_completion_requires_current_lease(state_root: Path) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    completed = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="lease-cas",
    )
    assert isinstance(completed["task_id"], str)
    intent_id = str(completed["intent_id"])
    task_id = str(completed["task_id"])
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        conn.execute(
            """
            UPDATE literature_research_task_intents
            SET status = 'task_created', lease_owner = 'worker-a',
                lease_expires_at = '2999-01-01T00:00:00+00:00', completed_at = NULL
            WHERE intent_id = ?
            """,
            (intent_id,),
        )
        conn.execute(
            """
            UPDATE literature_work_items SET status = 'running'
            WHERE work_item_id = (
                SELECT work_item_id FROM literature_research_task_intents WHERE intent_id = ?
            )
            """,
            (intent_id,),
        )
        conn.execute(
            """
            UPDATE literature_outbox SET status = 'pending'
            WHERE work_item_id = (
                SELECT work_item_id FROM literature_research_task_intents WHERE intent_id = ?
            )
            """,
            (intent_id,),
        )
        conn.commit()

    with pytest.raises(ResearchTaskLeaseLostError):
        saga._persist_completed_link(intent_id, "worker-b", task_id)

    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        state = conn.execute(
            """
            SELECT intent.status, outbox.status AS outbox_status, work.status AS work_status
            FROM literature_research_task_intents AS intent
            JOIN literature_outbox AS outbox ON outbox.work_item_id = intent.work_item_id
            JOIN literature_work_items AS work ON work.work_item_id = intent.work_item_id
            WHERE intent.intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
    assert state is not None
    assert tuple(state) == ("task_created", "pending", "running")


def test_literature_summary_failure_never_rebuilds_completed_research_task(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed LLM summary is a Literature concern, not a Task retry trigger."""

    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    created = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="summary-failure-is-not-task-retry",
    )
    task_id = str(created["task_id"])
    tracking = LiteratureTrackingService(state_root)
    tracking.initialize()

    def summary_context(_summary_id: str) -> dict[str, object]:
        return {
            "summary_id": "summary-fixture",
            "paper_id": "paper",
            "title": "Paper",
            "authors_json": "[]",
            "abstract": "Abstract",
            "published_at": "",
            "primary_category": "",
        }

    class FailingSummarizer:
        def __init__(self, *, batch_size: int) -> None:
            assert batch_size == 1

        async def __aenter__(self) -> FailingSummarizer:
            return self

        async def __aexit__(
            self,
            _exc_type: object,
            _exc: object,
            _traceback: object,
        ) -> None:
            return None

        async def summarize(self, _papers: list[object]) -> None:
            raise RuntimeError("fixture LLM summary failure")

    monkeypatch.setattr(tracking, "summary_context", summary_context)
    monkeypatch.setattr("ainrf.literature.work.AnthropicSummarizer", FailingSummarizer)
    with pytest.raises(RuntimeError, match="fixture LLM summary failure"):
        asyncio.run(
            execute_work_item(
                tracking,
                WorkItem(
                    work_item_id="summary-work-fixture",
                    kind="summarize",
                    payload={"summary_id": "summary-fixture"},
                ),
                artifact_sha=V2_ARTIFACT_SHA,
            )
        )

    replayed = saga.create_research_task(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="summary-failure-is-not-task-retry",
    )
    assert replayed["task_id"] == task_id
    assert _task_count(state_root) == 1


def test_literature_research_task_preserves_maintenance_error_for_api_call(
    state_root: Path,
) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    saga = _saga(state_root)
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="operator", reason="test Literature saga maintenance")
    try:
        with pytest.raises(MaintenanceModeError):
            saga.create_research_task(
                owner,
                paper_id="paper",
                subscription_id="sub",
                project_id=project_id,
                workspace_id=workspace_id,
                idempotency_key="maintenance-error",
            )
    finally:
        maintenance.exit(actor_id="operator")

    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT status, last_error FROM literature_research_task_intents
            WHERE user_id = 'owner' AND paper_id = 'paper' AND idempotency_key = 'maintenance-error'
            """
        ).fetchone()
    assert row is not None
    assert row["status"] == "retryable_failed"
    assert "maintenance" in str(row["last_error"])


def test_literature_research_task_requires_owned_executable_primary(state_root: Path) -> None:
    owner, project_id, workspace_id = _scope(state_root)
    _seed_legacy_paper(state_root)
    domain = DomainService(state_root, artifact_sha=V2_ARTIFACT_SHA)
    domain.detach_workspace(
        project_id,
        workspace_id,
        owner,
        idempotency_key="detach",
        allow_no_primary=True,
    )
    saga = _saga(state_root)

    with pytest.raises(ResearchTaskWorkspaceRequiredError):
        saga.create_research_task(
            owner,
            paper_id="paper",
            subscription_id="sub",
            project_id=project_id,
            workspace_id=None,
            idempotency_key="needs-primary",
        )


def test_v2_domain_worker_recovers_retryable_literature_outbox_intent(
    state_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The committed dispatcher resumes the outbox without a cross-DB transaction."""

    owner, project_id, workspace_id = _v2_scope(state_root, tmp_path)
    _seed_legacy_paper(state_root)
    failed = _retryable_intent_without_task(
        state_root,
        owner=owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="domain-worker-recovery",
        monkeypatch=monkeypatch,
    )

    dispatcher = TaskDispatcher(
        state_root,
        dispatcher_id="literature-recovery-dispatcher",
        lease_seconds=3,
        artifact_sha=V2_ARTIFACT_SHA,
    )
    # This test isolates the B9 recovery pass from harness/tenant runtime
    # validation.  The next dispatcher cycle owns the newly created Task
    # attempt; the current one proves the saga completed before task claiming.
    monkeypatch.setattr(dispatcher._attempts, "claim_next", lambda *_args, **_kwargs: None)
    try:
        result = asyncio.run(dispatcher.run_once())
    finally:
        dispatcher.stop()

    assert result.outcome == "idle"
    assert _task_count(state_root) == 1
    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT intent.status, intent.task_id, work.status AS work_status,
                   outbox.status AS outbox_status
            FROM literature_research_task_intents AS intent
            JOIN literature_work_items AS work ON work.work_item_id = intent.work_item_id
            JOIN literature_outbox AS outbox ON outbox.work_item_id = intent.work_item_id
            WHERE intent.intent_id = ?
            """,
            (failed["intent_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] == "completed"
    assert isinstance(row["task_id"], str)
    assert (row["work_status"], row["outbox_status"]) == ("completed", "published")


def test_v2_literature_work_retries_when_committed_artifact_is_unavailable(
    state_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broker worker cannot complete a retryable intent without the v2 fuse SHA."""

    owner, project_id, workspace_id = _v2_scope(state_root, tmp_path)
    _seed_legacy_paper(state_root)
    failed = _retryable_intent_without_task(
        state_root,
        owner=owner,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key="artifact-fence",
        monkeypatch=monkeypatch,
    )
    monkeypatch.setenv("AINRF_STATE_ROOT", str(state_root))
    monkeypatch.delenv("OPENSCIENCE_DOMAIN_ARTIFACT_SHA", raising=False)
    monkeypatch.delenv("AINRF_DOMAIN_ARTIFACT_SHA", raising=False)

    with pytest.raises(DomainCutoverError, match="required for v2 Literature"):
        process_durable_work_item(str(failed["work_item_id"]))

    with connect(state_root / "runtime" / "literature.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT intent.status, work.status AS work_status, outbox.status AS outbox_status
            FROM literature_research_task_intents AS intent
            JOIN literature_work_items AS work ON work.work_item_id = intent.work_item_id
            JOIN literature_outbox AS outbox ON outbox.work_item_id = intent.work_item_id
            WHERE intent.intent_id = ?
            """,
            (failed["intent_id"],),
        ).fetchone()
    assert row is not None
    assert (row["status"], row["work_status"], row["outbox_status"]) == (
        "retryable_failed",
        "retrying",
        "pending",
    )

"""Durable Today overview refresh-job tests."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ainrf.db import connect
from ainrf.domain.overview_jobs import (
    OverviewSnapshotPlanner,
    OverviewSnapshotService,
    _CardResult,
)
from ainrf.domain_control import DomainCutoverError, DomainMaintenanceService, MaintenanceModeError

pytestmark = [pytest.mark.unit]


def _instant(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 12, hour, minute, tzinfo=UTC)


def _service(state_root: Path, artifact_sha: str) -> OverviewSnapshotService:
    return OverviewSnapshotService(state_root, artifact_sha=artifact_sha)


def _seed_domain(state_root: Path, owner_user_id: str) -> None:
    now = _instant(0).isoformat()
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, owner_user_id, display_name, connection_json,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '{}', 'active', ?, ?)
            """,
            (f"env-{owner_user_id}", f"host-{owner_user_id}", owner_user_id, "Host", now, now),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, status, is_default, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', 0, ?, ?)
            """,
            (f"project-{owner_user_id}", owner_user_id, "Overview", now, now),
        )
        conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                f"workspace-{owner_user_id}",
                owner_user_id,
                f"env-{owner_user_id}",
                f"/tmp/{owner_user_id}",
                "Workspace",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at,
                latest_output_seq, owner_user_id
            ) VALUES (?, ?, ?, ?, 'vanilla', 'claude-code', 'queued', ?, 'Prompt', ?, ?, 0, ?)
            """,
            (
                f"task-{owner_user_id}",
                f"project-{owner_user_id}",
                f"workspace-{owner_user_id}",
                f"env-{owner_user_id}",
                "Task",
                now,
                now,
                owner_user_id,
            ),
        )
        conn.commit()


def _seed_literature(state_root: Path, owner_user_id: str) -> None:
    from ainrf.literature.tracking import LiteratureTrackingService

    tracking = LiteratureTrackingService(state_root)
    tracking.initialize()
    now = _instant(0).isoformat()
    with closing(connect(state_root / "runtime" / "literature.sqlite3")) as conn:
        conn.execute(
            """
            INSERT INTO literature_catalog_papers (
                paper_id, provider, external_id, title, first_seen_at, last_seen_at
            ) VALUES (?, 'fixture', ?, 'Overview paper', ?, ?)
            """,
            (f"paper-{owner_user_id}", f"external-{owner_user_id}", now, now),
        )
        conn.execute(
            """
            INSERT INTO literature_user_paper_states (
                user_id, paper_id, is_read, is_saved, is_ignored, first_seen_at, last_seen_at
            ) VALUES (?, ?, 0, 1, 0, ?, ?)
            """,
            (owner_user_id, f"paper-{owner_user_id}", now, now),
        )
        conn.commit()


def _seed_resource_detection(state_root: Path, owner_user_id: str) -> Path:
    source_path = state_root / "detections" / f"env-{owner_user_id}.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(
            {
                "environment_id": f"env-{owner_user_id}",
                "status": "ready",
                "detected_at": _instant(0).isoformat(),
                "summary": "fixture resource snapshot",
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return source_path


def _card(snapshot: dict[str, object], card_id: str) -> dict[str, object]:
    cards = cast(list[object], snapshot["cards"])
    for item in cards:
        if isinstance(item, dict):
            candidate = cast(dict[str, object], item)
            if candidate.get("id") == card_id:
                return candidate
    raise AssertionError(f"Card {card_id} was not returned")


def _unavailable_literature(_owner: str, cutoff_at: str) -> _CardResult:
    return _CardResult(
        card_id="literature",
        data=None,
        source_status="unavailable",
        data_cutoff_at=cutoff_at,
        attention_required=True,
        error_summary="fixture literature source unavailable",
    )


def _all_failed_cards(_conn: sqlite3.Connection, _owner: str, cutoff_at: str) -> list[_CardResult]:
    return [
        _CardResult(
            card_id=card_id,
            data=None,
            source_status="failed",
            data_cutoff_at=cutoff_at,
            attention_required=True,
            error_summary="fixture card failure",
        )
        for card_id in ("domain", "literature", "resources")
    ]


def test_overview_active_jobs_are_idempotent_and_user_scoped(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)

    first = service.request_refresh("owner", now=_instant(1))
    duplicate = service.request_refresh("owner", now=_instant(1, 1))
    other = service.request_refresh("other", now=_instant(1, 2))

    assert duplicate["job_id"] == first["job_id"]
    assert other["job_id"] != first["job_id"]
    assert service.get_job("other", str(first["job_id"])) is None


def test_overview_compatibility_refresh_uses_a_maintenance_participant(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="test-operator", reason="verify overview writer drain")
    try:
        with pytest.raises(MaintenanceModeError):
            service.refresh("owner")
    finally:
        maintenance.exit(actor_id="test-operator")

    assert service.latest("owner") is None


def test_overview_job_schema_and_lease_recovery_are_durable(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        snapshot_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(overview_snapshots)")
        }
        job_indexes = {
            str(row["name"]) for row in conn.execute("PRAGMA index_list(overview_refresh_jobs)")
        }

    assert {
        "overview_refresh_jobs",
        "overview_refresh_card_states",
        "overview_planner_state",
    } <= tables
    assert {"data_cutoff_at", "source_status", "attention_required"} <= snapshot_columns
    assert {
        "idx_overview_refresh_jobs_schedule_slot",
        "idx_overview_refresh_jobs_active_owner",
        "idx_overview_refresh_jobs_claim",
        "idx_overview_refresh_jobs_lease_expiry",
    } <= job_indexes

    started = _instant(1)
    job = service.request_refresh("owner", now=started)
    first_claim = service.claim_next_job(
        "first-worker", now=started, lease_seconds=5, job_id=str(job["job_id"])
    )
    assert first_claim is not None

    after_expiry = started + timedelta(seconds=6)
    assert not service.heartbeat_job(first_claim, now=after_expiry, lease_seconds=5)
    assert service._fail_claim(first_claim, "stale worker", after_expiry) is None
    second_claim = service.claim_next_job(
        "second-worker", now=after_expiry, lease_seconds=5, job_id=str(job["job_id"])
    )
    assert second_claim is not None
    assert second_claim.lease_token != first_claim.lease_token
    assert not service.heartbeat_job(first_claim, now=after_expiry, lease_seconds=5)


def test_overview_retry_wait_is_due_only_after_backoff_and_survives_planner_restart(
    state_root: Path,
    committed_v2_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed scheduled slot remains the one active job across restart."""

    service = _service(state_root, committed_v2_state)
    _seed_domain(state_root, "owner")
    scheduled_at = datetime(2026, 7, 12, 22, 5, tzinfo=UTC)  # 06:05 Shanghai on Jul 13.
    job = service.request_refresh(
        "owner",
        trigger="scheduled",
        scheduled_for_date="2026-07-13",
        now=scheduled_at,
    )

    def fail_build(*_args: object, **_kwargs: object) -> list[_CardResult]:
        raise OSError("fixture planner crash while projecting cards")

    monkeypatch.setattr(service, "_build_cards", fail_build)
    first = service.run_job(str(job["job_id"]), "first-worker", now=scheduled_at)
    assert first.outcome == "retry_wait"
    waiting = service.get_job("owner", str(job["job_id"]))
    assert waiting is not None
    assert waiting["status"] == "retry_wait"
    assert waiting["retry_count"] == 1
    assert isinstance(waiting["next_retry_at"], str)

    before_due = scheduled_at + timedelta(seconds=1)
    assert service.claim_next_job("early-worker", now=before_due, job_id=str(job["job_id"])) is None
    assert service.schedule_due_refreshes(now=before_due, active_user_ids=("owner",)) == []

    retry_at = datetime.fromisoformat(str(waiting["next_retry_at"]))
    restarted = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-restart-planner",
        artifact_sha=committed_v2_state,
        active_user_ids=lambda: ("owner",),
    )
    try:
        early_cycle = restarted.run_once(now=before_due)
        recovered_cycle = restarted.run_once(now=retry_at)
    finally:
        restarted.stop(now=retry_at + timedelta(seconds=1))

    assert str(job["job_id"]) not in early_cycle.completed_job_ids
    assert recovered_cycle.scheduled_job_ids == ()
    assert str(job["job_id"]) in recovered_cycle.completed_job_ids
    completed = service.get_job("owner", str(job["job_id"]))
    assert completed is not None
    assert completed["status"] in {"succeeded", "partial"}
    assert completed["retry_count"] == 1
    assert completed["next_retry_at"] is None
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        slot_count = conn.execute(
            """SELECT COUNT(*) FROM overview_refresh_jobs
               WHERE owner_user_id = ? AND scheduled_for_date = ?""",
            ("owner", "2026-07-13"),
        ).fetchone()
    assert slot_count is not None
    assert int(slot_count[0]) == 1


def test_overview_planner_state_write_requires_committed_v2_fuse(state_root: Path) -> None:
    planner = OverviewSnapshotPlanner(state_root, planner_id="uncommitted-overview-planner")

    with pytest.raises(DomainCutoverError):
        planner.start(now=_instant(1))

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        state = conn.execute("SELECT 1 FROM overview_planner_state WHERE singleton = 1").fetchone()
    assert state is None


def test_overview_planner_waits_for_shanghai_six_and_catches_up_after_restart(
    state_root: Path, committed_v2_state: str
) -> None:
    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-test-planner",
        artifact_sha=committed_v2_state,
        active_user_ids=lambda: ("alice", "bob"),
    )
    try:
        before_six = planner.run_once(now=_instant(21, 59))  # 05:59 Asia/Shanghai
        after_six = planner.run_once(now=_instant(22, 5))  # 06:05 Asia/Shanghai
        restart_cycle = planner.run_once(now=_instant(23, 0))
    finally:
        planner.stop(now=_instant(23, 1))

    assert before_six.scheduled_job_ids == ()
    assert len(after_six.scheduled_job_ids) == 2
    assert restart_cycle.scheduled_job_ids == ()
    service = _service(state_root, committed_v2_state)
    assert service.get_job("alice", str(after_six.scheduled_job_ids[0])) is not None
    assert service.get_job("bob", str(after_six.scheduled_job_ids[1])) is not None


def test_overview_planner_backfills_historical_slots_before_shanghai_six(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    _seed_domain(state_root, "owner")
    previous = service.request_refresh(
        "owner",
        trigger="scheduled",
        scheduled_for_date="2026-07-10",
        now=datetime(2026, 7, 9, 22, 5, tzinfo=UTC),
    )
    assert (
        service.run_job(
            str(previous["job_id"]),
            "overview-initial-worker",
            now=datetime(2026, 7, 9, 22, 5, tzinfo=UTC),
        ).outcome
        == "partial"
    )

    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-pre-six-catchup-planner",
        artifact_sha=committed_v2_state,
        active_user_ids=lambda: ("owner",),
    )
    before_six = datetime(2026, 7, 12, 21, 59, tzinfo=UTC)  # 05:59 Shanghai on Jul 13.
    after_six = datetime(2026, 7, 12, 22, 0, tzinfo=UTC)  # 06:00 Shanghai on Jul 13.
    try:
        catchup = planner.run_once(now=before_six)
        today = planner.run_once(now=after_six)
    finally:
        planner.stop(now=after_six + timedelta(minutes=1))

    assert len(catchup.scheduled_job_ids) == 2
    assert len(today.scheduled_job_ids) == 1
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        slots = [
            (str(row["scheduled_for_date"]), str(row["trigger"]))
            for row in conn.execute(
                """
                SELECT scheduled_for_date, trigger FROM overview_refresh_jobs
                WHERE owner_user_id = ? ORDER BY scheduled_for_date
                """,
                ("owner",),
            )
        ]
    assert slots == [
        ("2026-07-10", "scheduled"),
        ("2026-07-11", "catchup"),
        ("2026-07-12", "catchup"),
        ("2026-07-13", "scheduled"),
    ]


def test_overview_planner_drains_missed_shanghai_days_in_order(
    state_root: Path, committed_v2_state: str
) -> None:
    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-catchup-planner",
        artifact_sha=committed_v2_state,
        active_user_ids=lambda: ("owner",),
    )
    try:
        first = planner.run_once(now=datetime(2026, 7, 10, 22, 5, tzinfo=UTC))
        recovered = planner.run_once(now=datetime(2026, 7, 12, 22, 5, tzinfo=UTC))
    finally:
        planner.stop(now=datetime(2026, 7, 12, 22, 6, tzinfo=UTC))

    assert len(first.scheduled_job_ids) == 1
    assert len(recovered.scheduled_job_ids) == 2
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        slots = [
            (str(row["scheduled_for_date"]), str(row["trigger"]))
            for row in conn.execute(
                """
                SELECT scheduled_for_date, trigger FROM overview_refresh_jobs
                WHERE owner_user_id = ? ORDER BY scheduled_for_date
                """,
                ("owner",),
            )
        ]
    assert slots == [
        ("2026-07-11", "scheduled"),
        ("2026-07-12", "catchup"),
        ("2026-07-13", "scheduled"),
    ]


def test_overview_keeps_per_card_and_whole_snapshot_last_success(
    state_root: Path, committed_v2_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(state_root, committed_v2_state)
    _seed_domain(state_root, "owner")
    _seed_literature(state_root, "owner")
    _seed_resource_detection(state_root, "owner")

    first_job = service.request_refresh("owner", now=_instant(1))
    assert (
        service.run_job(str(first_job["job_id"]), "overview-test", now=_instant(1)).outcome
        == "succeeded"
    )
    first_snapshot = service.latest("owner")
    assert first_snapshot is not None
    first_literature = _card(first_snapshot, "literature")

    monkeypatch.setattr(service, "_build_literature_card", _unavailable_literature)
    partial_job = service.request_refresh("owner", now=_instant(2))
    assert (
        service.run_job(str(partial_job["job_id"]), "overview-test", now=_instant(2)).outcome
        == "partial"
    )
    partial_snapshot = service.latest("owner")
    assert partial_snapshot is not None
    stale_literature = _card(partial_snapshot, "literature")
    assert stale_literature["source_status"] == "stale"
    assert stale_literature["data"] == first_literature["data"]

    monkeypatch.setattr(service, "_build_cards", _all_failed_cards)
    failed_job = service.request_refresh("owner", now=_instant(3))
    first_failure = service.run_job(str(failed_job["job_id"]), "overview-test", now=_instant(3))
    assert first_failure.outcome == "retry_wait"
    retained_snapshot = service.latest("owner")
    assert retained_snapshot == partial_snapshot
    waiting_job = service.get_job("owner", str(failed_job["job_id"]))
    assert waiting_job is not None
    assert waiting_job["status"] == "retry_wait"
    assert waiting_job["retry_count"] == 1
    assert isinstance(waiting_job["next_retry_at"], str)

    current = datetime.fromisoformat(str(waiting_job["next_retry_at"]))
    for expected_retry_count in (2, 3):
        retried = service.run_job(str(failed_job["job_id"]), "overview-test", now=current)
        assert retried.outcome == "retry_wait"
        waiting_job = service.get_job("owner", str(failed_job["job_id"]))
        assert waiting_job is not None
        assert waiting_job["status"] == "retry_wait"
        assert waiting_job["retry_count"] == expected_retry_count
        assert isinstance(waiting_job["next_retry_at"], str)
        current = datetime.fromisoformat(str(waiting_job["next_retry_at"]))

    terminal = service.run_job(str(failed_job["job_id"]), "overview-test", now=current)
    assert terminal.outcome == "failed"
    completed_job = service.get_job("owner", str(failed_job["job_id"]))
    assert completed_job is not None
    assert completed_job["status"] == "failed"
    assert completed_job["next_retry_at"] is None
    assert completed_job["retry_count"] == 4


def test_overview_partial_resource_card_preserves_complete_last_success(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    _seed_domain(state_root, "owner")
    _seed_literature(state_root, "owner")
    detection_path = _seed_resource_detection(state_root, "owner")

    first_job = service.request_refresh("owner", now=_instant(1))
    assert (
        service.run_job(str(first_job["job_id"]), "overview-test", now=_instant(1)).outcome
        == "succeeded"
    )
    first_snapshot = service.latest("owner")
    assert first_snapshot is not None
    first_resource = _card(first_snapshot, "resources")
    assert first_resource["source_status"] == "ok"

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        first_state = conn.execute(
            """
            SELECT last_success_data_json, last_success_cutoff_at
            FROM overview_refresh_card_states
            WHERE owner_user_id = ? AND card_id = 'resources'
            """,
            ("owner",),
        ).fetchone()
    assert first_state is not None

    detection_path.unlink()
    partial_job = service.request_refresh("owner", now=_instant(2))
    assert (
        service.run_job(str(partial_job["job_id"]), "overview-test", now=_instant(2)).outcome
        == "partial"
    )
    partial_snapshot = service.latest("owner")
    assert partial_snapshot is not None
    stale_resource = _card(partial_snapshot, "resources")
    assert stale_resource["source_status"] == "stale"
    assert stale_resource["data"] == first_resource["data"]
    assert stale_resource["data_cutoff_at"] == first_resource["data_cutoff_at"]

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        partial_state = conn.execute(
            """
            SELECT last_success_data_json, last_success_cutoff_at
            FROM overview_refresh_card_states
            WHERE owner_user_id = ? AND card_id = 'resources'
            """,
            ("owner",),
        ).fetchone()
    assert partial_state is not None
    assert partial_state["last_success_data_json"] == first_state["last_success_data_json"]
    assert partial_state["last_success_cutoff_at"] == first_state["last_success_cutoff_at"]


def test_overview_builder_does_not_call_external_or_action_services(
    state_root: Path, committed_v2_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(state_root, committed_v2_state)
    _seed_domain(state_root, "owner")
    _seed_literature(state_root, "owner")
    _seed_resource_detection(state_root, "owner")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("overview must not trigger external work")

    monkeypatch.setattr("ainrf.environments.probing.build_detection_snapshot", forbidden)
    monkeypatch.setattr("ainrf.literature.fetcher.fetch_for_subscription", forbidden)
    monkeypatch.setattr("ainrf.domain.tasks.TaskApplicationService.create_task", forbidden)

    job = service.request_refresh("owner", now=_instant(1))
    result = service.run_job(str(job["job_id"]), "overview-test", now=_instant(1))

    assert result.outcome == "succeeded"
    snapshot = service.latest("owner")
    assert snapshot is not None
    assert _card(snapshot, "domain")["data_cutoff_at"] == _instant(1).isoformat()
    assert _card(snapshot, "literature")["source_status"] == "ok"

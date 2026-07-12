"""Durable Today overview refresh-job tests."""

from __future__ import annotations

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
from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError

pytestmark = [pytest.mark.unit]


def _instant(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 12, hour, minute, tzinfo=UTC)


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


def test_overview_active_jobs_are_idempotent_and_user_scoped(state_root: Path) -> None:
    service = OverviewSnapshotService(state_root)

    first = service.request_refresh("owner", now=_instant(1))
    duplicate = service.request_refresh("owner", now=_instant(1, 1))
    other = service.request_refresh("other", now=_instant(1, 2))

    assert duplicate["job_id"] == first["job_id"]
    assert other["job_id"] != first["job_id"]
    assert service.get_job("other", str(first["job_id"])) is None


def test_overview_compatibility_refresh_uses_a_maintenance_participant(state_root: Path) -> None:
    service = OverviewSnapshotService(state_root)
    maintenance = DomainMaintenanceService(state_root)
    maintenance.enter(actor_id="test-operator", reason="verify overview writer drain")
    try:
        with pytest.raises(MaintenanceModeError):
            service.refresh("owner")
    finally:
        maintenance.exit(actor_id="test-operator")

    assert service.latest("owner") is None


def test_overview_job_schema_and_lease_recovery_are_durable(state_root: Path) -> None:
    service = OverviewSnapshotService(state_root)
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
    assert not service._fail_claim(first_claim, "stale worker", after_expiry)
    second_claim = service.claim_next_job(
        "second-worker", now=after_expiry, lease_seconds=5, job_id=str(job["job_id"])
    )
    assert second_claim is not None
    assert second_claim.lease_token != first_claim.lease_token
    assert not service.heartbeat_job(first_claim, now=after_expiry, lease_seconds=5)


def test_overview_planner_waits_for_shanghai_six_and_catches_up_after_restart(
    state_root: Path,
) -> None:
    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-test-planner",
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
    service = OverviewSnapshotService(state_root)
    assert service.get_job("alice", str(after_six.scheduled_job_ids[0])) is not None
    assert service.get_job("bob", str(after_six.scheduled_job_ids[1])) is not None


def test_overview_planner_drains_missed_shanghai_days_in_order(state_root: Path) -> None:
    planner = OverviewSnapshotPlanner(
        state_root,
        planner_id="overview-catchup-planner",
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
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OverviewSnapshotService(state_root)
    _seed_domain(state_root, "owner")
    _seed_literature(state_root, "owner")

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
    assert (
        service.run_job(str(failed_job["job_id"]), "overview-test", now=_instant(3)).outcome
        == "failed"
    )
    retained_snapshot = service.latest("owner")
    assert retained_snapshot == partial_snapshot
    completed_job = service.get_job("owner", str(failed_job["job_id"]))
    assert completed_job is not None
    assert completed_job["status"] == "failed"


def test_overview_builder_does_not_call_external_or_action_services(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OverviewSnapshotService(state_root)
    _seed_domain(state_root, "owner")
    _seed_literature(state_root, "owner")

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

"""Persistent domain writer participant and maintenance-preflight tests."""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from ainrf.db import connect
from ainrf.domain_control import CUTOVER_REQUIRED_PARTICIPANT_TYPES, DomainMaintenanceService

pytestmark = [pytest.mark.unit, pytest.mark.concurrent]


def _participant_service_in_maintenance(state_root: Path) -> DomainMaintenanceService:
    service = DomainMaintenanceService(state_root)
    service.register_participant("api-1", "api", process_id=101)
    service.enter(actor_id="operator-1", reason="cutover")
    service.drain_participant("api-1")
    return service


def _drain_required_cutover_participants(service: DomainMaintenanceService) -> None:
    existing_types = {participant.participant_type for participant in service.participants()}
    for participant_type in CUTOVER_REQUIRED_PARTICIPANT_TYPES:
        if participant_type not in existing_types:
            service.register_participant(f"required:{participant_type}", participant_type)
        matching = [
            participant.participant_id
            for participant in service.participants()
            if participant.participant_type == participant_type and participant.status != "stopped"
        ]
        assert matching
        for participant_id in matching:
            service.drain_participant(participant_id)


def _insert_active_attempt_and_claimed_launch(state_root: Path) -> tuple[str, str]:
    """Seed only the durable facts preflight must inspect, without an engine."""
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    task_id = "task-preflight"
    attempt_id = "attempt-preflight"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, user_skills, user_mcp_servers, status, title, prompt,
                created_at, updated_at, latest_output_seq, owner_user_id
            ) VALUES (?, 'project-1', 'workspace-1', 'environment-1', 'general',
                'claude_code', '[]', '[]', 'running', 'Preflight task', 'test',
                '2026-07-12T00:00:00+00:00', '2026-07-12T00:00:00+00:00', 0, 'user-1')
            """,
            (task_id,),
        )
        conn.execute(
            """
            INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id, created_at
            ) VALUES (?, ?, 1, 'initial', 'running', NULL, '2026-07-12T00:00:00+00:00')
            """,
            (attempt_id, task_id),
        )
        conn.execute(
            """
            INSERT INTO task_dispatch_outbox (
                dispatch_id, task_id, attempt_id, status, created_at
            ) VALUES ('dispatch-preflight', ?, ?, 'claimed', '2026-07-12T00:00:00+00:00')
            """,
            (task_id, attempt_id),
        )
        conn.commit()
    return task_id, attempt_id


def test_participant_registration_heartbeat_and_lifecycle_are_persistent(
    state_root: Path,
) -> None:
    first = DomainMaintenanceService(state_root)
    registered = first.register_participant(
        "dispatcher-1",
        "task_dispatcher",
        process_id=4242,
        details={"queue": "domain"},
    )

    assert registered.participant_id == "dispatcher-1"
    assert registered.participant_type == "task_dispatcher"
    assert registered.process_id == 4242
    assert registered.observed_epoch == 0
    assert registered.status == "active"
    assert registered.in_flight_mutations == 0
    assert registered.unflushed_output_count == 0

    heartbeat = first.heartbeat_participant(
        "dispatcher-1",
        in_flight_mutations=3,
        unflushed_output_count=2,
    )
    assert heartbeat.in_flight_mutations == 3
    assert heartbeat.unflushed_output_count == 2

    second = DomainMaintenanceService(state_root)
    persisted = second.participants()
    assert len(persisted) == 1
    assert persisted[0].participant_id == "dispatcher-1"
    assert persisted[0].in_flight_mutations == 3
    assert persisted[0].unflushed_output_count == 2

    entered = second.enter(actor_id="operator-1", reason="cutover")
    second.heartbeat_participant(
        "dispatcher-1",
        in_flight_mutations=0,
        unflushed_output_count=0,
    )
    second.drain_participant("dispatcher-1")

    third = DomainMaintenanceService(state_root)
    drained = third.participants()[0]
    assert drained.status == "drained"
    assert drained.observed_epoch == entered.maintenance_epoch
    assert drained.drained_at is not None

    third.stop_participant("dispatcher-1")
    stopped = DomainMaintenanceService(state_root).participants()[0]
    assert stopped.status == "stopped"
    assert stopped.stopped_at is not None


def test_preflight_requires_every_required_participant_to_drain_and_remain_fresh(
    state_root: Path,
) -> None:
    service = _participant_service_in_maintenance(state_root)

    missing = service.preflight(
        required_participant_types=("api", "task_dispatcher"),
        stability_window_seconds=0.0,
    )
    assert not missing.ready
    assert not missing.participants_drained
    assert missing.missing_participant_types == ("task_dispatcher",)

    service.register_participant("dispatcher-1", "task_dispatcher")
    service.drain_participant("dispatcher-1")
    ready = service.preflight(
        required_participant_types=("api", "task_dispatcher"),
        stability_window_seconds=0.0,
    )
    assert ready.ready
    assert ready.participants_drained
    assert ready.missing_participant_types == ()
    assert ready.stale_participant_ids == ()

    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            "UPDATE domain_write_participants SET heartbeat_at = ? WHERE participant_id = ?",
            ("2000-01-01T00:00:00+00:00", "dispatcher-1"),
        )
        conn.commit()

    stale = service.preflight(
        required_participant_types=("api", "task_dispatcher"),
        stability_window_seconds=0.0,
        stale_after_seconds=1.0,
    )
    assert not stale.ready
    assert set(stale.stale_participant_ids) == {"dispatcher-1"}


def test_default_cutover_preflight_fails_closed_when_writer_types_are_missing(
    state_root: Path,
) -> None:
    service = _participant_service_in_maintenance(state_root)

    missing = service.preflight(stability_window_seconds=0.0)

    assert not missing.ready
    assert missing.missing_participant_types == tuple(
        participant_type
        for participant_type in CUTOVER_REQUIRED_PARTICIPANT_TYPES
        if participant_type != "api"
    )

    _drain_required_cutover_participants(service)
    ready = service.preflight(stability_window_seconds=0.0)
    assert ready.ready
    assert ready.missing_participant_types == ()


def test_preflight_blocks_active_attempts_pending_launches_and_unflushed_output(
    state_root: Path,
) -> None:
    service = _participant_service_in_maintenance(state_root)
    task_id, attempt_id = _insert_active_attempt_and_claimed_launch(state_root)
    service.heartbeat_participant("api-1", unflushed_output_count=4)

    blocked = service.preflight(stability_window_seconds=0.0)
    assert not blocked.ready
    assert blocked.maintenance_active
    assert not blocked.participants_drained
    assert blocked.active_attempt_count == 1
    assert blocked.pending_runtime_launch_count == 1
    assert blocked.unflushed_output_count == 4

    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            "UPDATE agent_task_attempts SET status = 'succeeded' WHERE attempt_id = ?",
            (attempt_id,),
        )
        conn.execute(
            "UPDATE task_dispatch_outbox SET status = 'cancelled' WHERE task_id = ?",
            (task_id,),
        )
        conn.commit()
    service.heartbeat_participant("api-1", unflushed_output_count=0)
    _drain_required_cutover_participants(service)

    ready = service.preflight(stability_window_seconds=0.0)
    assert ready.ready
    assert ready.active_attempt_count == 0
    assert ready.pending_runtime_launch_count == 0
    assert ready.unflushed_output_count == 0


def test_preflight_rejects_a_source_that_changes_during_its_stability_window(
    state_root: Path,
) -> None:
    service = _participant_service_in_maintenance(state_root)
    source = state_root / "runtime" / "projects.json"
    source.write_text('{"revision": 1}\n', encoding="utf-8")

    def mutate_source() -> None:
        time.sleep(0.04)
        source.write_text('{"revision": 2}\n', encoding="utf-8")

    with ThreadPoolExecutor(max_workers=1) as pool:
        mutation = pool.submit(mutate_source)
        preflight = service.preflight(stability_window_seconds=0.15)
        mutation.result()

    assert not preflight.ready
    assert not preflight.source_stable


def test_preflight_ignores_v2_participant_heartbeats_but_keeps_legacy_stability(
    state_root: Path,
) -> None:
    service = _participant_service_in_maintenance(state_root)
    _drain_required_cutover_participants(service)
    before = service._source_fingerprints()

    def heartbeat_v2_control_plane() -> None:
        time.sleep(0.04)
        service.heartbeat_participant("api-1")

    with ThreadPoolExecutor(max_workers=1) as pool:
        heartbeat = pool.submit(heartbeat_v2_control_plane)
        preflight = service.preflight(stability_window_seconds=0.15)
        heartbeat.result()

    assert preflight.ready
    assert preflight.source_stable
    assert service._source_fingerprints() == before


def test_concurrent_heartbeats_cannot_revive_a_drained_participant(state_root: Path) -> None:
    service = DomainMaintenanceService(state_root)
    service.register_participant("worker-1", "literature_worker")
    entered = service.enter(actor_id="operator-1", reason="cutover")
    barrier = Barrier(9)

    def heartbeat(worker_id: int) -> None:
        barrier.wait(timeout=1.0)
        service.heartbeat_participant(
            "worker-1",
            in_flight_mutations=0,
            unflushed_output_count=0,
        )

    def drain() -> None:
        barrier.wait(timeout=1.0)
        service.drain_participant("worker-1")

    with ThreadPoolExecutor(max_workers=9) as pool:
        heartbeat_futures: list[Future[None]] = [
            pool.submit(heartbeat, worker_id) for worker_id in range(8)
        ]
        drain_future: Future[None] = pool.submit(drain)
        for future in (*heartbeat_futures, drain_future):
            future.result()

    participant = DomainMaintenanceService(state_root).participants()[0]
    assert participant.status == "drained"
    assert participant.observed_epoch == entered.maintenance_epoch

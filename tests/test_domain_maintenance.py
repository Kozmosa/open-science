"""Persistent domain-maintenance barrier tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.middleware.domain_maintenance import build_domain_maintenance_middleware
from ainrf.db import connect
from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceLease,
    MaintenanceModeError,
)

pytestmark = [pytest.mark.unit, pytest.mark.concurrent]


def test_maintenance_epoch_persists_across_service_instances(state_root: Path) -> None:
    first = DomainMaintenanceService(state_root)
    entered = first.enter(actor_id="operator-1", reason="migration")

    second = DomainMaintenanceService(state_root)
    assert second.status().is_active
    assert second.status().maintenance_epoch == entered.maintenance_epoch
    with pytest.raises(MaintenanceModeError):
        second.begin_mutation(source="test")

    exited = second.exit(actor_id="operator-1")
    assert not exited.is_active
    assert exited.maintenance_epoch == entered.maintenance_epoch


def test_enter_waits_for_existing_mutation_to_drain(state_root: Path) -> None:
    service = DomainMaintenanceService(state_root)
    lease = service.begin_mutation(source="test")
    service.enter(actor_id="operator-1", reason="migration")

    assert not service.wait_for_drain(timeout_seconds=0.01, poll_seconds=0.001)
    service.finish_mutation(lease)
    assert service.wait_for_drain(timeout_seconds=0.1, poll_seconds=0.001)
    service.exit(actor_id="operator-1")


def test_maintenance_control_operation_blocks_exit_and_exposes_admin_in_flight(
    state_root: Path,
) -> None:
    service = DomainMaintenanceService(state_root)
    participant = DomainWriteParticipant(
        service,
        "admin-cli",
        participant_id="admin-control-operation",
    )
    participant.start()
    entered = service.enter(actor_id="operator-1", reason="cutover")
    participant.drain()

    lease = participant.begin_maintenance_operation(
        source="domain-cutover.prepare",
        expected_epoch=entered.maintenance_epoch,
    )
    status = service.status()
    matching = next(
        item for item in service.participants() if item.participant_id == participant.participant_id
    )
    assert status.in_flight_mutations == 1
    assert matching.status == "draining"
    assert matching.in_flight_mutations == 1
    with pytest.raises(MaintenanceModeError, match="in flight"):
        service.exit(actor_id="operator-1")

    participant.check_maintenance_operation(lease)
    participant.finish_mutation(lease)
    assert service.status().in_flight_mutations == 0
    assert (
        next(
            item
            for item in service.participants()
            if item.participant_id == participant.participant_id
        ).status
        == "drained"
    )
    service.exit(actor_id="operator-1")


@pytest.mark.anyio
async def test_http_domain_mutations_are_rejected_during_maintenance(state_root: Path) -> None:
    service = DomainMaintenanceService(state_root)
    app = FastAPI()
    app.middleware("http")(build_domain_maintenance_middleware(service))

    @app.post("/tasks")
    async def create_task() -> dict[str, bool]:
        await asyncio.sleep(0)
        return {"created": True}

    service.enter(actor_id="operator-1", reason="migration")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/tasks")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"


@pytest.mark.anyio
async def test_http_terminal_mutations_are_rejected_during_maintenance(state_root: Path) -> None:
    service = DomainMaintenanceService(state_root)
    app = FastAPI()
    app.middleware("http")(build_domain_maintenance_middleware(service))

    @app.post("/terminal/session")
    async def create_terminal_session() -> dict[str, bool]:
        return {"created": True}

    service.enter(actor_id="operator-1", reason="migration")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/terminal/session")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"


@pytest.mark.anyio
async def test_http_mutation_reports_maintenance_when_its_epoch_changes_mid_handler(
    state_root: Path,
) -> None:
    service = DomainMaintenanceService(state_root)
    app = FastAPI()
    app.middleware("http")(build_domain_maintenance_middleware(service))

    @app.post("/tasks")
    async def create_task() -> dict[str, bool]:
        service.enter(actor_id="operator-1", reason="cutover")
        return {"created": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/tasks")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"


@pytest.mark.anyio
async def test_http_mutation_releases_lease_when_maintenance_starts_before_handler(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The begin-to-check epoch race must not strand a durable mutation row."""

    service = DomainMaintenanceService(state_root)
    app = FastAPI()
    app.middleware("http")(build_domain_maintenance_middleware(service))
    handler_calls: list[bool] = []

    @app.post("/tasks")
    async def create_task() -> dict[str, bool]:
        handler_calls.append(True)
        return {"created": True}

    original_begin_mutation = service.begin_mutation

    def begin_then_enter_maintenance(
        *, source: str, participant_id: str | None = None
    ) -> MaintenanceLease:
        lease = original_begin_mutation(source=source, participant_id=participant_id)
        service.enter(actor_id="operator-1", reason="cutover")
        return lease

    monkeypatch.setattr(service, "begin_mutation", begin_then_enter_maintenance)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/tasks")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"
    assert handler_calls == []
    assert service.status().in_flight_mutations == 0
    service.exit(actor_id="operator-1")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/admin/environments/environment-1/access"),
        ("DELETE", "/admin/environments/environment-1/access/user-1"),
        ("PATCH", "/admin/users/user-1"),
        ("PUT", "/admin/users/user-1/password"),
        ("POST", "/files/upload"),
        ("POST", "/auth/register"),
        ("POST", "/auth/change-password"),
        ("PATCH", "/settings/search"),
        ("POST", "/skill-registries"),
        ("GET", "/terminal/session"),
        ("GET", "/terminal/session-pairs"),
    ],
)
async def test_http_authorization_and_workspace_writes_are_rejected_during_maintenance(
    state_root: Path,
    method: str,
    path: str,
) -> None:
    """No auth-grant or tenant-file handler may bypass the durable lease."""

    service = DomainMaintenanceService(state_root)
    app = FastAPI()
    app.middleware("http")(build_domain_maintenance_middleware(service))
    handler_calls: list[str] = []

    @app.api_route("/{target_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def mutate(target_path: str) -> dict[str, bool]:
        handler_calls.append(target_path)
        return {"mutated": True}

    service.enter(actor_id="operator-1", reason="migration")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.request(method, path)

    assert response.status_code == 503
    assert response.json()["error_code"] == "DOMAIN_MAINTENANCE_ACTIVE"
    assert handler_calls == []


def test_preflight_treats_unknown_or_dispatched_runtime_work_as_a_cutover_blocker(
    state_root: Path,
) -> None:
    service = DomainMaintenanceService(state_root)
    service.initialize()
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        conn.execute(
            """INSERT INTO tasks (
                   task_id, project_id, workspace_id, environment_id, researcher_type,
                   harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "task-unknown",
                "legacy-project",
                "legacy-workspace",
                "legacy-environment",
                "vanilla",
                "claude-code",
                "launch_unknown",
                "Unknown",
                "prompt",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "owner",
            ),
        )
        conn.execute(
            """INSERT INTO agent_task_attempts (
                   attempt_id, task_id, attempt_seq, trigger, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "attempt-unknown",
                "task-unknown",
                1,
                "initial",
                "launch_unknown",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """INSERT INTO task_dispatch_outbox (
                   dispatch_id, task_id, attempt_id, status, launch_state, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "dispatch-unknown",
                "task-unknown",
                "attempt-unknown",
                "launch_unknown",
                "unknown",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    service.enter(actor_id="operator", reason="cutover")

    preflight = service.preflight(stability_window_seconds=0)

    assert not preflight.ready
    assert preflight.active_attempt_count == 1
    assert preflight.pending_runtime_launch_count == 1


def test_preflight_counts_legacy_task_runner_work_without_an_attempt(state_root: Path) -> None:
    service = DomainMaintenanceService(state_root)
    service.initialize()
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        conn.execute(
            """INSERT INTO tasks (
                   task_id, project_id, workspace_id, environment_id, researcher_type,
                   harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "legacy-running-task",
                "legacy-project",
                "legacy-workspace",
                "legacy-environment",
                "vanilla",
                "claude-code",
                "running",
                "Legacy runner",
                "prompt",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "owner",
            ),
        )
        conn.execute(
            """INSERT INTO tasks (
                   task_id, project_id, workspace_id, environment_id, researcher_type,
                   harness_engine, status, title, prompt, created_at, updated_at, owner_user_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "legacy-queued-task",
                "legacy-project",
                "legacy-workspace",
                "legacy-environment",
                "vanilla",
                "claude-code",
                "queued",
                "Legacy queued",
                "prompt",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "owner",
            ),
        )
        conn.commit()
    service.enter(actor_id="operator", reason="cutover")

    preflight = service.preflight(required_participant_types=(), stability_window_seconds=0)

    assert not preflight.ready
    assert preflight.active_attempt_count == 1
    assert preflight.pending_runtime_launch_count == 1

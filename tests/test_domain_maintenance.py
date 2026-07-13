"""Persistent domain-maintenance barrier tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.middleware.domain_maintenance import build_domain_maintenance_middleware
from ainrf.db import connect
from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError

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

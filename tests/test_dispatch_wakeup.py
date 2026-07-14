"""Post-commit Task dispatch wakeup tests."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect
from ainrf.domain.dispatch_wakeup import DispatchWakeup
from ainrf.domain.tasks import TaskApplicationService
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA
from tests.test_task_lifecycle_closure import _create_task, _task_scope

pytestmark = [pytest.mark.unit]


@pytest.mark.anyio
async def test_file_wakeup_notifies_a_no_port_worker_waiter(tmp_path: Path) -> None:
    wakeup = DispatchWakeup(tmp_path)
    observed = wakeup.generation()
    waiter = asyncio.create_task(wakeup.wait_for_change(observed, timeout_seconds=1.0))
    await asyncio.sleep(0)
    wakeup.notify("dispatch-wakeup-test")

    assert await waiter != observed


def test_failed_post_commit_wakeup_keeps_durable_task_attempt_and_outbox(
    state_root: Path, tmp_path: Path
) -> None:
    scope = _task_scope(state_root, tmp_path, label="wakeup-failure")
    attempts: list[str] = []

    def fail_notify(dispatch_id: str) -> None:
        attempts.append(dispatch_id)
        raise OSError("fixture wakeup transport is unavailable")

    service = TaskApplicationService(
        state_root,
        artifact_sha=V2_ARTIFACT_SHA,
        dispatch_notifier=fail_notify,
    )
    created = _create_task(service, scope, idempotency_key="wakeup-failure-create")

    assert attempts == [created["dispatch_id"]]
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task = conn.execute(
            "SELECT task_id FROM tasks WHERE task_id = ?", (created["task_id"],)
        ).fetchone()
        attempt = conn.execute(
            "SELECT attempt_id FROM agent_task_attempts WHERE attempt_id = ?",
            (created["attempt_id"],),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT status FROM task_dispatch_outbox WHERE dispatch_id = ?",
            (created["dispatch_id"],),
        ).fetchone()
    assert task is not None
    assert attempt is not None
    assert dispatch is not None and dispatch["status"] == "pending"

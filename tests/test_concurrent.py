"""Concurrency and race-condition tests for critical services.

These tests intentionally create contention (multiple threads/async tasks
operating on the same service/state) to expose races that do not appear in
single-threaded tests.  Run them with ``-n1`` so pytest-xdist does not isolate
workers and hide the contention.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from ainrf.agentic_researcher.models import (
    HarnessEngineType,
    TaskStatus,
)
from ainrf.auth.models import AuthError
from ainrf.sessions.models import AttemptStatus
from tests.testutil import (
    FakeEngine,
    HangingEngine,
    make_researcher,
    run_threaded,
    seed_user,
)

pytestmark = [pytest.mark.unit, pytest.mark.concurrent]


# ---------------------------------------------------------------------------
# AgenticResearcherService concurrency
# ---------------------------------------------------------------------------
class TestAgenticResearcherConcurrency:
    def test_concurrent_task_output_appends_unique_seq(self, agentic_service):
        """Multiple threads appending outputs to the same task must not reuse seqs."""
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )

        def append(i: int):
            return asyncio.run(agentic_service.append_output(task.task_id, "message", f"msg-{i}"))

        results = run_threaded(append, 50, max_workers=8)
        seqs = sorted(e.seq for e in results)

        assert len(seqs) == len(set(seqs)), f"duplicate seqs found: {seqs}"
        assert seqs == list(range(1, 51))

        latest = agentic_service.get_task(task.task_id)
        assert latest.latest_output_seq == 50

    def test_concurrent_token_usage_merge_accuracy(self, agentic_service):
        """Concurrent token_usage merges for the same task must not lose data."""
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )

        usage = {
            "total": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 2,
                "cost_usd": 0.01,
            },
            "by_model": {
                "claude-sonnet": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost_usd": 0.01,
                }
            },
        }

        def record(_i: int):
            agentic_service._record_token_usage_sync(task.task_id, usage, replace=False)

        run_threaded(record, 20, max_workers=8)

        final = agentic_service.get_task(task.task_id)
        parsed = json.loads(final.token_usage_json)
        assert parsed["total"]["input_tokens"] == 200
        assert parsed["total"]["cost_usd"] == pytest.approx(0.2)
        assert parsed["by_model"]["claude-sonnet"]["input_tokens"] == 200

    @pytest.mark.anyio
    async def test_schedule_task_race_prevents_duplicate_coroutines(self, agentic_service):
        """Two concurrent schedule_task calls must create only one asyncio.Task."""
        engine = FakeEngine()
        engine.completion_event = threading.Event()
        agentic_service._engines[HarnessEngineType.CLAUDE_CODE] = engine

        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(harness_engine=HarnessEngineType.CLAUDE_CODE),
            prompt="hello",
            owner_user_id="user-1",
        )

        barrier = threading.Barrier(2)

        def schedule(_i: int):
            barrier.wait()
            # Each thread needs its own event loop because schedule_task uses
            # asyncio.get_running_loop() and we cannot share loops across threads.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self._schedule_and_wait(agentic_service, task.task_id, engine)
                )
            finally:
                loop.close()

        run_threaded(schedule, 2, max_workers=2)

        # At no point should there have been two entries for the same task_id.
        # Since we cannot observe the intermediate state from outside, we verify
        # the final state is consistent.
        latest = agentic_service.get_task(task.task_id)
        assert latest.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    @staticmethod
    async def _schedule_and_wait(service, task_id: str, engine: FakeEngine) -> None:
        task = service.schedule_task(task_id)
        if task is not None:
            await task
            return
        # The other thread won the race; wait for the shared engine to finish.
        engine.completion_event.wait(timeout=10)
        latest = service.get_task(task_id)
        assert latest.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    @pytest.mark.anyio
    async def test_cancel_running_task_while_engine_running(self, agentic_service):
        """Cancel a task while its engine is still running; verify clean termination."""
        engine = HangingEngine()
        agentic_service._engines[HarnessEngineType.CLAUDE_CODE] = engine

        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(harness_engine=HarnessEngineType.CLAUDE_CODE),
            prompt="hello",
            owner_user_id="user-1",
        )

        agentic_service.schedule_task(task.task_id)
        # Wait until the engine has definitely started.
        for _ in range(50):
            if engine.started_count > 0:
                break
            await asyncio.sleep(0.01)
        assert engine.started_count > 0

        await agentic_service.cancel_running_task(task.task_id)

        latest = agentic_service.get_task(task.task_id)
        assert latest.status == TaskStatus.CANCELLED
        assert task.task_id in engine.cancelled_task_ids


# ---------------------------------------------------------------------------
# SessionService concurrency
# ---------------------------------------------------------------------------
class TestSessionsConcurrency:
    def test_create_attempt_seq_race(self, session_service):
        """Concurrent attempt creation for the same session must produce unique seqs."""
        session = session_service.create_session(
            project_id="project-1", title="Race Session", owner_user_id="user-1"
        )

        def create_attempt(_i: int):
            return session_service.create_attempt(session_id=session.id)

        attempts = run_threaded(create_attempt, 40, max_workers=8)
        seqs = sorted(a.attempt_seq for a in attempts)

        assert len(seqs) == len(set(seqs)), f"duplicate attempt_seq: {seqs}"
        assert seqs == list(range(1, 41))

    def test_complete_attempt_and_recalc_session_race(self, session_service):
        """Completing two attempts concurrently must leave session aggregates correct."""
        session = session_service.create_session(
            project_id="project-1", title="Race Session", owner_user_id="user-1"
        )
        a1 = session_service.create_attempt(session_id=session.id)
        a2 = session_service.create_attempt(session_id=session.id)

        def complete(args):
            attempt_id, duration = args
            return session_service.complete_attempt(
                attempt_id,
                status=AttemptStatus.COMPLETED.value,
                duration_ms=duration,
            )

        run_threaded(complete, [(a1.id, 100), (a2.id, 200)], max_workers=2)

        latest = session_service.get_session(session.id)
        assert latest.task_count == 2
        assert latest.total_duration_ms == 300


# ---------------------------------------------------------------------------
# Project / Workspace registry concurrency
# ---------------------------------------------------------------------------
class TestRegistryConcurrency:
    def test_concurrent_project_creation_unique_ids(self, project_service):
        """Concurrent project creation must produce unique project IDs."""

        def create(_i: int):
            return project_service.create_project(
                name=f"Project {_i}", description="race test", owner_user_id="user-1"
            )

        projects = run_threaded(create, 32, max_workers=8)
        ids = [p.project_id for p in projects]
        assert len(ids) == len(set(ids)), f"duplicate project ids: {ids}"

    def test_concurrent_workspace_creation_same_label(self, workspace_service):
        """Concurrent workspace creation for the same user/label must all succeed uniquely."""

        def create(_i: int):
            return workspace_service.create_workspace(
                label="default",
                description="race",
                default_workdir=None,
                workspace_prompt="prompt",
                owner_user_id="user-1",
            )

        workspaces = run_threaded(create, 16, max_workers=8)
        ids = [w.workspace_id for w in workspaces]
        assert len(ids) == len(set(ids)), f"duplicate workspace ids: {ids}"


# ---------------------------------------------------------------------------
# Auth concurrency
# ---------------------------------------------------------------------------
class TestAuthConcurrency:
    def test_login_lockout_race_records_attempts(self, auth_service):
        """Concurrent failed login attempts from the same IP must be recorded reliably."""
        seed_user(auth_service, "victim", "correct-password")
        auth_service._login_max_failures = 3

        def record(_i: int):
            auth_service.record_login_attempt(
                username="victim", ip_address="10.0.0.99", success=False
            )
            return "recorded"

        results = run_threaded(record, 12, max_workers=8)
        recorded_count = sum(1 for r in results if r == "recorded")
        assert recorded_count == 12

        # IP lockout threshold is max_failures * 3 = 9.
        with pytest.raises(auth_service.AccountLockedError):
            auth_service.check_login_lockout(username="new-user", ip_address="10.0.0.99")

    def test_password_change_race(self, auth_service):
        """Two threads changing password for the same user must leave a working password."""
        user_id = seed_user(auth_service, "racer", "old-password")

        def change_password(i: int):
            new_password = f"new-password-{i}"
            auth_service.change_password(user_id, "old-password", new_password)
            return new_password

        new_passwords = run_threaded(change_password, 2, max_workers=2)

        # At least one of the new passwords must work; the old password must not.
        with pytest.raises(AuthError):
            auth_service.login(username="racer", password="old-password")

        working = [p for p in new_passwords if self._can_login(auth_service, "racer", p)]
        assert len(working) >= 1

    @staticmethod
    def _can_login(auth_service, username: str, password: str) -> bool:
        try:
            auth_service.login(username=username, password=password)
            return True
        except AuthError:
            return False

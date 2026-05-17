# tests/test_sessions.py
"""Tests for session service and API routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestSessionService:
    @pytest.fixture
    def service(self):
        from ainrf.sessions import SessionService

        with tempfile.TemporaryDirectory() as td:
            svc = SessionService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_create_and_get_session(self, service):
        s = service.create_session(project_id="proj_1", title="Test Session")
        assert s.title == "Test Session"
        assert s.project_id == "proj_1"
        assert s.status.value == "active"

        got = service.get_session(s.id)
        assert got.id == s.id

    def test_list_sessions_filter(self, service):
        service.create_session(project_id="p1", title="A")
        service.create_session(project_id="p2", title="B")

        all_s = service.list_sessions()
        assert len(all_s) == 2

        p1 = service.list_sessions(project_id="p1")
        assert len(p1) == 1
        assert p1[0].project_id == "p1"

    def test_list_sessions_status_filter(self, service):
        service.create_session(project_id="p1", title="Active")
        s2 = service.create_session(project_id="p1", title="Archived")
        service.update_session(s2.id, status="archived")

        active = service.list_sessions(status="active")
        assert len(active) == 1

    def test_update_session(self, service):
        s = service.create_session(project_id="p1", title="Old")
        updated = service.update_session(s.id, title="New")
        assert updated.title == "New"

    def test_delete_session_archives(self, service):
        s = service.create_session(project_id="p1", title="X")
        service.delete_session(s.id)
        got = service.get_session(s.id)
        assert got.status.value == "archived"

    def test_session_not_found(self, service):
        from ainrf.sessions import SessionNotFoundError

        with pytest.raises(SessionNotFoundError):
            service.get_session("nonexistent")

    def test_create_attempt(self, service):
        s = service.create_session(project_id="p1", title="S")
        a = service.create_attempt(session_id=s.id, task_id="task_1")
        assert a.session_id == s.id
        assert a.attempt_seq == 1
        assert a.task_id == "task_1"
        assert a.status.value == "running"

    def test_attempt_chain(self, service):
        s = service.create_session(project_id="p1", title="S")
        a1 = service.create_attempt(session_id=s.id)
        a2 = service.create_attempt(
            session_id=s.id, parent_attempt_id=a1.id,
            intervention_reason="fix bugs"
        )
        assert a2.attempt_seq == 2
        assert a2.parent_attempt_id == a1.id
        assert a2.intervention_reason == "fix bugs"

    def test_complete_attempt(self, service):
        s = service.create_session(project_id="p1", title="S")
        a = service.create_attempt(session_id=s.id)
        done = service.complete_attempt(
            a.id, status="completed", duration_ms=5000,
            token_usage_json='{"input": 1000, "output": 200}',
        )
        assert done.status.value == "completed"
        assert done.duration_ms == 5000

    def test_complete_attempt_recalcs_session(self, service):
        s = service.create_session(project_id="p1", title="S")
        a1 = service.create_attempt(session_id=s.id)
        service.complete_attempt(a1.id, status="completed", duration_ms=3000)
        a2 = service.create_attempt(session_id=s.id)
        service.complete_attempt(a2.id, status="completed", duration_ms=7000)

        s2 = service.get_session(s.id)
        assert s2.task_count == 2
        assert s2.total_duration_ms == 10000

    def test_list_attempts_sorted(self, service):
        s = service.create_session(project_id="p1", title="S")
        service.create_attempt(session_id=s.id)
        service.create_attempt(session_id=s.id)
        attempts = service.list_attempts(s.id)
        assert len(attempts) == 2
        assert attempts[0].attempt_seq < attempts[1].attempt_seq

    def test_delete_session_preserves_data(self, service):
        s = service.create_session(project_id="p1", title="S")
        service.create_attempt(session_id=s.id)
        service.delete_session(s.id)
        # attempts still queryable
        attempts = service.list_attempts(s.id)
        assert len(attempts) == 1

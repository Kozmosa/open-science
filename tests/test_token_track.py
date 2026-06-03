"""Tests for token track functionality: engine extraction, session-meta polling, cost aggregation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestBuildTokenUsage:
    """Tests for _build_token_usage in agent_sdk.py."""

    def test_full_result_message(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeResultMsg:
            usage = {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 100,
            }
            total_cost_usd = 1.50
            model_usage = {
                "claude-opus-4-7": {"input_tokens": 800, "output_tokens": 400, "cost_usd": 1.20},
                "claude-sonnet-4-6": {"input_tokens": 200, "output_tokens": 100, "cost_usd": 0.30},
            }

        result = _build_token_usage(FakeResultMsg())
        assert result is not None
        assert result["source"] == "agent-sdk"
        assert result["total"]["input_tokens"] == 1000
        assert result["total"]["output_tokens"] == 500
        assert result["total"]["cache_creation_input_tokens"] == 200
        assert result["total"]["cache_read_input_tokens"] == 100
        assert result["total"]["cost_usd"] == 1.50
        assert len(result["by_model"]) == 2
        assert result["by_model"]["claude-opus-4-7"]["cost_usd"] == 1.20

    def test_no_usage_returns_none(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeMsg:
            pass

        result = _build_token_usage(FakeMsg())
        assert result is None

    def test_empty_usage_returns_none(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeMsg:
            usage = None

        result = _build_token_usage(FakeMsg())
        assert result is None

    def test_no_model_usage(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeMsg:
            usage = {"input_tokens": 100, "output_tokens": 50}
            total_cost_usd = 0.15

        result = _build_token_usage(FakeMsg())
        assert result is not None
        assert "by_model" not in result
        assert result["total"]["cost_usd"] == 0.15

    def test_cost_usd_zero(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeMsg:
            usage = {"input_tokens": 100}
            total_cost_usd = 0.0

        result = _build_token_usage(FakeMsg())
        assert result is not None
        assert result["total"]["cost_usd"] == 0.0

    def test_cost_usd_none_defaults_to_zero(self):
        from ainrf.harness_engine.engines.agent_sdk import _build_token_usage

        class FakeMsg:
            usage = {"input_tokens": 100}

        result = _build_token_usage(FakeMsg())
        assert result is not None
        assert result["total"]["cost_usd"] == 0.0


class TestFindSessionMeta:
    """Tests for _find_session_meta in claude_code.py."""

    def test_finds_matching_file_within_window(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        with tempfile.TemporaryDirectory() as td:
            import ainrf.harness_engine.engines.claude_code as cc

            original_dir = cc._SESSION_META_DIR
            cc._SESSION_META_DIR = Path(td)

            try:
                # Create a session-meta file
                meta = {"start_time": 100.0, "input_tokens": 500, "output_tokens": 200}
                f = Path(td) / "test-uuid.json"
                f.write_text(json.dumps(meta))

                result = _find_session_meta(102.0)  # within 10s window
                assert result is not None
                assert result["input_tokens"] == 500
                assert result["output_tokens"] == 200
            finally:
                cc._SESSION_META_DIR = original_dir

    def test_no_match_outside_window(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        with tempfile.TemporaryDirectory() as td:
            import ainrf.harness_engine.engines.claude_code as cc

            original_dir = cc._SESSION_META_DIR
            cc._SESSION_META_DIR = Path(td)

            try:
                meta = {"start_time": 100.0, "input_tokens": 500, "output_tokens": 200}
                f = Path(td) / "test-uuid.json"
                f.write_text(json.dumps(meta))

                result = _find_session_meta(200.0)  # 100s away, outside 10s window
                assert result is None
            finally:
                cc._SESSION_META_DIR = original_dir

    def test_returns_none_for_empty_directory(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        with tempfile.TemporaryDirectory() as td:
            import ainrf.harness_engine.engines.claude_code as cc

            original_dir = cc._SESSION_META_DIR
            cc._SESSION_META_DIR = Path(td)

            try:
                result = _find_session_meta(100.0)
                assert result is None
            finally:
                cc._SESSION_META_DIR = original_dir

    def test_returns_none_when_dir_missing(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        import ainrf.harness_engine.engines.claude_code as cc

        original_dir = cc._SESSION_META_DIR
        cc._SESSION_META_DIR = Path("/nonexistent/path/xyz")

        try:
            result = _find_session_meta(100.0)
            assert result is None
        finally:
            cc._SESSION_META_DIR = original_dir

    def test_ignores_non_json_files(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        with tempfile.TemporaryDirectory() as td:
            import ainrf.harness_engine.engines.claude_code as cc

            original_dir = cc._SESSION_META_DIR
            cc._SESSION_META_DIR = Path(td)

            try:
                # Create a non-json file
                (Path(td) / "readme.txt").write_text("hello")
                result = _find_session_meta(100.0)
                assert result is None
            finally:
                cc._SESSION_META_DIR = original_dir

    def test_handles_malformed_json(self):
        from ainrf.harness_engine.engines.claude_code import _find_session_meta

        with tempfile.TemporaryDirectory() as td:
            import ainrf.harness_engine.engines.claude_code as cc

            original_dir = cc._SESSION_META_DIR
            cc._SESSION_META_DIR = Path(td)

            try:
                (Path(td) / "bad.json").write_text("not valid json{")
                result = _find_session_meta(100.0)
                assert result is None
            finally:
                cc._SESSION_META_DIR = original_dir


class TestRecalcSessionCostAggregation:
    """Tests for _recalc_session cost aggregation."""

    @pytest.fixture
    def service(self):
        from ainrf.sessions import SessionService

        with tempfile.TemporaryDirectory() as td:
            svc = SessionService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_aggregates_cost_from_multiple_attempts(self, service):
        s = service.create_session(project_id="p1", title="Cost Test")
        a1 = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a1.id,
            status="completed",
            duration_ms=5000,
            token_usage_json=json.dumps(
                {
                    "total": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 1.50},
                    "source": "agent-sdk",
                }
            ),
        )
        a2 = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a2.id,
            status="completed",
            duration_ms=3000,
            token_usage_json=json.dumps(
                {
                    "total": {"input_tokens": 200, "output_tokens": 75, "cost_usd": 2.00},
                    "source": "agent-sdk",
                }
            ),
        )
        s2 = service.get_session(s.id)
        assert s2.total_cost_usd == pytest.approx(3.50)

    def test_null_token_usage_yields_zero_cost(self, service):
        s = service.create_session(project_id="p1", title="Null Test")
        a = service.create_attempt(session_id=s.id)
        service.complete_attempt(a.id, status="completed", duration_ms=1000)
        s2 = service.get_session(s.id)
        assert s2.total_cost_usd == 0.0

    def test_mixed_null_and_valid_costs(self, service):
        s = service.create_session(project_id="p1", title="Mixed Test")
        a1 = service.create_attempt(session_id=s.id)
        service.complete_attempt(a1.id, status="completed", duration_ms=2000)
        a2 = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a2.id,
            status="completed",
            duration_ms=3000,
            token_usage_json=json.dumps(
                {
                    "total": {"input_tokens": 50, "cost_usd": 0.75},
                    "source": "agent-sdk",
                }
            ),
        )
        s2 = service.get_session(s.id)
        assert s2.total_cost_usd == pytest.approx(0.75)

    def test_claude_code_source_no_cost_usd(self, service):
        """Claude Code session-meta has no cost_usd field."""
        s = service.create_session(project_id="p1", title="CC Test")
        a = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a.id,
            status="completed",
            duration_ms=5000,
            token_usage_json=json.dumps(
                {
                    "total": {"input_tokens": 300, "output_tokens": 150},
                    "source": "claude-session-meta",
                }
            ),
        )
        s2 = service.get_session(s.id)
        # No cost_usd --> json_extract returns NULL --> COALESCE --> 0.0
        assert s2.total_cost_usd == 0.0


class TestTaskOutputKindToken:
    def test_token_kind_exists(self):
        from ainrf.harness_engine import OutputEvent

        event = OutputEvent(kind="token", content="", seq=1, created_at="2026-01-01")
        assert event.kind == "token"


class TestEngineEventTokenUsage:
    def test_system_event_carries_token_usage(self):
        from ainrf.harness_engine import EngineEvent

        e = EngineEvent(
            "system",
            {"subtype": "task_completed"},
            token_usage={"total": {"input_tokens": 10}, "source": "agent-sdk"},
        )
        assert e.token_usage == {"total": {"input_tokens": 10}, "source": "agent-sdk"}
        assert e.event_type == "system"

    def test_message_event_defaults_token_usage_none(self):
        from ainrf.harness_engine import EngineEvent

        e = EngineEvent("message", {"role": "assistant", "content": "hello"})
        assert e.token_usage is None

    def test_token_event_type_accepted(self):
        from ainrf.harness_engine import EngineEvent

        e = EngineEvent("token", {}, token_usage={"total": {"input_tokens": 50}})
        assert e.event_type == "token"
        assert e.token_usage is not None


class TestCostAggregationRoundTrip:
    """End-to-end: token_usage_json --> complete_attempt --> _recalc_session --> get_session."""

    @pytest.fixture
    def service(self):
        from ainrf.sessions import SessionService

        with tempfile.TemporaryDirectory() as td:
            svc = SessionService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_round_trip(self, service):
        s = service.create_session(project_id="p1", title="E2E")

        # Create and complete attempt with token data
        a = service.create_attempt(session_id=s.id, task_id="task_1")
        token_usage = {
            "total": {"input_tokens": 5000, "output_tokens": 2000, "cost_usd": 5.50},
            "by_model": {
                "claude-opus-4-7": {
                    "input_tokens": 5000,
                    "output_tokens": 2000,
                    "cost_usd": 5.50,
                },
            },
            "source": "agent-sdk",
        }
        service.complete_attempt(
            a.id,
            status="completed",
            duration_ms=10000,
            token_usage_json=json.dumps(token_usage),
        )

        # Verify session reflects the cost
        s2 = service.get_session(s.id)
        assert s2.task_count == 1
        assert s2.total_cost_usd == pytest.approx(5.50)
        assert s2.total_duration_ms == 10000

        # Verify attempt retains token_usage_json
        attempts = service.list_attempts(s.id)
        assert len(attempts) == 1
        assert attempts[0].token_usage_json is not None
        parsed = json.loads(attempts[0].token_usage_json)
        assert parsed["total"]["cost_usd"] == 5.50

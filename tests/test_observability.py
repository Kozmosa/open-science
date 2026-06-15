"""Tests for the LLM observability abstraction layer."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ainrf.observability.protocol import (
    NullReporter,
    ObservabilityConfig,
    SafeReporter,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# ObservabilityConfig
# ---------------------------------------------------------------------------
class TestObservabilityConfig:
    def test_from_env_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = ObservabilityConfig.from_env()
        assert cfg.enabled is False
        assert cfg.base_url == ""
        assert cfg.secret_key == ""
        assert cfg.public_key == ""

    @pytest.mark.parametrize("val", ("1", "true", "True", "TRUE", "yes", "Yes"))
    def test_from_env_enabled_variants(self, val):
        with patch.dict(os.environ, {"AINRF_OBSERVABILITY_ENABLED": val}):
            cfg = ObservabilityConfig.from_env()
        assert cfg.enabled is True

    def test_from_env_reads_all_keys(self):
        env = {
            "AINRF_OBSERVABILITY_ENABLED": "true",
            "AINRF_OBSERVABILITY_BASE_URL": "http://litefuse:3000",
            "AINRF_OBSERVABILITY_SECRET_KEY": "sk-test",
            "AINRF_OBSERVABILITY_PUBLIC_KEY": "pk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = ObservabilityConfig.from_env()
        assert cfg.enabled is True
        assert cfg.base_url == "http://litefuse:3000"
        assert cfg.secret_key == "sk-test"
        assert cfg.public_key == "pk-test"


# ---------------------------------------------------------------------------
# NullReporter
# ---------------------------------------------------------------------------
class TestNullReporter:
    def test_all_methods_are_noop(self):
        r = NullReporter()
        # None of these should raise.
        r.start_trace("t1", "test")
        r.end_trace("t1")
        r.record_generation("t1", "gen-1")
        r.record_span("t1", "span-1")
        r.flush()

    def test_kwargs_accepted(self):
        r = NullReporter()
        r.start_trace(
            "t1", "test", user_id="u1", session_id="s1", metadata={"k": "v"}, input={"q": "?"}
        )
        r.end_trace("t1", output={"a": 42}, error="oops")
        r.record_generation(
            "t1",
            "gen-1",
            model="claude-3",
            usage_details={"input_tokens": 100},
            cost_details={"cost_usd": 0.01},
            input="prompt",
            output="reply",
        )
        r.record_span("t1", "span-1", input="in", output="out", metadata={"key": "val"})


# ---------------------------------------------------------------------------
# SafeReporter
# ---------------------------------------------------------------------------
class TestSafeReporter:
    def test_delegates_to_inner(self):
        inner = MagicMock(spec=NullReporter)
        safe = SafeReporter(inner)
        safe.start_trace("t1", "test")
        inner.start_trace.assert_called_once_with("t1", "test")

    def test_swallows_exceptions(self):
        failing = MagicMock(spec=NullReporter)
        failing.start_trace.side_effect = RuntimeError("boom")
        safe = SafeReporter(failing)
        # Should not raise.
        safe.start_trace("t1", "test")

    def test_flush_swallows_exceptions(self):
        failing = MagicMock(spec=NullReporter)
        failing.flush.side_effect = RuntimeError("flush error")
        safe = SafeReporter(failing)
        safe.flush()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class TestFactory:
    def setup_method(self):
        from ainrf.observability.factory import reset_reporter

        reset_reporter()

    def teardown_method(self):
        from ainrf.observability.factory import reset_reporter

        reset_reporter()

    def test_returns_null_when_disabled(self):
        from ainrf.observability.factory import get_reporter

        cfg = ObservabilityConfig(enabled=False)
        reporter = get_reporter(cfg)
        # Should be a SafeReporter wrapping NullReporter
        assert isinstance(reporter, SafeReporter)
        assert isinstance(reporter._inner, NullReporter)

    def test_returns_null_on_import_error(self):
        from ainrf.observability.factory import get_reporter

        cfg = ObservabilityConfig(enabled=True, base_url="http://x", secret_key="s", public_key="p")
        with patch.dict("sys.modules", {"langfuse": None}):
            reporter = get_reporter(cfg)
        assert isinstance(reporter, SafeReporter)
        assert isinstance(reporter._inner, NullReporter)

    def test_singleton_pattern(self):
        from ainrf.observability.factory import get_reporter

        r1 = get_reporter(ObservabilityConfig(enabled=False))
        r2 = get_reporter()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        from ainrf.observability.factory import get_reporter, reset_reporter

        r1 = get_reporter(ObservabilityConfig(enabled=False))
        reset_reporter()
        r2 = get_reporter(ObservabilityConfig(enabled=False))
        assert r1 is not r2


# ---------------------------------------------------------------------------
# ApiConfig integration
# ---------------------------------------------------------------------------
class TestApiConfigObservability:
    def test_defaults_disabled(self):
        from ainrf.api.config import ApiConfig
        from pathlib import Path

        with patch.dict(
            os.environ,
            {
                "AINRF_API_KEY_HASHES": "abc123",
            },
            clear=False,
        ):
            cfg = ApiConfig.from_env(state_root=Path("/tmp/ainrf-test"))
        assert cfg.observability_enabled is False
        assert cfg.observability_base_url == ""

    def test_reads_env_vars(self):
        from ainrf.api.config import ApiConfig
        from pathlib import Path

        env = {
            "AINRF_API_KEY_HASHES": "abc123",
            "AINRF_OBSERVABILITY_ENABLED": "true",
            "AINRF_OBSERVABILITY_BASE_URL": "http://litefuse:3000",
            "AINRF_OBSERVABILITY_SECRET_KEY": "sk-abc",
            "AINRF_OBSERVABILITY_PUBLIC_KEY": "pk-xyz",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = ApiConfig.from_env(state_root=Path("/tmp/ainrf-test"))
        assert cfg.observability_enabled is True
        assert cfg.observability_base_url == "http://litefuse:3000"
        assert cfg.observability_secret_key == "sk-abc"
        assert cfg.observability_public_key == "pk-xyz"


# ---------------------------------------------------------------------------
# AgenticResearcherService integration (mocked)
# ---------------------------------------------------------------------------
class TestResearcherObservability:
    """Verify the observability reporter receives calls during task lifecycle."""

    def test_service_accepts_reporter(self):
        """Service constructor accepts observability_reporter without error."""
        from ainrf.agentic_researcher.service import AgenticResearcherService
        from ainrf.observability.protocol import NullReporter
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            reporter = NullReporter()
            svc = AgenticResearcherService(
                Path(tmp),
                observability_reporter=reporter,
            )
            assert svc._observability is reporter

    def test_service_defaults_to_null(self):
        """Service uses NullReporter when none is provided."""
        from ainrf.agentic_researcher.service import AgenticResearcherService
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            svc = AgenticResearcherService(Path(tmp))
            assert isinstance(svc._observability, NullReporter)


# ---------------------------------------------------------------------------
# Literature fetcher integration
# ---------------------------------------------------------------------------
class TestLiteratureObservability:
    @pytest.mark.anyio
    async def test_fetch_for_subscription_accepts_reporter(self):
        """fetch_for_subscription accepts optional reporter parameter."""
        from ainrf.literature.models import LiteratureSubscription
        from ainrf.literature.fetcher import fetch_for_subscription
        from ainrf.observability.protocol import NullReporter

        sub = LiteratureSubscription(
            subscription_id="sub-1",
            label="Test",
            keywords=["test"],
            arxiv_categories=["cs.AI"],
            frequency="daily",
        )
        # Patch arxiv fetch to return empty list (no real API call).
        with patch("ainrf.literature.fetcher.fetch_papers", return_value=[]):
            result = await fetch_for_subscription(sub, NullReporter())
        assert isinstance(result, list)

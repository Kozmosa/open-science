from __future__ import annotations

import pytest

from ainrf.harness_engine import HarnessEngineType, get_engine
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine


def test_get_engine_claude_code() -> None:
    engine = get_engine("claude-code")
    assert isinstance(engine, ClaudeCodeEngine)
    assert engine.engine_type == HarnessEngineType.CLAUDE_CODE


def test_get_engine_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown execution engine"):
        get_engine("unknown-engine")

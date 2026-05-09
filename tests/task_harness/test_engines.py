from __future__ import annotations

import asyncio

import pytest

from ainrf.task_harness.engines import ClaudeCodeEngine, NotSupportedError, get_engine


def test_get_engine_unknown():
    with pytest.raises(ValueError, match="Unknown execution engine"):
        get_engine("unknown")


def test_claude_code_engine_not_supported():
    engine = ClaudeCodeEngine()
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.pause("t-1"))
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.resume(None, None))
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.send_prompt("t-1", "hello"))

from __future__ import annotations

import pytest

from ainrf.harness_engine import (
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
    OutputEvent,
    get_engine,
)
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine


def test_get_engine_claude_code() -> None:
    engine = get_engine("claude-code")
    assert isinstance(engine, ClaudeCodeEngine)
    assert engine.engine_type == HarnessEngineType.CLAUDE_CODE


def test_get_engine_agent_sdk() -> None:
    engine = get_engine("agent-sdk")
    assert isinstance(engine, AgentSdkEngine)
    assert engine.engine_type == HarnessEngineType.AGENT_SDK


def test_get_engine_codex_app_server() -> None:
    engine = get_engine("codex-app-server")
    assert isinstance(engine, CodexAppServerEngine)
    assert engine.engine_type == HarnessEngineType.CODEX_APP_SERVER


def test_get_engine_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown execution engine"):
        get_engine("unknown-engine")


def test_execution_context_creation() -> None:
    ctx = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        prompt="test prompt",
        skills=["skill1"],
        mcp_servers=[],
    )
    assert ctx.task_id == "task-001"
    assert ctx.system_prompt is None


def test_output_event_creation() -> None:
    event = OutputEvent(kind="stdout", content="hello", seq=1, created_at="2026-01-01")
    assert event.kind == "stdout"
    assert event.content == "hello"


def test_harness_engine_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        HarnessEngine()

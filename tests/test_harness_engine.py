from __future__ import annotations

from unittest.mock import patch

import pytest

from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineNotSupportedError,
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
        rendered_prompt="test prompt",
        skills=["skill1"],
        mcp_servers=[],
    )
    assert ctx.task_id == "task-001"
    assert ctx.prompt == "test prompt"
    assert ctx.system_prompt is None


def test_engine_event_creation() -> None:
    event = EngineEvent(
        event_type="system",
        payload={"subtype": "task_started"},
        token_usage={"total": {"input_tokens": 1}},
    )
    assert event.event_type == "system"
    assert event.payload["subtype"] == "task_started"
    assert event.token_usage == {"total": {"input_tokens": 1}}


def test_output_event_creation() -> None:
    event = OutputEvent(kind="stdout", content="hello", seq=1, created_at="2026-01-01")
    assert event.kind == "stdout"
    assert event.content == "hello"


def test_harness_engine_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        HarnessEngine()


@pytest.mark.anyio
async def test_default_unsupported_operations_raise_typed_error() -> None:
    engine = get_engine("claude-code")
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

    async def emit(event: EngineEvent) -> None:
        _ = event

    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.pause("task-001")
    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.resume(context, emit)
    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.send_input("task-001", "hello")


@pytest.mark.anyio
async def test_codex_app_server_start_fails_when_process_exits_before_response() -> None:
    engine = CodexAppServerEngine()
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

    class FakeStreamReader:
        async def readline(self) -> bytes:
            return b""

    class FakeStreamWriter:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStreamWriter()
            self.stdout = FakeStreamReader()
            self.stderr = FakeStreamReader()
            self.returncode = None

        async def wait(self) -> int:
            return 1

        def terminate(self) -> None:
            self.returncode = 1

    async def emit(event: EngineEvent) -> None:
        _ = event

    with patch(
        "ainrf.harness_engine.engines.codex_app_server.asyncio.create_subprocess_exec",
        return_value=FakeProcess(),
    ):
        with pytest.raises(RuntimeError, match="terminated before completing the request"):
            await engine.start(context, emit)

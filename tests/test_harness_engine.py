from __future__ import annotations

from unittest.mock import patch

import pytest
from claude_agent_sdk import ResultMessage, StreamEvent

from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineNotSupportedError,
    HarnessEngineType,
    OutputEvent,
    get_engine,
)
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine, AgentSession
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine, CodexSession


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


def test_claude_code_engine_scrubs_implicit_anthropic_env() -> None:
    engine = ClaudeCodeEngine()
    env = {
        "ANTHROPIC_API_KEY": "stale",
        "ANTHROPIC_AUTH_TOKEN": "stale",
        "PATH": "/usr/bin",
    }
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

    engine._remove_implicit_provider_env(env, context)

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"


def test_claude_code_engine_keeps_explicit_anthropic_env() -> None:
    engine = ClaudeCodeEngine()
    env = {"ANTHROPIC_API_KEY": "explicit"}
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
        api_key="explicit",
    )

    engine._remove_implicit_provider_env(env, context)

    assert env["ANTHROPIC_API_KEY"] == "explicit"


def test_agent_sdk_ignores_partial_stream_deltas() -> None:
    engine = AgentSdkEngine()
    session = AgentSession(task_id="task-001")
    event = StreamEvent(
        uuid="event-001",
        session_id="session-001",
        event={"type": "content_block_delta", "delta": {"text": "Hello"}},
    )

    assert engine._convert_sdk_message(event, session) == []


def test_agent_sdk_failed_result_does_not_require_extra_stderr() -> None:
    engine = AgentSdkEngine()
    session = AgentSession(task_id="task-001")
    result = ResultMessage(
        subtype="result",
        duration_ms=1,
        duration_api_ms=1,
        is_error=True,
        num_turns=1,
        session_id="session-001",
        errors=["Failed to authenticate"],
    )

    events = engine._convert_sdk_message(result, session)

    assert session.had_error is True
    assert session.terminal_emitted is True
    assert [event.event_type for event in events] == ["system", "status"]


@pytest.mark.anyio
async def test_codex_app_server_ignores_partial_agent_message_delta() -> None:
    engine = CodexAppServerEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    await engine._handle_message(
        session=CodexSession(task_id="task-001"),
        payload={
            "method": "item/agentMessage/delta",
            "params": {"delta": "Hello"},
        },
        emit=emit,
    )

    assert emitted == []

@pytest.mark.anyio
async def test_codex_app_server_suppresses_echoed_user_messages() -> None:
    engine = CodexAppServerEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    await engine._handle_message(
        session=CodexSession(task_id="task-001"),
        payload={
            "method": "item/started",
            "params": {"item": {"type": "userMessage", "text": "hello"}},
        },
        emit=emit,
    )

    assert emitted == []


@pytest.mark.anyio
async def test_codex_app_server_starts_with_yolo_sandbox_defaults() -> None:
    engine = CodexAppServerEngine()
    session = CodexSession(task_id="task-001")
    captured: list[tuple[str, dict]] = []

    async def fake_rpc_request(
        _session: CodexSession,
        method: str,
        params: dict,
    ) -> dict:
        captured.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-001"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-001"}}
        return {}

    engine._rpc_request = fake_rpc_request  # type: ignore[method-assign]
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="hello",
    )

    await engine._start_thread(context, session)
    await engine._start_turn(context, session, "hello")

    assert captured[0] == (
        "thread/start",
        {
            "cwd": "/tmp",
            "approvalPolicy": "never",
            "personality": "pragmatic",
            "sandbox": "danger-full-access",
        },
    )
    assert captured[1] == (
        "turn/start",
        {
            "threadId": "thread-001",
            "approvalPolicy": "never",
            "input": [{"type": "text", "text": "hello"}],
            "sandboxPolicy": {"type": "dangerFullAccess"},
        },
    )


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

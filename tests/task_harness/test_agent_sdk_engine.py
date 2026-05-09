from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ainrf.task_harness.engines import AgentSdkEngine
from ainrf.task_harness.engines.base import EngineContext, EngineEvent
from ainrf.task_harness.models import (
    ResearchAgentProfileSnapshot,
    TaskConfigurationMode,
    TaskConfigurationSnapshot,
)


# ---------------------------------------------------------------------------
# Fake SDK message types — patched into the engine module at runtime so
# isinstance() checks in _convert_sdk_message() succeed.
# ---------------------------------------------------------------------------


@dataclass
class FakeTextBlock:
    text: str


@dataclass
class FakeThinkingBlock:
    thinking: str


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class FakeToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class FakeAssistantMessage:
    content: list[Any]


@dataclass
class FakeUserMessage:
    content: str | list[dict[str, Any]]


@dataclass
class FakeSystemMessage:
    subtype: str
    data: dict[str, Any]


@dataclass
class FakeResultMessage:
    session_id: str
    num_turns: int
    total_cost_usd: float
    is_error: bool
    errors: list[str] | None = None


@dataclass
class FakeStreamEvent:
    event: dict[str, Any]


@dataclass
class FakeRateLimitEvent:
    rate_limit_info: dict[str, Any]


def _make_context(
    *,
    task_id: str = "t-1",
    working_directory: str = "/tmp/wd",
    rendered_prompt: str = "do work",
    api_base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    env_overrides: dict[str, str] | None = None,
    session_state_path: str | None = None,
) -> EngineContext:
    return EngineContext(
        task_id=task_id,
        working_directory=working_directory,
        rendered_prompt=rendered_prompt,
        agent_profile=ResearchAgentProfileSnapshot(
            profile_id="test-profile",
            label="Test",
            system_prompt=None,
            skills=[],
            skills_prompt=None,
            settings_json=None,
            settings_artifact_path=None,
            model=model,
            permission_mode=None,
            max_turns=None,
            max_budget_usd=None,
            mcp_servers=None,
            disallowed_tools=None,
            api_base_url=api_base_url,
            api_key=api_key,
            default_opus_model=None,
            default_sonnet_model=None,
            default_haiku_model=None,
            env_overrides=env_overrides,
        ),
        task_config=TaskConfigurationSnapshot(
            mode=TaskConfigurationMode.RAW_PROMPT,
            template_id=None,
            template_vars={},
            raw_prompt=None,
            rendered_task_input="",
        ),
        session_state_path=session_state_path,
    )


def _async_iter(items: list[Any]):
    """Return an async iterator that yields *items*."""

    async def _gen():
        for item in items:
            yield item

    return _gen()


@pytest.fixture
def patch_sdk_classes():
    """Patch all SDK class references in the engine module."""
    with (
        patch("ainrf.task_harness.engines.agent_sdk.AssistantMessage", FakeAssistantMessage),
        patch("ainrf.task_harness.engines.agent_sdk.ResultMessage", FakeResultMessage),
        patch("ainrf.task_harness.engines.agent_sdk.SystemMessage", FakeSystemMessage),
        patch("ainrf.task_harness.engines.agent_sdk.UserMessage", FakeUserMessage),
        patch("ainrf.task_harness.engines.agent_sdk.StreamEvent", FakeStreamEvent),
        patch("ainrf.task_harness.engines.agent_sdk.RateLimitEvent", FakeRateLimitEvent),
        patch("ainrf.task_harness.engines.agent_sdk.TextBlock", FakeTextBlock),
        patch("ainrf.task_harness.engines.agent_sdk.ThinkingBlock", FakeThinkingBlock),
        patch("ainrf.task_harness.engines.agent_sdk.ToolUseBlock", FakeToolUseBlock),
        patch("ainrf.task_harness.engines.agent_sdk.ToolResultBlock", FakeToolResultBlock),
    ):
        yield


@pytest.mark.anyio
async def test_start_emits_assistant_text_and_thinking(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeSystemMessage(subtype="init", data={"session_id": "sess-1"}),
        FakeAssistantMessage(content=[FakeTextBlock(text="Hello")]),
        FakeAssistantMessage(content=[FakeThinkingBlock(thinking="planning...")]),
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(), emit)

    assert len(emitted) >= 3
    assert emitted[0].event_type == "system"
    assert emitted[0].payload["subtype"] == "task_started"
    assert emitted[1].event_type == "message"
    assert emitted[1].payload["content"] == "Hello"
    assert emitted[2].event_type == "thinking"
    assert emitted[2].payload["content"] == "planning..."
    assert emitted[-1].event_type == "system"
    assert emitted[-1].payload["subtype"] == "task_completed"


@pytest.mark.anyio
async def test_start_emits_tool_call_and_tool_result(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeAssistantMessage(
            content=[FakeToolUseBlock(id="tu-1", name="Read", input={"file_path": "/x"})]
        ),
        FakeAssistantMessage(
            content=[FakeToolResultBlock(tool_use_id="tu-1", content="file data")]
        ),
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(), emit)

    tool_call = [e for e in emitted if e.event_type == "tool_call"][0]
    assert tool_call.payload["name"] == "Read"
    assert tool_call.payload["arguments"] == {"file_path": "/x"}

    tool_result = [e for e in emitted if e.event_type == "tool_result"][0]
    assert tool_result.payload["tool_use_id"] == "tu-1"
    assert tool_result.payload["content"] == "file data"


@pytest.mark.anyio
async def test_start_emits_user_message(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeUserMessage(content="user says hi"),
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(), emit)

    msg = [e for e in emitted if e.event_type == "message"][0]
    assert msg.payload["role"] == "user"
    assert msg.payload["content"] == "user says hi"


@pytest.mark.anyio
async def test_start_emits_stream_event_delta(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeStreamEvent(event={"type": "content_block_delta", "delta": {"text": "chunk"}}),
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(), emit)

    msg = [e for e in emitted if e.event_type == "message" and e.payload.get("streaming")][0]
    assert msg.payload["content"] == "chunk"


@pytest.mark.anyio
async def test_start_emits_rate_limit_event(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeRateLimitEvent(rate_limit_info={"retry_after": 5}),
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(), emit)

    evt = [
        e for e in emitted if e.event_type == "system" and e.payload.get("subtype") == "rate_limit"
    ][0]
    assert evt.payload["rate_limit_info"] == {"retry_after": 5}


@pytest.mark.anyio
async def test_result_error_sets_had_error_and_emits_failure(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeResultMessage(
            session_id="sess-1",
            num_turns=1,
            total_cost_usd=0.01,
            is_error=True,
            errors=["something broke"],
        ),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        with pytest.raises(RuntimeError, match="completed with errors"):
            await engine.start(_make_context(), emit)

    failure = [
        e for e in emitted if e.event_type == "system" and e.payload.get("subtype") == "task_failed"
    ][0]
    assert failure.payload["errors"] == ["something broke"]


@pytest.mark.anyio
async def test_pause_sets_flag_and_start_emits_paused(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    await engine.pause("t-1")

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(task_id="t-1"), emit)

    paused = [
        e for e in emitted if e.event_type == "system" and e.payload.get("subtype") == "task_paused"
    ]
    assert len(paused) == 1


@pytest.mark.anyio
async def test_resume_delegates_to_start(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.resume(_make_context(), emit)

    assert any(
        e.event_type == "system" and e.payload.get("subtype") == "task_completed" for e in emitted
    )


@pytest.mark.anyio
async def test_send_prompt_queues_and_start_uses_it(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []
    captured_prompt: str | None = None

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    def capture_query(*, prompt: str, options: Any):
        nonlocal captured_prompt
        captured_prompt = prompt
        return _async_iter([])

    await engine.send_prompt("t-1", "queued prompt")

    with patch("ainrf.task_harness.engines.agent_sdk.query", side_effect=capture_query):
        await engine.start(_make_context(task_id="t-1"), emit)

    assert captured_prompt == "queued prompt"


@pytest.mark.anyio
async def test_abort_breaks_query_and_raises_cancelled(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    async def slow_query(*, prompt: str, options: Any):
        for _ in range(100):
            await asyncio.sleep(0.01)
            yield FakeSystemMessage(subtype="ping", data={})

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query",
        return_value=slow_query(prompt="", options=None),
    ):
        task = asyncio.create_task(engine.start(_make_context(), emit))
        await asyncio.sleep(0.05)
        await engine.abort("t-1")
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_start_raises_cancelled_error_propagates(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    class RaisingAsyncIter:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise asyncio.CancelledError("outer cancel")

    with patch("ainrf.task_harness.engines.agent_sdk.query", return_value=RaisingAsyncIter()):
        with pytest.raises(asyncio.CancelledError, match="outer cancel"):
            await engine.start(_make_context(), emit)


@pytest.mark.anyio
async def test_start_saves_checkpoint_on_completion(patch_sdk_classes, tmp_path: Path) -> None:
    engine = AgentSdkEngine()
    checkpoint_path = tmp_path / "checkpoint.json"

    async def emit(event: EngineEvent) -> None:
        pass

    sdk_messages = [
        FakeResultMessage(session_id="sess-abc", num_turns=3, total_cost_usd=0.05, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ):
        await engine.start(_make_context(session_state_path=str(checkpoint_path)), emit)

    data = json.loads(checkpoint_path.read_text())
    assert data["session_id"] == "sess-abc"
    assert data["turn_count"] == 3
    assert data["total_cost_usd"] == 0.05


@pytest.mark.anyio
async def test_start_loads_checkpoint_and_resumes_session(
    patch_sdk_classes, tmp_path: Path
) -> None:
    engine = AgentSdkEngine()
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "task_id": "t-1",
                "session_id": "sess-resume",
                "cwd": "/tmp/wd",
                "created_at": "2026-01-01T00:00:00",
                "turn_count": 5,
                "total_cost_usd": 0.10,
                "pending_prompts": ["resume prompt"],
            }
        )
    )

    captured_prompt: str | None = None
    captured_resume: str | None = None

    async def emit(event: EngineEvent) -> None:
        pass

    def capture_query(*, prompt: str, options: Any):
        nonlocal captured_prompt, captured_resume
        captured_prompt = prompt
        captured_resume = options.resume
        return _async_iter([])

    with patch("ainrf.task_harness.engines.agent_sdk.query", side_effect=capture_query):
        await engine.start(_make_context(session_state_path=str(checkpoint_path)), emit)

    assert captured_prompt == "resume prompt"
    assert captured_resume == "sess-resume"


@pytest.mark.anyio
async def test_env_override_sets_api_key_and_base_url(
    patch_sdk_classes, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = AgentSdkEngine()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    async def emit(event: EngineEvent) -> None:
        pass

    env_vars: dict[str, str | None] = {}

    def capture_query(*, prompt: str, options: Any):
        env_vars["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY")
        env_vars["ANTHROPIC_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL")
        env_vars["ANTHROPIC_AUTH_TOKEN"] = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        return _async_iter([])

    with patch("ainrf.task_harness.engines.agent_sdk.query", side_effect=capture_query):
        await engine.start(
            _make_context(api_key="sk-test", api_base_url="https://api.test"),
            emit,
        )

    assert env_vars["ANTHROPIC_API_KEY"] == "sk-test"
    assert env_vars["ANTHROPIC_BASE_URL"] == "https://api.test"
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "sk-test"


@pytest.mark.anyio
async def test_env_override_prefers_auth_token_when_env_override_set(
    patch_sdk_classes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AgentSdkEngine()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    async def emit(event: EngineEvent) -> None:
        pass

    env_vars: dict[str, str | None] = {}

    def capture_query(*, prompt: str, options: Any):
        env_vars["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY")
        env_vars["ANTHROPIC_AUTH_TOKEN"] = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        return _async_iter([])

    with patch("ainrf.task_harness.engines.agent_sdk.query", side_effect=capture_query):
        await engine.start(
            _make_context(
                api_key="sk-test",
                env_overrides={"ANTHROPIC_AUTH_TOKEN": "token-from-override"},
            ),
            emit,
        )

    assert env_vars["ANTHROPIC_API_KEY"] is None
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "token-from-override"


@pytest.mark.anyio
async def test_start_catches_exception_and_emits_error(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    class BadAsyncIter:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("sdk blew up")

    with patch("ainrf.task_harness.engines.agent_sdk.query", return_value=BadAsyncIter()):
        with pytest.raises(RuntimeError, match="sdk blew up"):
            await engine.start(_make_context(), emit)

    error_evt = [e for e in emitted if e.event_type == "error"][0]
    assert "sdk blew up" in error_evt.payload["message"]
    failure_evt = [
        e for e in emitted if e.event_type == "system" and e.payload.get("subtype") == "task_failed"
    ][0]
    assert failure_evt is not None


@pytest.mark.anyio
async def test_post_tool_use_hook_emits_event(patch_sdk_classes):
    engine = AgentSdkEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    sdk_messages = [
        FakeResultMessage(session_id="sess-1", num_turns=1, total_cost_usd=0.01, is_error=False),
    ]

    with patch(
        "ainrf.task_harness.engines.agent_sdk.query", return_value=_async_iter(sdk_messages)
    ) as mock_query:
        await engine.start(_make_context(), emit)

    # Hooks are registered; verify they are wired by checking options passed
    _call_args, kwargs = mock_query.call_args
    options = kwargs["options"]
    assert "PostToolUse" in options.hooks
    assert "Notification" in options.hooks

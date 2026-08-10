from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ainrf.domain.conversation_contracts import CapabilitySupport, EngineCapability
from ainrf.harness_engine.base import ExecutionContext, HarnessEngineType
from ainrf.harness_engine.conversation_adapter import (
    ConversationRuntimeAdapter,
    NativeAcceptanceIdentity,
)
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine, AgentSession
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine, CodexSession

pytestmark = [pytest.mark.engine]


def test_adapter_capabilities_do_not_claim_cli_or_one_shot_sdk_steer() -> None:
    sdk = ConversationRuntimeAdapter(AgentSdkEngine())
    cli = ConversationRuntimeAdapter(ClaudeCodeEngine())
    codex = ConversationRuntimeAdapter(CodexAppServerEngine())

    assert sdk.capabilities()[EngineCapability.SAME_TURN_STEER] is CapabilitySupport.UNSUPPORTED
    assert cli.capabilities()[EngineCapability.SAME_TURN_STEER] is CapabilitySupport.UNSUPPORTED
    assert codex.capabilities()[EngineCapability.SAME_TURN_STEER] is CapabilitySupport.NATIVE


def test_adapter_exposes_engine_conversation_identity_at_acceptance() -> None:
    codex_engine = CodexAppServerEngine()
    codex_engine._sessions["launch-codex"] = CodexSession(
        task_id="task-codex",
        runtime_identity="launch-codex",
        thread_id="thread-native",
    )
    codex = ConversationRuntimeAdapter(codex_engine)
    assert codex.native_conversation_identity(
        runtime_launch_key="launch-codex",
        fallback_task_id="task-codex",
    ) == ("thread", "thread-native")

    sdk_engine = AgentSdkEngine()
    sdk_engine._sessions["launch-sdk"] = AgentSession(
        task_id="task-sdk",
        runtime_identity="launch-sdk",
        session_id="session-native",
    )
    sdk = ConversationRuntimeAdapter(sdk_engine)
    assert sdk.native_conversation_identity(
        runtime_launch_key="launch-sdk",
        fallback_task_id="task-sdk",
    ) == ("session", "session-native")

    cli_engine = ClaudeCodeEngine()
    cli_engine._session_ids["launch-cli"] = "session-cli"
    cli = ConversationRuntimeAdapter(cli_engine)
    assert cli.native_conversation_identity(
        runtime_launch_key="launch-cli",
        fallback_task_id="task-cli",
    ) == ("session", "session-cli")


def test_codex_acceptance_waits_for_native_thread_and_turn() -> None:
    engine = CodexAppServerEngine()
    session = CodexSession(
        task_id="task-1",
        runtime_identity="launch-1",
        thread_id="thread-1",
    )
    engine._sessions["launch-1"] = session
    adapter = ConversationRuntimeAdapter(engine)

    assert (
        adapter.native_acceptance_identity(
            runtime_launch_key="launch-1",
            fallback_task_id="task-1",
            fallback_turn_id="fallback-turn",
        )
        is None
    )

    session.turn_id = "native-turn-1"
    assert adapter.native_acceptance_identity(
        runtime_launch_key="launch-1",
        fallback_task_id="task-1",
        fallback_turn_id="fallback-turn",
    ) == NativeAcceptanceIdentity(
        conversation_kind="thread",
        conversation_ref="thread-1",
        turn_kind="turn",
        turn_ref="native-turn-1",
    )


@pytest.mark.anyio
async def test_codex_start_clears_historical_turn_before_next_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CodexAppServerEngine()
    session = CodexSession(
        task_id="task-1",
        runtime_identity="launch-1",
        thread_id="thread-1",
        turn_id="historical-turn",
    )
    engine._sessions["launch-1"] = session
    observed_turns: list[str | None] = []

    async def no_connection(*args: object, **kwargs: object) -> None:
        _ = args, kwargs

    async def start_new_turn(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        observed_turns.append(session.turn_id)
        session.turn_id = "new-turn"

    monkeypatch.setattr(engine, "_ensure_connection", no_connection)
    monkeypatch.setattr(engine, "_resume_thread", no_connection)
    monkeypatch.setattr(engine, "_start_turn", start_new_turn)
    monkeypatch.setattr(engine, "_await_turn", no_connection)
    await engine.start(
        ExecutionContext(
            task_id="task-1",
            working_directory="/tmp",
            rendered_prompt="hello",
            engine_type=HarnessEngineType.CODEX_APP_SERVER,
            runtime_launch_key="launch-1",
        ),
        AsyncMock(),
    )

    assert observed_turns == [None]
    assert session.turn_id == "new-turn"


def test_adapter_derives_fresh_session_identity_from_bound_runtime_context() -> None:
    context = ExecutionContext(
        task_id="task-1",
        working_directory="/tmp",
        rendered_prompt="hello",
        engine_type=HarnessEngineType.AGENT_SDK,
        runtime_launch_key="launch-1",
    )
    sdk_engine = AgentSdkEngine()
    sdk_engine._sessions["launch-1"] = AgentSession(
        task_id="task-1",
        runtime_identity="launch-1",
    )
    sdk = ConversationRuntimeAdapter(sdk_engine)
    sdk._runtime_contexts["launch-1"] = context
    assert sdk.native_conversation_identity(
        runtime_launch_key="launch-1",
        fallback_task_id="task-1",
    ) == ("session", sdk_engine._runtime_session_id(context))

    cli_engine = ClaudeCodeEngine()
    cli = ConversationRuntimeAdapter(cli_engine)
    cli._runtime_contexts["launch-1"] = context
    assert cli.native_conversation_identity(
        runtime_launch_key="launch-1",
        fallback_task_id="task-1",
    ) == ("session", "launch-1")


@pytest.mark.anyio
async def test_codex_adapter_uses_native_expected_turn_guard() -> None:
    engine = CodexAppServerEngine()
    engine._sessions["execution-1"] = CodexSession(
        task_id="task-1",
        runtime_identity="execution-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    rpc_request = AsyncMock(return_value={"accepted": True})
    engine._rpc_request = rpc_request  # type: ignore[method-assign]
    adapter = ConversationRuntimeAdapter(engine)

    receipt = await adapter.steer_turn(
        task_id="task-1",
        expected_turn_id="turn-1",
        text="adjust",
        runtime_launch_key="execution-1",
    )

    assert receipt.support is CapabilitySupport.NATIVE
    assert receipt.accepted is True
    rpc_request.assert_awaited_once_with(
        engine._sessions["execution-1"],
        "turn/steer",
        {
            "threadId": "thread-1",
            "expectedTurnId": "turn-1",
            "input": [{"type": "text", "text": "adjust"}],
        },
    )

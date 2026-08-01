from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ainrf.domain.conversation_contracts import CapabilitySupport, EngineCapability
from ainrf.harness_engine.conversation_adapter import ConversationRuntimeAdapter
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine
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

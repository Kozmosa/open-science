"""Runtime Adapter Interface for canonical Conversation execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ainrf.domain.conversation_contracts import (
    CapabilitySupport,
    EngineCapability,
)
from ainrf.harness_engine.base import EngineEmit, ExecutionContext, HarnessEngine, HarnessEngineType
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine


@dataclass(frozen=True, slots=True)
class ControlReceipt:
    support: CapabilitySupport
    accepted: bool
    evidence: Mapping[str, object]


class ConversationRuntimeAdapter:
    """Translate one concrete Harness implementation at the runtime Seam."""

    def __init__(self, engine: HarnessEngine) -> None:
        self._engine = engine

    @property
    def engine_type(self) -> HarnessEngineType:
        return self._engine.engine_type

    def capabilities(self) -> dict[EngineCapability, CapabilitySupport]:
        common = {
            EngineCapability.DURABLE_CONVERSATION: CapabilitySupport.NATIVE,
            EngineCapability.INTERRUPT: CapabilitySupport.DEGRADED,
            EngineCapability.TYPED_ITEMS: CapabilitySupport.DEGRADED,
            EngineCapability.USAGE: CapabilitySupport.DEGRADED,
            EngineCapability.ACTIVE_RUNTIME_ADOPTION: CapabilitySupport.UNSUPPORTED,
        }
        if self.engine_type is HarnessEngineType.CODEX_APP_SERVER:
            common.update(
                {
                    EngineCapability.NATIVE_TURN_ID: CapabilitySupport.NATIVE,
                    EngineCapability.SAME_TURN_STEER: CapabilitySupport.NATIVE,
                    EngineCapability.INTERRUPT: CapabilitySupport.NATIVE,
                    EngineCapability.RECONNECT: CapabilitySupport.DEGRADED,
                    EngineCapability.FORK: CapabilitySupport.UNSUPPORTED,
                }
            )
        elif self.engine_type is HarnessEngineType.AGENT_SDK:
            common.update(
                {
                    EngineCapability.NATIVE_TURN_ID: CapabilitySupport.EMULATED,
                    EngineCapability.SAME_TURN_STEER: CapabilitySupport.UNSUPPORTED,
                    EngineCapability.RECONNECT: CapabilitySupport.DEGRADED,
                    EngineCapability.FORK: CapabilitySupport.UNSUPPORTED,
                }
            )
        else:
            common.update(
                {
                    EngineCapability.NATIVE_TURN_ID: CapabilitySupport.EMULATED,
                    EngineCapability.SAME_TURN_STEER: CapabilitySupport.UNSUPPORTED,
                    EngineCapability.RECONNECT: CapabilitySupport.DEGRADED,
                    EngineCapability.FORK: CapabilitySupport.UNSUPPORTED,
                }
            )
        return common

    async def start_turn(self, context: ExecutionContext, emit: EngineEmit) -> None:
        await self._engine.start(context, emit)

    def native_turn_identity(
        self,
        *,
        runtime_launch_key: str,
        fallback_turn_id: str,
    ) -> tuple[str, str]:
        if isinstance(self._engine, CodexAppServerEngine):
            session = self._engine._sessions.get(runtime_launch_key)
            if session is not None and session.turn_id:
                return "turn", session.turn_id
        if isinstance(self._engine, AgentSdkEngine):
            session = self._engine._sessions.get(runtime_launch_key)
            if session is not None and session.session_id:
                return "sdk_query", f"{session.session_id}:{fallback_turn_id}"
        if isinstance(self._engine, ClaudeCodeEngine):
            session_id = self._engine._session_ids.get(runtime_launch_key)
            if session_id:
                return "cli_process", f"{session_id}:{fallback_turn_id}"
        return "driver_execution", fallback_turn_id

    async def steer_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        text: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        if isinstance(self._engine, CodexAppServerEngine):
            evidence = await self._engine.steer_turn(
                task_id,
                expected_turn_id,
                text,
                runtime_launch_key=runtime_launch_key,
            )
            return ControlReceipt(CapabilitySupport.NATIVE, True, evidence)
        return ControlReceipt(
            CapabilitySupport.UNSUPPORTED,
            False,
            {"reason": "driver does not provide same-Turn steer"},
        )

    async def interrupt_turn(
        self,
        *,
        task_id: str,
        expected_turn_id: str,
        runtime_launch_key: str,
    ) -> ControlReceipt:
        if isinstance(self._engine, CodexAppServerEngine):
            evidence = await self._engine.interrupt_turn(
                task_id,
                expected_turn_id,
                runtime_launch_key=runtime_launch_key,
            )
            return ControlReceipt(CapabilitySupport.NATIVE, True, evidence)
        await self._engine.cancel(task_id, runtime_launch_key=runtime_launch_key)
        return ControlReceipt(
            CapabilitySupport.DEGRADED,
            True,
            {"reason": "driver uses process/query interruption"},
        )

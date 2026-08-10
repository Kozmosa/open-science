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


@dataclass(frozen=True, slots=True)
class NativeAcceptanceIdentity:
    conversation_kind: str
    conversation_ref: str
    turn_kind: str
    turn_ref: str


class ConversationRuntimeAdapter:
    """Translate one concrete Harness implementation at the runtime Seam."""

    def __init__(self, engine: HarnessEngine) -> None:
        self._engine = engine
        self._runtime_contexts: dict[str, ExecutionContext] = {}

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
        runtime_identity = context.runtime_identity
        self._runtime_contexts[runtime_identity] = context
        try:
            await self._engine.start(context, emit)
        finally:
            if self._runtime_contexts.get(runtime_identity) is context:
                self._runtime_contexts.pop(runtime_identity, None)

    def native_conversation_identity(
        self,
        *,
        runtime_launch_key: str,
        fallback_task_id: str,
    ) -> tuple[str, str]:
        """Return the engine's durable conversation identity at acceptance.

        The worker calls this only after the engine emits its first event.  A
        missing identity is therefore a provider-contract failure, not a
        reason to invent Task- or Turn-scoped lineage downstream.
        """

        if isinstance(self._engine, CodexAppServerEngine):
            session = self._engine._sessions.get(runtime_launch_key)
            if session is not None and session.task_id == fallback_task_id and session.thread_id:
                return "thread", session.thread_id
        elif isinstance(self._engine, AgentSdkEngine):
            session = self._engine._sessions.get(runtime_launch_key)
            if session is not None and session.task_id == fallback_task_id:
                if session.session_id:
                    return "session", session.session_id
                context = self._runtime_contexts.get(runtime_launch_key)
                if context is not None and context.task_id == fallback_task_id:
                    session_id = self._engine._runtime_session_id(context)
                    if session_id:
                        return "session", session_id
        elif isinstance(self._engine, ClaudeCodeEngine):
            context = self._runtime_contexts.get(runtime_launch_key)
            session_id = self._engine._session_ids.get(runtime_launch_key)
            if session_id and (context is None or context.task_id == fallback_task_id):
                return "session", session_id
            if context is not None and context.task_id == fallback_task_id:
                return "session", self._engine._make_session_id(context)
        raise RuntimeError("Runtime adapter did not expose a native conversation identity")

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

    def native_acceptance_identity(
        self,
        *,
        runtime_launch_key: str,
        fallback_task_id: str,
        fallback_turn_id: str,
    ) -> NativeAcceptanceIdentity | None:
        """Return a complete native identity only at the acceptance boundary."""

        try:
            conversation_kind, conversation_ref = self.native_conversation_identity(
                runtime_launch_key=runtime_launch_key,
                fallback_task_id=fallback_task_id,
            )
        except RuntimeError:
            return None
        if isinstance(self._engine, CodexAppServerEngine):
            session = self._engine._sessions.get(runtime_launch_key)
            if session is None or session.task_id != fallback_task_id or not session.turn_id:
                return None
            turn_kind, turn_ref = "turn", session.turn_id
        else:
            turn_kind, turn_ref = self.native_turn_identity(
                runtime_launch_key=runtime_launch_key,
                fallback_turn_id=fallback_turn_id,
            )
        return NativeAcceptanceIdentity(
            conversation_kind=conversation_kind,
            conversation_ref=conversation_ref,
            turn_kind=turn_kind,
            turn_ref=turn_ref,
        )

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

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class HarnessEngineType(StrEnum):
    CLAUDE_CODE = "claude-code"
    AGENT_SDK = "agent-sdk"
    CODEX_APP_SERVER = "codex-app-server"


class HarnessEngineError(RuntimeError):
    """Base error for harness engine operations."""


class HarnessEngineNotSupportedError(HarnessEngineError):
    """Engine does not support this operation."""


@dataclass(slots=True)
class ExecutionContext:
    task_id: str
    working_directory: str
    rendered_prompt: str
    researcher_type: str = "vanilla"
    engine_type: HarnessEngineType = HarnessEngineType.CLAUDE_CODE
    skills: list[str] | None = None
    mcp_servers: dict[str, dict[str, object]] | None = None
    system_prompt: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    default_opus_model: str | None = None
    default_sonnet_model: str | None = None
    default_haiku_model: str | None = None
    env_overrides: dict[str, str] | None = None
    codex_base_url: str | None = None
    codex_api_key: str | None = None
    codex_model: str | None = None
    codex_app_server_command: str | None = None
    codex_approval_policy: str | None = None
    codex_home_path: str | None = None
    session_state_path: str | None = None

    @property
    def prompt(self) -> str:
        """Compatibility alias for the user-visible rendered prompt."""
        return self.rendered_prompt


@dataclass(slots=True)
class ExecutionHandle:
    task_id: str
    engine_type: HarnessEngineType


@dataclass(slots=True)
class OutputEvent:
    kind: Literal[
        "stdout",
        "stderr",
        "system",
        "lifecycle",
        "message",
        "thinking",
        "tool_call",
        "tool_result",
        "token",
    ]
    content: str
    seq: int
    created_at: str


@dataclass(slots=True)
class EngineEvent:
    event_type: Literal[
        "message",
        "thinking",
        "tool_call",
        "tool_result",
        "status",
        "system",
        "error",
        "token",
    ]
    payload: dict[str, Any]
    token_usage: dict[str, Any] | None = None


EngineEmit = Callable[[EngineEvent], Awaitable[None]]


class HarnessEngine(ABC):
    """执行引擎抽象基类"""

    @property
    @abstractmethod
    def engine_type(self) -> HarnessEngineType:
        """返回引擎类型标识"""
        ...

    @abstractmethod
    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        """Start executing the context and emit engine events until completion."""
        ...

    async def pause(self, task_id: str) -> None:
        """Pause an active task when supported by the engine."""
        raise HarnessEngineNotSupportedError(f"{self.engine_type} does not support pause")

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        """Resume a paused task when supported by the engine."""
        raise HarnessEngineNotSupportedError(f"{self.engine_type} does not support resume")

    async def send_input(self, task_id: str, text: str) -> None:
        """Send follow-up input to an active task when supported by the engine."""
        raise HarnessEngineNotSupportedError(f"{self.engine_type} does not support send_input")

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        """取消执行"""
        ...

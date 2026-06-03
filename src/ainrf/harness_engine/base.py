from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class HarnessEngineType(StrEnum):
    CLAUDE_CODE = "claude-code"
    AGENT_SDK = "agent-sdk"
    CODEX_APP_SERVER = "codex-app-server"


@dataclass(slots=True)
class ExecutionContext:
    task_id: str
    working_directory: str
    prompt: str
    skills: list[str]
    mcp_servers: list[str]
    system_prompt: str | None = None


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


class HarnessEngine(ABC):
    """执行引擎抽象基类"""

    @property
    @abstractmethod
    def engine_type(self) -> HarnessEngineType:
        """返回引擎类型标识"""
        ...

    @abstractmethod
    async def launch(self, context: ExecutionContext) -> ExecutionHandle:
        """启动执行，返回执行句柄"""
        ...

    @abstractmethod
    async def stream_output(self, handle: ExecutionHandle) -> AsyncIterator[OutputEvent]:
        """流式输出事件"""
        ...

    @abstractmethod
    async def send_input(self, handle: ExecutionHandle, text: str) -> None:
        """发送输入到执行中的任务"""
        ...

    @abstractmethod
    async def cancel(self, handle: ExecutionHandle) -> None:
        """取消执行"""
        ...

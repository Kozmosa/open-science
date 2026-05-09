from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from ainrf.task_harness.models import (
    ResearchAgentProfileSnapshot,
    TaskConfigurationSnapshot,
    TaskHarnessError,
)


class NotSupportedError(TaskHarnessError):
    """Engine does not support this operation."""


@dataclass(slots=True)
class EngineContext:
    task_id: str
    working_directory: str
    rendered_prompt: str
    agent_profile: ResearchAgentProfileSnapshot
    task_config: TaskConfigurationSnapshot
    session_state_path: str | None = None


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
    ]
    payload: dict


class ExecutionEngine(ABC):
    @abstractmethod
    async def start(
        self,
        context: EngineContext,
        emit: Callable[[EngineEvent], Awaitable[None]],
    ) -> None: ...

    @abstractmethod
    async def pause(self, task_id: str) -> None: ...

    @abstractmethod
    async def resume(
        self,
        context: EngineContext,
        emit: Callable[[EngineEvent], Awaitable[None]],
    ) -> None: ...

    @abstractmethod
    async def send_prompt(self, task_id: str, prompt: str) -> None: ...

    @abstractmethod
    async def abort(self, task_id: str) -> None: ...

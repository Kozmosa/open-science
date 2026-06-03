from __future__ import annotations

from collections.abc import AsyncIterator

from ainrf.harness_engine.base import (
    ExecutionContext,
    ExecutionHandle,
    HarnessEngine,
    HarnessEngineType,
    OutputEvent,
)


class ClaudeCodeEngine(HarnessEngine):
    """Claude Code 执行引擎"""

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def launch(self, context: ExecutionContext) -> ExecutionHandle:
        # TODO: 迁移实际启动逻辑
        return ExecutionHandle(
            task_id=context.task_id,
            engine_type=self.engine_type,
        )

    async def stream_output(self, handle: ExecutionHandle) -> AsyncIterator[OutputEvent]:
        # TODO: 迁移实际流式输出逻辑
        yield OutputEvent(kind="system", content="Not implemented", seq=0, created_at="")

    async def send_input(self, handle: ExecutionHandle, text: str) -> None:
        # TODO: 迁移实际输入发送逻辑
        pass

    async def cancel(self, handle: ExecutionHandle) -> None:
        # TODO: 迁移实际取消逻辑
        pass

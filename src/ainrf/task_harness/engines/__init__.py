from .base import ExecutionEngine, EngineContext, EngineEvent, NotSupportedError
from .claude_code import ClaudeCodeEngine
from .factory import get_engine

__all__ = [
    "ExecutionEngine",
    "EngineContext",
    "EngineEvent",
    "NotSupportedError",
    "get_engine",
    "ClaudeCodeEngine",
    "AgentSdkEngine",
]


def __getattr__(name: str):
    if name == "AgentSdkEngine":
        from .agent_sdk import AgentSdkEngine as _engine
        return _engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

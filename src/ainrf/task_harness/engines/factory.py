from __future__ import annotations

from .base import ExecutionEngine


_ENGINES: dict[str, str] = {
    "claude-code": "ainrf.task_harness.engines.claude_code:ClaudeCodeEngine",
    "agent-sdk": "ainrf.task_harness.engines.agent_sdk:AgentSdkEngine",
    "codex-app-server": "ainrf.task_harness.engines.codex_app_server:CodexAppServerEngine",
}


def get_engine(name: str) -> ExecutionEngine:
    spec = _ENGINES.get(name)
    if spec is None:
        raise ValueError(f"Unknown execution engine: {name}")
    module_name, class_name = spec.rsplit(":", 1)
    import importlib

    module = importlib.import_module(module_name)
    engine_cls = getattr(module, class_name)
    instance = engine_cls()
    if not isinstance(instance, ExecutionEngine):
        raise TypeError(f"Engine {name!r} ({spec}) does not implement ExecutionEngine")
    return instance

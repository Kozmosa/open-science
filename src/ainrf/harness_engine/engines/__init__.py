from __future__ import annotations

from ainrf.harness_engine.base import HarnessEngine, HarnessEngineType

_ENGINES: dict[str, str] = {
    "claude-code": "ainrf.harness_engine.engines.claude_code:ClaudeCodeEngine",
    "agent-sdk": "ainrf.harness_engine.engines.agent_sdk:AgentSdkEngine",
    "codex-app-server": "ainrf.harness_engine.engines.codex_app_server:CodexAppServerEngine",
}


def get_engine(name: str) -> HarnessEngine:
    spec = _ENGINES.get(name)
    if spec is None:
        raise ValueError(f"Unknown execution engine: {name}")
    module_name, class_name = spec.rsplit(":", 1)
    import importlib

    module = importlib.import_module(module_name)
    engine_cls = getattr(module, class_name)
    instance = engine_cls()
    if not isinstance(instance, HarnessEngine):
        raise TypeError(f"Engine {name!r} ({spec}) does not implement HarnessEngine")
    return instance

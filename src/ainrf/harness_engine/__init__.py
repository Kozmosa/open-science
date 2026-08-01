"""Lazy compatibility exports for engine Interfaces and Adapters."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_BASE = "ainrf.harness_engine.base"
_MCP = "ainrf.harness_engine.mcp_servers"
_EXPORTS = {
    "ExecutionContext": (_BASE, "ExecutionContext"),
    "ExecutionHandle": (_BASE, "ExecutionHandle"),
    "EngineEvent": (_BASE, "EngineEvent"),
    "HarnessEngine": (_BASE, "HarnessEngine"),
    "HarnessEngineError": (_BASE, "HarnessEngineError"),
    "HarnessEngineNotSupportedError": (_BASE, "HarnessEngineNotSupportedError"),
    "HarnessEngineType": (_BASE, "HarnessEngineType"),
    "OutputEvent": (_BASE, "OutputEvent"),
    "RuntimeProbeResult": (_BASE, "RuntimeProbeResult"),
    "RuntimeProbeStatus": (_BASE, "RuntimeProbeStatus"),
    "get_engine": ("ainrf.harness_engine.engines", "get_engine"),
    "available_mcp_servers": (_MCP, "available_mcp_servers"),
    "get_active_backend_id": (_MCP, "get_active_backend_id"),
    "list_backends": (_MCP, "list_backends"),
    "load_search_settings": (_MCP, "load_search_settings"),
    "resolve_mcp_servers_for_task": (_MCP, "resolve_mcp_servers_for_task"),
    "save_search_settings": (_MCP, "save_search_settings"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())

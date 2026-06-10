"""Built-in MCP server registry.

Provides named MCP server configurations that can be referenced by name
when creating tasks.  Each built-in resolves to an MCP stdio server
config dict suitable for ``ClaudeAgentOptions.mcp_servers`` or
Claude Code's ``~/.claude.json`` / ``settings.json``.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

# TypedDict-like shape that both the SDK and JSON-serialised configs expect.
# Kept as plain dict[str, Any] to avoid importing the SDK at module level.
McpServerConfig = dict[str, Any]


def _uvx_command() -> str:
    """Return the uvx binary path, falling back to bare ``uvx``."""
    uvx = shutil.which("uvx")
    return uvx or "uvx"


def _kindly_web_search() -> McpServerConfig:
    """Build the kindly-web-search MCP server config.

    Requires one of: ``SERPER_API_KEY``, ``TAVILY_API_KEY``,
    or ``SEARXNG_BASE_URL`` in the environment.  Optional ``GITHUB_TOKEN``.
    """
    env: dict[str, str] = {}
    for key in (
        "SERPER_API_KEY",
        "TAVILY_API_KEY",
        "SEARXNG_BASE_URL",
        "SEARXNG_HEADERS_JSON",
        "SEARXNG_USER_AGENT",
        "GITHUB_TOKEN",
    ):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value

    return {
        "type": "stdio",
        "command": _uvx_command(),
        "args": [
            "--from",
            "git+https://github.com/Shelpuk-AI-Technology-Consulting/kindly-web-search-mcp-server",
            "kindly-web-search-mcp-server",
            "start-mcp-server",
        ],
        "env": env,
    }


# ── Registry ────────────────────────────────────────────────────────

_BUILT_IN_SERVERS: dict[str, McpServerConfig] = {
    "kindly-web-search": _kindly_web_search,
}


def resolve_mcp_servers(
    names: list[str] | None,
    extra: dict[str, McpServerConfig] | None = None,
) -> dict[str, McpServerConfig]:
    """Resolve MCP server names to their full configuration dicts.

    Parameters
    ----------
    names:
        List of built-in server names to enable (e.g. ``["kindly-web-search"]``).
    extra:
        Additional user-provided MCP server configs, keyed by name.
        Values are passed through verbatim.

    Returns
    -------
    dict mapping server name → config dict.
    """
    resolved: dict[str, McpServerConfig] = {}
    for name in names or []:
        factory = _BUILT_IN_SERVERS.get(name)
        if factory is not None:
            resolved[name] = factory()
        else:
            # Unknown name — skip silently so that future built-ins or
            # typos don't crash task creation.
            pass
    if extra:
        resolved.update(extra)
    return resolved


def available_mcp_servers() -> dict[str, str]:
    """Return a summary of available built-in MCP servers for API discovery."""
    return {
        "kindly-web-search": (
            "Web search + content retrieval via Serper/Tavily/SearXNG. "
            "Requires SERPER_API_KEY, TAVILY_API_KEY, or SEARXNG_BASE_URL."
        ),
    }

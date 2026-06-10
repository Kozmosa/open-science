"""Search backend registry and settings.

Manages three built-in search backends for the agent engines:

- ``native``        — Claude's built-in WebSearch/WebFetch (no MCP server needed).
- ``kindly-web-search`` — Kindly Web Search MCP server (Serper/Tavily/SearXNG).
- ``cc-web-mcp``    — CC-Web-MCP lightweight local-first search (DuckDuckGo/Bing/SearXNG).

Settings are persisted to ``<state_root>/search-settings.json`` and control
which backend is active and whether MCP servers auto-start with every task.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# TypedDict-like shape used by both claude_agent_sdk and Claude Code's
# --mcp-config JSON.  Kept as plain dict to avoid importing the SDK at
# module level.
McpServerConfig = dict[str, Any]


# ── Helpers ─────────────────────────────────────────────────────────


def _uvx_command() -> str:
    """Return the uvx binary path, falling back to bare ``uvx``."""
    return shutil.which("uvx") or "uvx"


def _python_command() -> str:
    """Return a python binary suitable for ``-m cc_web_mcp``."""
    return shutil.which("python3") or shutil.which("python") or "python3"


# ── MCP server factory functions ────────────────────────────────────


def _kindly_web_search_config() -> McpServerConfig:
    """Kindly Web Search MCP server — Serper/Tavily/SearXNG + content retrieval."""
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
            "git+https://github.com/Shelpuk-AI-Technology-Consulting/"
            "kindly-web-search-mcp-server",
            "kindly-web-search-mcp-server",
            "start-mcp-server",
        ],
        "env": env,
    }


def _cc_web_mcp_config() -> McpServerConfig:
    """CC-Web-MCP — lightweight DuckDuckGo/Bing/SearXNG web search for
    Claude Code when using third-party Anthropic-compatible models."""
    env: dict[str, str] = {}
    # Pass through optional CC-Web-MCP config env vars
    for key in ("CC_WEB_MCP_CONFIG",):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value

    return {
        "type": "stdio",
        "command": _uvx_command(),
        "args": ["cc-web-mcp"],
        "env": env,
    }


# ── Backend definitions ─────────────────────────────────────────────

BackendId = str  # Literal["native", "kindly-web-search", "cc-web-mcp"]


@dataclass(slots=True, frozen=True)
class SearchBackend:
    """Immutable descriptor for a search backend."""

    id: BackendId
    display_name: str
    description: str
    requires_mcp: bool  # True = engine must start an MCP server
    mcp_factory: McpServerConfig | None  # Non-None = callable that returns config

    def mcp_server_config(self) -> McpServerConfig | None:
        """Return the MCP server config dict, or None for native backend."""
        if self.mcp_factory is None:
            return None
        # mcp_factory is stored as the result of calling the factory
        # during registration; but we store the factory itself.
        return self.mcp_factory


# ── Registry ────────────────────────────────────────────────────────

_BACKENDS: dict[BackendId, SearchBackend] = {}


def _register(
    backend_id: BackendId,
    display_name: str,
    description: str,
    mcp_factory: Any | None = None,
) -> None:
    _BACKENDS[backend_id] = SearchBackend(
        id=backend_id,
        display_name=display_name,
        description=description,
        requires_mcp=mcp_factory is not None,
        mcp_factory=mcp_factory() if callable(mcp_factory) else mcp_factory,
    )


_register(
    "native",
    "Claude Native",
    "Use Claude's built-in WebSearch/WebFetch tools. "
    "Only works with official Anthropic models that support these tools.",
    mcp_factory=None,
)

_register(
    "kindly-web-search",
    "Kindly Web Search",
    "Web search + content retrieval via Serper, Tavily, or SearXNG. "
    "Requires SERPER_API_KEY, TAVILY_API_KEY, or SEARXNG_BASE_URL.",
    mcp_factory=_kindly_web_search_config,
)

_register(
    "cc-web-mcp",
    "CC-Web-MCP",
    "Lightweight local-first web search and fetch for third-party models. "
    "Uses DuckDuckGo, Bing, or SearXNG — no API keys required for basic use.",
    mcp_factory=_cc_web_mcp_config,
)


# ── Settings persistence ────────────────────────────────────────────

_SETTINGS_FILENAME = "search-settings.json"

_DEFAULT_ACTIVE_BACKEND: BackendId = "cc-web-mcp"
# MCP servers that should always be started alongside every task,
# regardless of the active backend.
_DEFAULT_AUTO_START_MCP_SERVERS: list[BackendId] = [
    "kindly-web-search",
    "cc-web-mcp",
]


@dataclass(slots=True)
class SearchSettings:
    """Persisted search configuration."""

    active_backend: BackendId = _DEFAULT_ACTIVE_BACKEND
    # All backends whose MCP servers should be started for every task.
    auto_start_mcp_servers: list[BackendId] = field(
        default_factory=lambda: list(_DEFAULT_AUTO_START_MCP_SERVERS),
    )

    def validate(self) -> None:
        valid_ids = set(_BACKENDS.keys())
        if self.active_backend not in valid_ids:
            raise ValueError(
                f"Unknown search backend: {self.active_backend!r}. "
                f"Available: {sorted(valid_ids)}"
            )
        for name in self.auto_start_mcp_servers:
            if name not in valid_ids:
                raise ValueError(
                    f"Unknown MCP server in auto_start: {name!r}. "
                    f"Available: {sorted(valid_ids)}"
                )


def load_search_settings(state_root: Path) -> SearchSettings:
    """Load search settings from disk, falling back to defaults."""
    path = state_root / _SETTINGS_FILENAME
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            settings = SearchSettings(
                active_backend=data.get("active_backend", _DEFAULT_ACTIVE_BACKEND),
                auto_start_mcp_servers=data.get(
                    "auto_start_mcp_servers",
                    list(_DEFAULT_AUTO_START_MCP_SERVERS),
                ),
            )
            settings.validate()
            return settings
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid search settings file %s: %s", path, exc)
    return SearchSettings()


def save_search_settings(state_root: Path, settings: SearchSettings) -> None:
    """Persist search settings to disk."""
    settings.validate()
    state_root.mkdir(parents=True, exist_ok=True)
    path = state_root / _SETTINGS_FILENAME
    path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ── Resolution helpers ──────────────────────────────────────────────


def resolve_mcp_servers_for_task(
    state_root: Path,
    user_mcp_servers: list[str] | None = None,
) -> dict[str, McpServerConfig]:
    """Build the full MCP server config dict for a task.

    Combines:
    1. Auto-start MCP servers from persisted settings.
    2. User-specified MCP server names from the task creation request.

    Returns a dict mapping server name → config dict.
    """
    settings = load_search_settings(state_root)
    resolved: dict[str, McpServerConfig] = {}

    # Auto-start servers
    for name in settings.auto_start_mcp_servers:
        backend = _BACKENDS.get(name)
        if backend is not None and backend.mcp_factory is not None:
            # Re-invoke factory to get fresh env vars
            factory_fn = _MCP_FACTORIES.get(name)
            if factory_fn is not None:
                resolved[name] = factory_fn()

    # User-specified servers (override auto-start if same name)
    for name in user_mcp_servers or []:
        factory_fn = _MCP_FACTORIES.get(name)
        if factory_fn is not None:
            resolved[name] = factory_fn()

    return resolved


def get_active_backend_id(state_root: Path) -> BackendId:
    """Return the currently configured active backend ID."""
    return load_search_settings(state_root).active_backend


def list_backends() -> list[SearchBackend]:
    """Return all registered backends, ordered by registration order."""
    return list(_BACKENDS.values())


def available_mcp_servers() -> dict[str, str]:
    """Return name → description for all MCP-capable backends."""
    return {
        bid: b.description
        for bid, b in _BACKENDS.items()
        if b.requires_mcp
    }


# Internal factory lookup (for re-invocation with fresh env)
_MCP_FACTORIES: dict[str, Any] = {
    "kindly-web-search": _kindly_web_search_config,
    "cc-web-mcp": _cc_web_mcp_config,
}

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ainrf.harness_engine.mcp_servers import (
    available_mcp_servers,
    list_backends,
    load_search_settings,
    save_search_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


# ── Codex defaults ──────────────────────────────────────────────────


class CodexDefaultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codex_config_toml: str | None = None
    codex_auth_json: str | None = None


def _read_optional_text(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


@router.get("/codex-defaults", response_model=CodexDefaultsResponse)
async def read_codex_defaults() -> CodexDefaultsResponse:
    codex_home = Path.home() / ".codex"
    return CodexDefaultsResponse(
        codex_config_toml=_read_optional_text(codex_home / "config.toml"),
        codex_auth_json=_read_optional_text(codex_home / "auth.json"),
    )


# ── Search backend settings ─────────────────────────────────────────


class SearchBackendItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str
    requires_mcp: bool


class SearchSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_backend: str
    available_backends: list[SearchBackendItem]
    auto_start_mcp_servers: list[str]


class SearchSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_backend: str | None = None
    auto_start_mcp_servers: list[str] | None = None


def _get_state_root(request: Request) -> Path:
    """Resolve state_root from the app's ApiConfig."""
    config = getattr(request.app.state, "api_config", None)
    if config is not None and hasattr(config, "state_root"):
        return config.state_root
    # Fallback: default state root
    from ainrf.state import default_state_root

    return default_state_root()


@router.get("/search", response_model=SearchSettingsResponse)
async def get_search_settings(request: Request) -> SearchSettingsResponse:
    """Get the current search backend configuration."""
    state_root = _get_state_root(request)
    settings = load_search_settings(state_root)
    backends = list_backends()
    return SearchSettingsResponse(
        active_backend=settings.active_backend,
        available_backends=[
            SearchBackendItem(
                id=b.id,
                display_name=b.display_name,
                description=b.description,
                requires_mcp=b.requires_mcp,
            )
            for b in backends
        ],
        auto_start_mcp_servers=settings.auto_start_mcp_servers,
    )


@router.patch("/search", response_model=SearchSettingsResponse)
async def update_search_settings(
    request: Request,
    payload: SearchSettingsUpdateRequest,
) -> SearchSettingsResponse:
    """Update the search backend configuration."""
    state_root = _get_state_root(request)
    settings = load_search_settings(state_root)

    if payload.active_backend is not None:
        settings.active_backend = payload.active_backend
    if payload.auto_start_mcp_servers is not None:
        settings.auto_start_mcp_servers = payload.auto_start_mcp_servers

    try:
        settings.validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    save_search_settings(state_root, settings)

    backends = list_backends()
    return SearchSettingsResponse(
        active_backend=settings.active_backend,
        available_backends=[
            SearchBackendItem(
                id=b.id,
                display_name=b.display_name,
                description=b.description,
                requires_mcp=b.requires_mcp,
            )
            for b in backends
        ],
        auto_start_mcp_servers=settings.auto_start_mcp_servers,
    )


# ── MCP server discovery (legacy, kept for compatibility) ───────────


class McpServerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str


class McpServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: list[McpServerSummary]


@router.get("/mcp-servers", response_model=McpServersResponse)
async def list_mcp_servers() -> McpServersResponse:
    """List available MCP-capable search servers."""
    servers = available_mcp_servers()
    return McpServersResponse(
        servers=[
            McpServerSummary(name=name, description=desc)
            for name, desc in servers.items()
        ],
    )

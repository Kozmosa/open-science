from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ainrf.deployment_version import resolve_deployment_version
from ainrf.harness_engine.mcp_servers import (
    available_mcp_servers,
    list_backends,
    load_search_settings,
    save_search_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# ── Codex defaults ──────────────────────────────────────────────────


class CodexDefaultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codex_config_toml: str | None = None
    codex_auth_json: str | None = None


class DeploymentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_commit: str | None = None
    committed_at: str | None = None


@router.get("/deployment-version", response_model=DeploymentVersionResponse)
async def get_deployment_version(request: Request) -> DeploymentVersionResponse:
    config = getattr(request.app.state, "api_config", None)
    startup_cwd = getattr(config, "startup_cwd", Path.cwd())
    version_info = resolve_deployment_version(startup_cwd)
    return DeploymentVersionResponse(
        short_commit=version_info.short_commit,
        committed_at=version_info.committed_at,
    )


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


# ── Monitoring / observability platform links ──────────────────────


class MonitoringServiceItem(BaseModel):
    """A configured monitoring/observability service entry point."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str
    url: str | None = None
    icon: str  # key the frontend maps to a Lucide icon


class MonitoringSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[MonitoringServiceItem]


_MONITORING_SERVICE_DEFAULTS: list[dict[str, object]] = [
    {
        "id": "grafana",
        "display_name": "Grafana",
        "description": "Metrics dashboards, alerts, and visualization",
        "icon": "grafana",
        "env_var": "AINRF_GRAFANA_URL",
    },
    {
        "id": "prometheus",
        "display_name": "Prometheus",
        "description": "Time-series metrics collection and querying",
        "icon": "prometheus",
        "env_var": "AINRF_PROMETHEUS_URL",
    },
    {
        "id": "litefuse",
        "display_name": "Litefuse",
        "description": "LLM observability: traces, generations, and token analytics",
        "icon": "litefuse",
        "env_var": "AINRF_OBSERVABILITY_BASE_URL",
    },
]


def _build_monitoring_services(request: Request) -> list[MonitoringServiceItem]:
    """Build the list of monitoring service links from environment and config."""
    config = getattr(request.app.state, "api_config", None)
    services: list[MonitoringServiceItem] = []

    for entry in _MONITORING_SERVICE_DEFAULTS:
        env_var = str(entry["env_var"])
        service_id = str(entry["id"])
        url: str | None = os.environ.get(env_var)

        # Litefuse URL may also come from the ApiConfig observability settings.
        if config is not None and service_id == "litefuse" and not url:
            url = getattr(config, "observability_base_url", None) or None

        services.append(
            MonitoringServiceItem(
                id=service_id,
                display_name=str(entry["display_name"]),
                description=str(entry["description"]),
                url=url,
                icon=str(entry["icon"]),
            )
        )

    return services


@router.get("/monitoring", response_model=MonitoringSettingsResponse)
async def get_monitoring_settings(request: Request) -> MonitoringSettingsResponse:
    """Return configured monitoring / observability platform entry points."""
    return MonitoringSettingsResponse(services=_build_monitoring_services(request))

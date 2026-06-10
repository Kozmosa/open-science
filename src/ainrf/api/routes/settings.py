from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ainrf.harness_engine.mcp_servers import available_mcp_servers

router = APIRouter(prefix="/settings", tags=["settings"])


class CodexDefaultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codex_config_toml: str | None = None
    codex_auth_json: str | None = None


class McpServerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str


class McpServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: list[McpServerSummary]


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


@router.get("/mcp-servers", response_model=McpServersResponse)
async def list_mcp_servers() -> McpServersResponse:
    """List available built-in MCP servers for task configuration."""
    servers = available_mcp_servers()
    return McpServersResponse(
        servers=[
            McpServerSummary(name=name, description=desc)
            for name, desc in servers.items()
        ],
    )
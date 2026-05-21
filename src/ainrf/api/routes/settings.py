from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/settings", tags=["settings"])


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

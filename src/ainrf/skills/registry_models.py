"""Data models for skill registry configuration and status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SkillRegistryConfig:
    """Configuration for a recommended skill registry."""

    registry_id: str
    display_name: str
    git_url: str
    git_ref: str = "main"
    source_skills_path: str = "skills"
    core_skill_ids: list[str] = field(default_factory=list)
    install_mode: str = "copy"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "display_name": self.display_name,
            "git_url": self.git_url,
            "git_ref": self.git_ref,
            "source_skills_path": self.source_skills_path,
            "core_skill_ids": self.core_skill_ids,
            "install_mode": self.install_mode,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRegistryConfig:
        return cls(
            registry_id=data["registry_id"],
            display_name=data["display_name"],
            git_url=data["git_url"],
            git_ref=data.get("git_ref", "main"),
            source_skills_path=data.get("source_skills_path", "skills"),
            core_skill_ids=data.get("core_skill_ids", []),
            install_mode=data.get("install_mode", "copy"),
            enabled=data.get("enabled", True),
        )


# Pre-configured default registries (currently ARIS only)
DEFAULT_REGISTRIES: list[SkillRegistryConfig] = [
    SkillRegistryConfig(
        registry_id="aris",
        display_name="ARIS",
        git_url="https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git",
        git_ref="main",
        source_skills_path="skills",
        core_skill_ids=[
            "research-lit",
            "arxiv",
            "semantic-scholar",
            "deepxiv",
            "openalex",
            "exa-search",
            "gemini-search",
        ],
        install_mode="copy",
        enabled=True,
    )
]


@dataclass
class SkillRegistryStatus:
    """Runtime status of an installed skill registry."""

    registry_id: str
    installed: bool = False
    installed_count: int = 0
    last_sync_at: datetime | None = None
    remote_commit: str | None = None
    local_commit: str | None = None
    has_update: bool = False
    is_dirty: bool = False
    sync_in_progress: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "installed": self.installed,
            "installed_count": self.installed_count,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "remote_commit": self.remote_commit,
            "local_commit": self.local_commit,
            "has_update": self.has_update,
            "is_dirty": self.is_dirty,
            "sync_in_progress": self.sync_in_progress,
        }

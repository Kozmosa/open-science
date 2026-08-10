from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class InjectMode(StrEnum):
    AUTO = "auto"
    PROMPT_ONLY = "prompt_only"
    DISABLED = "disabled"


@dataclass(slots=True, frozen=True)
class SkillItem:
    skill_id: str
    label: str
    description: str | None = None
    package: str | None = None


@dataclass(slots=True)
class SkillDefinition:
    skill_id: str
    label: str
    description: str | None = None
    version: str = "1.0.0"
    author: str = "ainrf"
    dependencies: list[str] = field(default_factory=list)
    inject_mode: InjectMode = InjectMode.AUTO
    package: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SkillDefinition:
        inject_mode = InjectMode(data.get("inject_mode", "auto"))
        return cls(
            skill_id=data["skill_id"],
            label=data["label"],
            description=data.get("description"),
            version=data.get("version", "1.0.0"),
            author=data.get("author", "ainrf"),
            dependencies=data.get("dependencies", []),
            inject_mode=inject_mode,
            package=data.get("package"),
        )

    def to_skill_item(self) -> SkillItem:
        return SkillItem(
            skill_id=self.skill_id,
            label=self.label,
            description=self.description,
            package=self.package,
        )


@dataclass(slots=True)
class SkillManifest:
    skills: dict[str, dict[str, list[str]]] = field(default_factory=dict)

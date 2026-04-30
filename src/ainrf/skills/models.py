from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SkillItem:
    skill_id: str
    label: str
    description: str | None = None

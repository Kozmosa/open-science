from __future__ import annotations

from pathlib import Path

from ainrf.skills.loader import SkillLoader
from ainrf.skills.models import SkillDefinition, SkillItem


class SkillsDiscoveryService:
    def __init__(self, scan_roots: list[Path] | None = None) -> None:
        self._scan_roots = scan_roots or []

    def discover(self) -> list[SkillItem]:
        """Return lightweight skill items from all scan roots.

        This is a convenience wrapper around :meth:`discover_full` that returns
        only the metadata needed for listings.  It intentionally uses the same
        scan rules so that skills returned here can always be resolved again
        via :meth:`discover_full`.
        """
        return [skill.to_skill_item() for skill in self.discover_full()]

    def discover_full(self) -> list[SkillDefinition]:
        """Return full skill definitions by scanning skill directories.

        Scans the conventional skill directory names (``.codex/skills``,
        ``.claude/skills``, ``skills``) under each scan root, then falls back
        to scanning immediate children of each root.  Deduplicates by
        ``skill_id`` — first seen wins.

        Returns empty list if no scan roots or no valid skills found.
        """
        seen: set[str] = set()
        skills: list[SkillDefinition] = []

        for root in self._scan_roots:
            if not root.is_dir():
                continue
            # Scan _SKILL_DIRS subdirectories (e.g. root/skills/)
            for skill_dir_name in (".codex/skills", ".claude/skills", "skills"):
                skill_dir = root / skill_dir_name
                if skill_dir.is_dir():
                    for skill in SkillLoader.load_all_from_root(skill_dir):
                        if skill.skill_id not in seen:
                            seen.add(skill.skill_id)
                            skills.append(skill)
            # Fallback: scan immediate children of root itself
            for skill in SkillLoader.load_all_from_root(root):
                if skill.skill_id not in seen:
                    seen.add(skill.skill_id)
                    skills.append(skill)

        return skills

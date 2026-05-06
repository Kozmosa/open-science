from __future__ import annotations

import json
from pathlib import Path

from ainrf.skills.models import SkillDefinition


class SkillLoader:
    @staticmethod
    def load_from_directory(skill_dir: Path | str) -> SkillDefinition:
        """Load a skill from a directory.

        - skill_dir must contain `skill.json` (required)
        - skill_dir must contain `SKILL.md` (required)
        - Parse skill.json with json.loads()
        - Validate that skill_id in JSON matches the directory basename
        - Return SkillDefinition.from_json(data)
        - Raise FileNotFoundError with clear message if skill.json or SKILL.md is missing
        """
        skill_dir = Path(skill_dir)
        json_path = skill_dir / "skill.json"
        md_path = skill_dir / "SKILL.md"

        if not json_path.exists():
            raise FileNotFoundError(f"skill.json not found in {skill_dir}")
        if not md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

        data = json.loads(json_path.read_text(encoding="utf-8"))
        skill_id = data.get("skill_id")
        if skill_id != skill_dir.name:
            raise ValueError(f"skill_id mismatch: expected '{skill_dir.name}', got '{skill_id}'")

        return SkillDefinition.from_json(data)

    @staticmethod
    def load_all_from_root(root: Path | str) -> list[SkillDefinition]:
        """Scan all subdirectories under root and load valid skills.

        - Only scan immediate subdirectories of root
        - Skip directories that don't have skill.json or SKILL.md (silently ignore, no error)
        - Return list of successfully loaded SkillDefinition objects
        - Return empty list if root doesn't exist or has no valid skills
        """
        root = Path(root)
        if not root.exists():
            return []

        results: list[SkillDefinition] = []
        for subdir in sorted(root.iterdir()):
            if not subdir.is_dir():
                continue
            json_path = subdir / "skill.json"
            md_path = subdir / "SKILL.md"
            if not json_path.exists() or not md_path.exists():
                continue
            try:
                skill = SkillLoader.load_from_directory(subdir)
                results.append(skill)
            except (ValueError, json.JSONDecodeError):
                continue

        return sorted(results, key=lambda s: s.skill_id)

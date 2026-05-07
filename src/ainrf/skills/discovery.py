from __future__ import annotations

import json
from pathlib import Path

from ainrf.skills.loader import SkillLoader
from ainrf.skills.models import SkillDefinition, SkillItem

_BUILTIN_SKILLS: list[SkillItem] = [
    SkillItem("web-search", "Web Search", "Search the web for information", package="aris"),
    SkillItem("code-analysis", "Code Analysis", "Analyze and understand code", package="aris"),
    SkillItem("citation", "Citation", "Manage citations and references", package="aris"),
    SkillItem("repo-inspection", "Repo Inspection", "Inspect repository structure and history", package="aris"),
    SkillItem("paper-reading", "Paper Reading", "Read and summarize academic papers", package="aris"),
    SkillItem("writing", "Academic Writing", "Write academic content", package="aris"),
]

_SKILL_DIRS = (".codex/skills", ".claude/skills", "skills")


def _scan_directory_skills(directory: Path) -> list[SkillItem]:
    skills: list[SkillItem] = []
    for skill_dir_name in _SKILL_DIRS:
        skill_dir = directory / skill_dir_name
        if not skill_dir.is_dir():
            continue
        for entry in skill_dir.iterdir():
            if entry.is_dir():
                skill_id = entry.name
                label = skill_id.replace("-", " ").replace("_", " ").title()
                manifest = entry / "skill.json"
                description: str | None = None
                package: str | None = None
                if manifest.is_file():
                    try:
                        data = json.loads(manifest.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            label = data.get("label", label)
                            description = data.get("description")
                            package = data.get("package")
                    except (json.JSONDecodeError, OSError):
                        pass
                skills.append(SkillItem(skill_id, label, description, package=package))
            elif entry.suffix == ".json" and entry.name != "skills.json":
                skill_id = entry.stem
                label = skill_id.replace("-", " ").replace("_", " ").title()
                description: str | None = None
                package: str | None = None
                try:
                    data = json.loads(entry.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        label = data.get("label", label)
                        description = data.get("description")
                        package = data.get("package")
                except (json.JSONDecodeError, OSError):
                    pass
                skills.append(SkillItem(skill_id, label, description, package=package))
    return skills


def _scan_skills_json(directory: Path) -> list[SkillItem]:
    skills: list[SkillItem] = []
    for skills_json in directory.rglob("skills.json"):
        try:
            data = json.loads(skills_json.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "skill_id" in item:
                        skills.append(
                            SkillItem(
                                skill_id=item["skill_id"],
                                label=item.get("label", item["skill_id"]),
                                description=item.get("description"),
                                package=item.get("package"),
                            )
                        )
            elif isinstance(data, dict) and "skills" in data:
                for item in data["skills"]:
                    if isinstance(item, dict) and "skill_id" in item:
                        skills.append(
                            SkillItem(
                                skill_id=item["skill_id"],
                                label=item.get("label", item["skill_id"]),
                                description=item.get("description"),
                                package=item.get("package"),
                            )
                        )
        except (json.JSONDecodeError, OSError):
            continue
    return skills


class SkillsDiscoveryService:
    def __init__(self, scan_roots: list[Path] | None = None) -> None:
        self._scan_roots = scan_roots or []

    def discover(self) -> list[SkillItem]:
        seen: set[str] = set()
        skills: list[SkillItem] = []

        for skill in _BUILTIN_SKILLS:
            if skill.skill_id not in seen:
                seen.add(skill.skill_id)
                skills.append(skill)

        for root in self._scan_roots:
            if root.is_dir():
                for skill in _scan_directory_skills(root):
                    if skill.skill_id not in seen:
                        seen.add(skill.skill_id)
                        skills.append(skill)
                for skill in _scan_skills_json(root):
                    if skill.skill_id not in seen:
                        seen.add(skill.skill_id)
                        skills.append(skill)

        return skills

    def discover_full(self) -> list[SkillDefinition]:
        """Return full skill definitions by scanning skill directories.

        Scans _SKILL_DIRS subdirectories under each scan root (same as discover()),
        then falls back to scanning immediate children of each root.
        Deduplicates by skill_id — first seen wins (same semantics as discover()).
        Returns empty list if no scan roots or no skills found.
        """
        seen: set[str] = set()
        skills: list[SkillDefinition] = []

        for root in self._scan_roots:
            if not root.is_dir():
                continue
            # Scan _SKILL_DIRS subdirectories (e.g. root/skills/)
            for skill_dir_name in _SKILL_DIRS:
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

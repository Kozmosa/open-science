from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ainrf.skills.loader import SkillLoader
from ainrf.skills.merge import deep_merge_settings, resolve_env_placeholders
from ainrf.skills.models import InjectMode, SkillDefinition
from ainrf.skills.sync import sync_ainrf_to_claude

_BASE_SETTINGS: dict[str, Any] = {
    "permissionMode": "bypassPermissions",
}


class SkillInjectionService:
    def __init__(self, skill_root: Path | str) -> None:
        self._skill_root = Path(skill_root)

    def generate_ainrf(
        self,
        workdir: Path | str,
        selected_skills: list[str],
        task_settings_override: dict[str, Any] | None = None,
    ) -> None:
        workdir = Path(workdir)
        ainrf_dir = workdir / ".ainrf"
        skills_out = ainrf_dir / "skills"
        skills_out.mkdir(parents=True, exist_ok=True)

        all_skills = SkillLoader.load_all_from_root(self._skill_root)
        skill_map = {s.skill_id: s for s in all_skills}

        resolved = self._resolve_dependencies(selected_skills, skill_map)
        active = [s for s in resolved if s.inject_mode != InjectMode.DISABLED]

        for skill in active:
            src = self._skill_root / skill.skill_id
            dst = skills_out / skill.skill_id
            shutil.copytree(src, dst, dirs_exist_ok=True)

        settings: dict[str, Any] = dict(_BASE_SETTINGS)
        for skill in active:
            if skill.inject_mode == InjectMode.AUTO:
                settings = deep_merge_settings(settings, skill.settings_fragment)

        if task_settings_override:
            settings = deep_merge_settings(settings, task_settings_override)

        settings = resolve_env_placeholders(settings)

        settings_path = ainrf_dir / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

        manifest = self._build_manifest(active)
        manifest_path = ainrf_dir / "tool-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def sync_to_claude(self, workdir: Path | str) -> None:
        workdir = Path(workdir)
        ainrf_skills = workdir / ".ainrf" / "skills"
        claude_skills = workdir / ".claude" / "skills"
        sync_ainrf_to_claude(ainrf_skills, claude_skills)
        shutil.copy2(workdir / ".ainrf" / "settings.json", workdir / ".claude" / "settings.json")

    def _resolve_dependencies(
        self,
        selected_skills: list[str],
        skill_map: dict[str, SkillDefinition],
    ) -> list[SkillDefinition]:
        result: list[SkillDefinition] = []
        added: set[str] = set()
        visited: set[str] = set()
        stack: set[str] = set()

        def visit(skill_id: str) -> None:
            if skill_id in stack:
                raise ValueError(f"circular dependency detected involving '{skill_id}'")
            if skill_id in visited:
                return
            if skill_id not in skill_map:
                raise ValueError(f"dependency '{skill_id}' not found")
            visited.add(skill_id)
            stack.add(skill_id)
            skill = skill_map[skill_id]
            for dep in skill.dependencies:
                visit(dep)
            stack.remove(skill_id)
            if skill_id not in added:
                result.append(skill)
                added.add(skill_id)

        for sid in selected_skills:
            visit(sid)
        return result

    def _build_manifest(self, active_skills: list[SkillDefinition]) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for skill in active_skills:
            scripts_dir = self._skill_root / skill.skill_id / "scripts"
            scripts: list[str] = []
            if scripts_dir.exists() and scripts_dir.is_dir():
                scripts = sorted(p.name for p in scripts_dir.iterdir() if p.is_file())
            entries.append(
                {
                    "skill_id": skill.skill_id,
                    "label": skill.label,
                    "version": skill.version,
                    "inject_mode": str(skill.inject_mode),
                    "scripts": scripts,
                    "mcp_servers": list(skill.mcp_servers),
                }
            )
        return {"skills": entries}

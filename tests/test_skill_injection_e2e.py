from __future__ import annotations

import json
from pathlib import Path

from ainrf.skills.injection import SkillInjectionService


def test_skill_injection_end_to_end(tmp_path: Path) -> None:
    """End-to-end test of the complete skill injection flow.

    1. Create a skill repository with one skill
    2. Call SkillInjectionService.generate_ainrf() and sync_to_claude()
    3. Verify .ainrf/ directory contents
    4. Verify .claude/ directory contents
    """
    # 1. Create skill repository
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "web-search"
    skill_dir.mkdir(parents=True)
    skill_json = {
        "skill_id": "web-search",
        "label": "Web Search",
        "description": "Search the web for information",
        "version": "1.0.0",
        "author": "ainrf",
        "dependencies": [],
        "inject_mode": "auto",
        "settings_fragment": {"env": {"SEARCH_API_KEY": "test-key"}},
        "mcp_servers": ["web-search-mcp"],
        "hooks": ["session-start"],
        "allowed_agents": ["claude-code"],
    }
    (skill_dir / "skill.json").write_text(json.dumps(skill_json), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Web Search\n\nSearch the web.\n", encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "search.py").write_text("#!/usr/bin/env python3\nprint('searching')\n")

    # 2. Generate .ainrf/ and sync to .claude/
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    service = SkillInjectionService(skill_root)
    service.generate_ainrf(
        workdir=workdir,
        selected_skills=["web-search"],
    )
    service.sync_to_claude(workdir=workdir)

    # 3. Verify .ainrf/ contents
    ainrf_dir = workdir / ".ainrf"
    assert ainrf_dir.is_dir()

    # Skills copied
    assert (ainrf_dir / "skills" / "web-search" / "skill.json").exists()
    assert (ainrf_dir / "skills" / "web-search" / "SKILL.md").exists()
    assert (ainrf_dir / "skills" / "web-search" / "scripts" / "search.py").exists()

    # settings.json
    settings_path = ainrf_dir / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissionMode"] == "bypassPermissions"
    assert settings["env"]["SEARCH_API_KEY"] == "test-key"

    # tool-manifest.json
    manifest_path = ainrf_dir / "tool-manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["skills"]) == 1
    assert manifest["skills"][0]["skill_id"] == "web-search"
    assert manifest["skills"][0]["scripts"] == ["search.py"]
    assert manifest["skills"][0]["mcp_servers"] == ["web-search-mcp"]

    # 4. Verify .claude/ contents
    claude_dir = workdir / ".claude"
    assert claude_dir.is_dir()

    # .ainrf-managed marker
    marker = claude_dir / ".ainrf-managed"
    assert marker.exists()
    assert "managed by ainrf" in marker.read_text(encoding="utf-8")

    # skills symlink or directory exists
    claude_skills = claude_dir / "skills"
    assert claude_skills.exists()
    assert (claude_skills / "web-search" / "skill.json").exists()

    # settings.json copied
    assert (claude_dir / "settings.json").exists()
    claude_settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert claude_settings["env"]["SEARCH_API_KEY"] == "test-key"

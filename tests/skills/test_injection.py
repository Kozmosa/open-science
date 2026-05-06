from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.skills.injection import SkillInjectionService


def _make_skill(
    root: Path,
    skill_id: str,
    label: str,
    inject_mode: str = "auto",
    dependencies: list[str] | None = None,
    settings_fragment: dict | None = None,
    mcp_servers: list[str] | None = None,
    scripts: list[str] | None = None,
) -> None:
    """Create a skill directory under root with skill.json and SKILL.md."""
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "skill_id": skill_id,
        "label": label,
        "inject_mode": inject_mode,
    }
    if dependencies is not None:
        data["dependencies"] = dependencies
    if settings_fragment is not None:
        data["settings_fragment"] = settings_fragment
    if mcp_servers is not None:
        data["mcp_servers"] = mcp_servers
    (skill_dir / "skill.json").write_text(json.dumps(data), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {label}\n", encoding="utf-8")
    if scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        for script in scripts:
            (scripts_dir / script).write_text("# script\n", encoding="utf-8")


def test_generate_ainrf_creates_directories(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(skill_root, "skill-a", "Skill A")
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-a"])
    assert (workdir / ".ainrf" / "skills" / "skill-a" / "skill.json").exists()
    assert (workdir / ".ainrf" / "skills" / "skill-a" / "SKILL.md").exists()


def test_generate_ainrf_merges_settings(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(
        skill_root,
        "skill-merge",
        "Skill Merge",
        settings_fragment={"foo": {"bar": 1}},
    )
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-merge"])
    settings = json.loads((workdir / ".ainrf" / "settings.json").read_text(encoding="utf-8"))
    assert settings["foo"]["bar"] == 1
    assert settings["permissionMode"] == "bypassPermissions"


def test_generate_ainrf_respects_task_override(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(
        skill_root,
        "skill-override",
        "Skill Override",
        settings_fragment={"foo": {"bar": 1}},
    )
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(
        workdir,
        ["skill-override"],
        task_settings_override={"foo": {"bar": 42}},
    )
    settings = json.loads((workdir / ".ainrf" / "settings.json").read_text(encoding="utf-8"))
    assert settings["foo"]["bar"] == 42


def test_generate_ainrf_prompt_only_filtered(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(
        skill_root,
        "skill-prompt",
        "Skill Prompt",
        inject_mode="prompt_only",
        settings_fragment={"foo": {"bar": 1}},
    )
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-prompt"])
    assert (workdir / ".ainrf" / "skills" / "skill-prompt").exists()
    settings = json.loads((workdir / ".ainrf" / "settings.json").read_text(encoding="utf-8"))
    assert "foo" not in settings


def test_generate_ainrf_disabled_skipped(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(
        skill_root,
        "skill-disabled",
        "Skill Disabled",
        inject_mode="disabled",
    )
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-disabled"])
    assert not (workdir / ".ainrf" / "skills" / "skill-disabled").exists()


def test_generate_ainrf_resolves_dependencies(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(skill_root, "skill-b", "Skill B")
    _make_skill(skill_root, "skill-a", "Skill A", dependencies=["skill-b"])
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-a"])
    assert (workdir / ".ainrf" / "skills" / "skill-a").exists()
    assert (workdir / ".ainrf" / "skills" / "skill-b").exists()
    manifest = json.loads((workdir / ".ainrf" / "tool-manifest.json").read_text(encoding="utf-8"))
    ids = [s["skill_id"] for s in manifest["skills"]]
    assert ids == ["skill-b", "skill-a"]


def test_generate_ainrf_circular_dependency_raises(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(skill_root, "skill-a", "Skill A", dependencies=["skill-b"])
    _make_skill(skill_root, "skill-b", "Skill B", dependencies=["skill-a"])
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    with pytest.raises(ValueError, match="circular dependency"):
        svc.generate_ainrf(workdir, ["skill-a"])


def test_generate_ainrf_missing_dependency_raises(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(skill_root, "skill-a", "Skill A", dependencies=["skill-z"])
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    with pytest.raises(ValueError, match="dependency.*skill-z"):
        svc.generate_ainrf(workdir, ["skill-a"])


def test_generate_ainrf_tool_manifest(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(
        skill_root,
        "skill-manifest",
        "Skill Manifest",
        inject_mode="auto",
        mcp_servers=["mcp1"],
        scripts=["script1.py", "script2.py"],
    )
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-manifest"])
    manifest = json.loads((workdir / ".ainrf" / "tool-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["skills"]) == 1
    entry = manifest["skills"][0]
    assert entry["skill_id"] == "skill-manifest"
    assert entry["label"] == "Skill Manifest"
    assert entry["version"] == "1.0.0"
    assert entry["inject_mode"] == "auto"
    assert entry["scripts"] == ["script1.py", "script2.py"]
    assert entry["mcp_servers"] == ["mcp1"]


def test_sync_to_claude(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    _make_skill(skill_root, "skill-sync", "Skill Sync")
    svc = SkillInjectionService(skill_root)
    workdir = tmp_path / "workdir"
    svc.generate_ainrf(workdir, ["skill-sync"])
    svc.sync_to_claude(workdir)
    claude_skills = workdir / ".claude" / "skills"
    assert claude_skills.exists()
    assert (workdir / ".claude" / "settings.json").exists()
    assert (claude_skills / "skill-sync" / "skill.json").exists()

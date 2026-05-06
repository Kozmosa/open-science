from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.skills.loader import SkillLoader
from ainrf.skills.models import InjectMode, SkillDefinition


def test_load_from_directory_success(tmp_path: Path) -> None:
    """Load a valid skill directory with skill.json and SKILL.md."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()

    skill_data = {
        "skill_id": "my-skill",
        "label": "My Skill",
        "description": "A test skill",
        "version": "1.2.3",
        "author": "tester",
        "dependencies": ["dep1", "dep2"],
        "inject_mode": "prompt_only",
        "settings_fragment": {"key": "value"},
        "mcp_servers": ["server1"],
        "hooks": ["hook1"],
        "allowed_agents": ["agent1"],
    }
    (skill_dir / "skill.json").write_text(json.dumps(skill_data))
    (skill_dir / "SKILL.md").write_text("# My Skill\n\nThis is my skill.\n")

    result = SkillLoader.load_from_directory(skill_dir)

    assert isinstance(result, SkillDefinition)
    assert result.skill_id == "my-skill"
    assert result.label == "My Skill"
    assert result.description == "A test skill"
    assert result.version == "1.2.3"
    assert result.author == "tester"
    assert result.dependencies == ["dep1", "dep2"]
    assert result.inject_mode == InjectMode.PROMPT_ONLY
    assert result.settings_fragment == {"key": "value"}
    assert result.mcp_servers == ["server1"]
    assert result.hooks == ["hook1"]
    assert result.allowed_agents == ["agent1"]


def test_load_from_directory_missing_json(tmp_path: Path) -> None:
    """Raise FileNotFoundError when skill.json is missing."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# My Skill\n")

    with pytest.raises(FileNotFoundError, match="skill.json not found"):
        SkillLoader.load_from_directory(skill_dir)


def test_load_from_directory_missing_skill_md(tmp_path: Path) -> None:
    """Raise FileNotFoundError when SKILL.md is missing."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "skill.json").write_text(json.dumps({"skill_id": "my-skill", "label": "My Skill"}))

    with pytest.raises(FileNotFoundError, match="SKILL.md not found"):
        SkillLoader.load_from_directory(skill_dir)


def test_load_from_directory_mismatched_skill_id(tmp_path: Path) -> None:
    """Raise ValueError when directory name doesn't match skill_id."""
    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    skill_data = {"skill_id": "bar", "label": "Bar Skill"}
    (skill_dir / "skill.json").write_text(json.dumps(skill_data))
    (skill_dir / "SKILL.md").write_text("# Bar Skill\n")

    with pytest.raises(ValueError, match="skill_id"):
        SkillLoader.load_from_directory(skill_dir)


def test_load_all_from_root(tmp_path: Path) -> None:
    """Load only valid skills from root, sorted by skill_id."""
    # Valid skill 1
    skill_a_dir = tmp_path / "skill-a"
    skill_a_dir.mkdir()
    (skill_a_dir / "skill.json").write_text(json.dumps({"skill_id": "skill-a", "label": "Skill A"}))
    (skill_a_dir / "SKILL.md").write_text("# Skill A\n")

    # Valid skill 2
    skill_b_dir = tmp_path / "skill-b"
    skill_b_dir.mkdir()
    (skill_b_dir / "skill.json").write_text(json.dumps({"skill_id": "skill-b", "label": "Skill B"}))
    (skill_b_dir / "SKILL.md").write_text("# Skill B\n")

    # Invalid skill — missing SKILL.md
    invalid_dir = tmp_path / "invalid-skill"
    invalid_dir.mkdir()
    (invalid_dir / "skill.json").write_text(
        json.dumps({"skill_id": "invalid-skill", "label": "Invalid"})
    )

    results = SkillLoader.load_all_from_root(tmp_path)

    assert len(results) == 2
    assert [r.skill_id for r in results] == ["skill-a", "skill-b"]


def test_load_all_from_root_empty(tmp_path: Path) -> None:
    """Return empty list for an empty directory."""
    results = SkillLoader.load_all_from_root(tmp_path)
    assert results == []


def test_load_all_from_root_nonexistent() -> None:
    """Return empty list for a non-existent path."""
    results = SkillLoader.load_all_from_root(Path("/nonexistent/path/12345"))
    assert results == []

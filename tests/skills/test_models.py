from __future__ import annotations

from ainrf.skills.models import InjectMode, SkillDefinition, SkillItem, SkillManifest


def test_inject_mode_values():
    assert InjectMode.AUTO == "auto"
    assert InjectMode.PROMPT_ONLY == "prompt_only"
    assert InjectMode.DISABLED == "disabled"


def test_skill_definition_from_json():
    data = {
        "skill_id": "test-skill",
        "label": "Test Skill",
        "description": "A test skill",
        "version": "2.0.0",
        "author": "tester",
        "dependencies": ["dep1", "dep2"],
        "inject_mode": "prompt_only",
        "settings_fragment": {"key": "value"},
        "mcp_servers": ["server1"],
        "hooks": ["hook1"],
        "allowed_agents": ["claude-code", "custom-agent"],
    }
    skill = SkillDefinition.from_json(data)
    assert skill.skill_id == "test-skill"
    assert skill.label == "Test Skill"
    assert skill.description == "A test skill"
    assert skill.version == "2.0.0"
    assert skill.author == "tester"
    assert skill.dependencies == ["dep1", "dep2"]
    assert skill.inject_mode == InjectMode.PROMPT_ONLY
    assert skill.settings_fragment == {"key": "value"}
    assert skill.mcp_servers == ["server1"]
    assert skill.hooks == ["hook1"]
    assert skill.allowed_agents == ["claude-code", "custom-agent"]

    item = skill.to_skill_item()
    assert isinstance(item, SkillItem)
    assert item.skill_id == "test-skill"
    assert item.label == "Test Skill"
    assert item.description == "A test skill"


def test_skill_manifest_tools():
    manifest = SkillManifest()
    assert manifest.skills == {}

    manifest.skills["category1"] = {"sub": ["skill1", "skill2"]}
    assert manifest.skills["category1"]["sub"] == ["skill1", "skill2"]

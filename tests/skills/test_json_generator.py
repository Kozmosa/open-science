from __future__ import annotations


from ainrf.skills.json_generator import generate_skill_json, parse_skill_md_frontmatter


class TestParseSkillMdFrontmatter:
    def test_parses_valid_frontmatter(self):
        content = """---
name: idea-discovery
description: "Workflow 1: Full idea discovery pipeline."
argument-hint: [research-direction]
allowed-tools: Bash(*), Read
---

# Workflow 1: Idea Discovery Pipeline

Research topic: $ARGUMENTS
"""
        result = parse_skill_md_frontmatter(content)
        assert result == {
            "name": "idea-discovery",
            "description": "Workflow 1: Full idea discovery pipeline.",
            "argument-hint": ["research-direction"],
            "allowed-tools": "Bash(*), Read",
        }

    def test_returns_empty_dict_when_no_frontmatter(self):
        content = "# Just a heading\n\nSome content."
        result = parse_skill_md_frontmatter(content)
        assert result == {}

    def test_returns_empty_dict_when_empty_frontmatter(self):
        content = "---\n---\n\n# Heading"
        result = parse_skill_md_frontmatter(content)
        assert result == {}


class TestGenerateSkillJson:
    def test_generates_skill_json_with_defaults(self):
        frontmatter = {
            "name": "idea-discovery",
            "description": "A description.",
        }
        result = generate_skill_json("idea-discovery", frontmatter, is_core=False)
        assert result == {
            "skill_id": "idea-discovery",
            "label": "idea-discovery",
            "description": "A description.",
            "version": "0.0.0",
            "author": "ARIS",
            "inject_mode": "disabled",
            "dependencies": [],
            "settings_fragment": {},
            "mcp_servers": [],
            "hooks": [],
            "allowed_agents": [],
        }

    def test_core_skill_uses_auto_inject_mode(self):
        frontmatter = {"name": "research-lit"}
        result = generate_skill_json("research-lit", frontmatter, is_core=True)
        assert result["inject_mode"] == "auto"

    def test_uses_directory_name_when_no_name_in_frontmatter(self):
        frontmatter = {"description": "Just a description."}
        result = generate_skill_json("my-skill", frontmatter, is_core=False)
        assert result["skill_id"] == "my-skill"
        assert result["label"] == "my-skill"

    def test_description_defaults_to_empty_string(self):
        frontmatter = {"name": "test"}
        result = generate_skill_json("test", frontmatter, is_core=False)
        assert result["description"] == ""

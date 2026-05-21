from __future__ import annotations

from datetime import UTC, datetime

from ainrf.environments.models import EnvironmentAuthKind, EnvironmentRegistryEntry
from ainrf.task_harness.models import ResearchAgentProfileSnapshot
from ainrf.task_harness.prompting import compose_skill_prompt_lines, compose_task_prompt
from ainrf.workspaces.models import WorkspaceRecord


def test_compose_skill_prompt_lines_with_skills_and_prompt():
    result = compose_skill_prompt_lines(skills=["a", "b"], skills_prompt="Custom prompt")
    assert result == ["Enabled skills: a, b", "Custom prompt"]


def test_compose_skill_prompt_lines_skills_only():
    result = compose_skill_prompt_lines(skills=["a"], skills_prompt=None)
    assert result == ["Enabled skills: a"]


def test_compose_skill_prompt_lines_prompt_only():
    result = compose_skill_prompt_lines(skills=[], skills_prompt="Custom")
    assert result == ["Custom"]


def test_compose_skill_prompt_lines_empty():
    result = compose_skill_prompt_lines(skills=[], skills_prompt=None)
    assert result == []


def test_compose_skill_prompt_lines_strips_prompt():
    result = compose_skill_prompt_lines(skills=[], skills_prompt="  padded  ")
    assert result == ["padded"]


def test_compose_task_prompt_includes_skills_layer():
    now = datetime.now(UTC)
    workspace = WorkspaceRecord(
        workspace_id="ws-1",
        project_id="p-1",
        label="Test Workspace",
        description=None,
        default_workdir=None,
        workspace_prompt="Workspace prompt content",
        created_at=now,
        updated_at=now,
    )
    environment = EnvironmentRegistryEntry(
        id="env-1",
        alias="test-env",
        display_name="Test Environment",
        description=None,
        is_seed=False,
        tags=[],
        host="localhost",
        port=22,
        user="root",
        auth_kind=EnvironmentAuthKind.SSH_KEY,
        identity_file=None,
        proxy_jump=None,
        proxy_command=None,
        ssh_options={},
        default_workdir=None,
        preferred_python=None,
        preferred_env_manager=None,
        preferred_runtime_notes=None,
        task_harness_profile="Environment harness profile",
        code_server_path=None,
        created_at=now,
        updated_at=now,
    )
    research_agent_profile = ResearchAgentProfileSnapshot(
        profile_id="rp-1",
        label="Test Profile",
        system_prompt="System prompt",
        skills=["skill-a", "skill-b"],
        skills_prompt="Custom skills prompt",
        settings_json=None,
        settings_artifact_path=None,
    )

    composition = compose_task_prompt(
        workspace=workspace,
        environment=environment,
        task_profile="claude-code",
        task_input="Do something",
        research_agent_profile=research_agent_profile,
    )

    assert "Enabled skills: skill-a, skill-b" in composition.rendered_prompt
    assert "Custom skills prompt" in composition.rendered_prompt
    assert "research_agent_skills" in composition.layer_order

    skills_layer = next(
        layer for layer in composition.layers if layer.name == "research_agent_skills"
    )
    assert "Enabled skills: skill-a, skill-b" in skills_layer.content
    assert "Custom skills prompt" in skills_layer.content

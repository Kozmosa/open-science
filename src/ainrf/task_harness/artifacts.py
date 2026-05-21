from __future__ import annotations

import shutil
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.task_harness.models import (
    EnvironmentSummary,
    ResearchAgentProfileSnapshot,
    TaskBindingSummary,
    TaskConfigurationMode,
    TaskConfigurationSnapshot,
    TaskPromptLayer,
    TaskPromptSummary,
    TaskRuntimeSummary,
    WorkspaceSummary,
)
from ainrf.task_harness.prompting import compose_task_prompt
from ainrf.workspaces.models import WorkspaceRecord

if TYPE_CHECKING:
    from ainrf.task_harness.launcher import LaunchPayload


BINDING_SNAPSHOT_FILENAME = "binding_snapshot.json"
PROMPT_MANIFEST_FILENAME = "prompt_layer_manifest.json"
RENDERED_PROMPT_FILENAME = "rendered_prompt.txt"
LAUNCH_PAYLOAD_FILENAME = "resolved_launch_payload.json"
TASK_CONFIG_SNAPSHOT_FILENAME = "task_configuration_snapshot.json"
RESEARCH_AGENT_PROFILE_FILENAME = "research_agent_profile.json"
CLAUDE_SETTINGS_FILENAME = "claude-settings.json"
REMOTE_LAUNCH_FILENAME = "remote-launch.sh"
CODEX_HOME_DIRNAME = "codex-home"
CODEX_CONFIG_FILENAME = "config.toml"
CODEX_AUTH_FILENAME = "auth.json"
DEFAULT_EXECUTION_ENGINE = "claude-code"

DEFAULT_RESEARCH_AGENT_PROFILE = ResearchAgentProfileSnapshot(
    profile_id="claude-code-default",
    label="Claude Code Default",
    system_prompt=None,
    skills=[],
    skills_prompt=None,
    settings_json=None,
    settings_artifact_path=None,
)


def binding_snapshot_path(task_dir: Path) -> Path:
    return task_dir / BINDING_SNAPSHOT_FILENAME


def prompt_manifest_path(task_dir: Path) -> Path:
    return task_dir / PROMPT_MANIFEST_FILENAME


def rendered_prompt_path(task_dir: Path) -> Path:
    return task_dir / RENDERED_PROMPT_FILENAME


def launch_payload_path(task_dir: Path) -> Path:
    return task_dir / LAUNCH_PAYLOAD_FILENAME


def task_configuration_snapshot_path(task_dir: Path) -> Path:
    return task_dir / TASK_CONFIG_SNAPSHOT_FILENAME


def research_agent_profile_path(task_dir: Path) -> Path:
    return task_dir / RESEARCH_AGENT_PROFILE_FILENAME


def claude_settings_path(task_dir: Path) -> Path:
    return task_dir / CLAUDE_SETTINGS_FILENAME


def remote_launch_path(task_dir: Path) -> Path:
    return task_dir / REMOTE_LAUNCH_FILENAME


def codex_home_path(task_dir: Path) -> Path:
    return task_dir / CODEX_HOME_DIRNAME


def codex_config_path(task_dir: Path) -> Path:
    return codex_home_path(task_dir) / CODEX_CONFIG_FILENAME


def codex_auth_path(task_dir: Path) -> Path:
    return codex_home_path(task_dir) / CODEX_AUTH_FILENAME


def write_binding_snapshot(
    path: Path,
    *,
    workspace: WorkspaceRecord,
    environment: EnvironmentRegistryEntry,
    task_profile: str,
    title: str,
    task_input: str,
    resolved_workdir: str,
    execution_engine: str = DEFAULT_EXECUTION_ENGINE,
    research_agent_profile: ResearchAgentProfileSnapshot | None = None,
    task_configuration: TaskConfigurationSnapshot | None = None,
) -> TaskBindingSummary:
    profile = research_agent_profile or DEFAULT_RESEARCH_AGENT_PROFILE
    configuration = task_configuration or raw_prompt_configuration(task_input)
    binding = TaskBindingSummary(
        workspace=_workspace_summary(workspace),
        environment=_environment_summary(environment),
        task_profile=task_profile,
        title=title,
        task_input=task_input,
        resolved_workdir=resolved_workdir,
        snapshot_path=str(path),
        execution_engine=execution_engine,
        research_agent_profile=profile,
        task_configuration=configuration,
    )
    write_json(path, binding_snapshot_payload(binding, workspace, environment))
    return binding


def write_prompt_artifacts(
    task_dir: Path,
    manifest_path: Path,
    *,
    workspace: WorkspaceRecord,
    environment: EnvironmentRegistryEntry,
    task_profile: str,
    task_input: str,
    research_agent_profile: ResearchAgentProfileSnapshot | None = None,
) -> tuple[Path, TaskPromptSummary]:
    prompt_composition = compose_task_prompt(
        workspace=workspace,
        environment=environment,
        task_profile=task_profile,
        task_input=task_input,
        research_agent_profile=research_agent_profile,
    )
    prompt_file = rendered_prompt_path(task_dir)
    prompt_file.write_text(prompt_composition.rendered_prompt, encoding="utf-8")
    payload = {
        "rendered_prompt": prompt_composition.rendered_prompt,
        "layer_order": prompt_composition.layer_order,
        "layers": [asdict(layer) for layer in prompt_composition.layers],
        "manifest_path": str(manifest_path),
    }
    write_json(manifest_path, payload)
    return prompt_file, prompt_summary_from_payload(payload)


def write_launch_payload(path: Path, payload: LaunchPayload) -> None:
    write_json(path, asdict(payload))


def write_task_configuration_snapshot(
    path: Path, task_configuration: TaskConfigurationSnapshot
) -> None:
    write_json(path, task_configuration_payload(task_configuration))


def write_research_agent_profile_snapshot(
    path: Path, research_agent_profile: ResearchAgentProfileSnapshot
) -> None:
    write_json(path, research_agent_profile_payload(research_agent_profile))


def write_claude_settings_artifact(
    path: Path,
    settings_json: dict[str, object] | None,
) -> str | None:
    if settings_json is None:
        return None
    write_json(path, settings_json)
    return str(path)


def prepare_codex_home_artifact(
    task_dir: Path,
    *,
    profile: ResearchAgentProfileSnapshot,
    source_home: Path | None = None,
) -> str:
    source = source_home or (Path.home() / ".codex")
    target = codex_home_path(task_dir)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    source_config = source / CODEX_CONFIG_FILENAME
    if source_config.exists() and source_config.is_file():
        shutil.copy2(source_config, codex_config_path(task_dir))
    source_auth = source / CODEX_AUTH_FILENAME
    if source_auth.exists() and source_auth.is_file():
        shutil.copy2(source_auth, codex_auth_path(task_dir))
    if profile.codex_config_toml is not None:
        config_path = codex_config_path(task_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(profile.codex_config_toml, encoding="utf-8")
    if profile.codex_auth_json is not None:
        auth_path = codex_auth_path(task_dir)
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_text(profile.codex_auth_json, encoding="utf-8")
    return str(target)


def read_binding_summary(snapshot_path: str) -> TaskBindingSummary | None:
    path = Path(snapshot_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TaskBindingSummary(
        workspace=workspace_summary_from_json(dump_json(payload["workspace"])),
        environment=environment_summary_from_json(dump_json(payload["environment"])),
        task_profile=str(payload["task_profile"]),
        title=str(payload["title"]),
        task_input=str(payload["task_input"]),
        resolved_workdir=str(payload["resolved_workdir"]),
        snapshot_path=str(payload["snapshot_path"]),
        execution_engine=str(payload.get("execution_engine", DEFAULT_EXECUTION_ENGINE)),
        research_agent_profile=research_agent_profile_from_payload(
            payload.get(
                "research_agent_profile",
                research_agent_profile_payload(DEFAULT_RESEARCH_AGENT_PROFILE),
            )
        ),
        task_configuration=task_configuration_from_payload(
            payload.get(
                "task_configuration",
                task_configuration_payload(raw_prompt_configuration(str(payload["task_input"]))),
            )
        ),
    )


def read_prompt_summary(manifest_path: str) -> TaskPromptSummary | None:
    path = Path(manifest_path)
    if not path.exists():
        return None
    return prompt_summary_from_payload(json.loads(path.read_text(encoding="utf-8")))


def read_runtime_summary(launch_payload_path: str) -> TaskRuntimeSummary | None:
    path = Path(launch_payload_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TaskRuntimeSummary(
        runner_kind=payload.get("runner_kind"),
        working_directory=payload.get("working_directory"),
        command=[str(item) for item in payload.get("command", [])],
        prompt_file=payload.get("prompt_file"),
        helper_path=payload.get("helper_path"),
        launch_payload_path=payload.get("launch_payload_path"),
        codex_home=payload.get("codex_home"),
    )


def read_task_configuration_snapshot(snapshot_path: str) -> TaskConfigurationSnapshot | None:
    path = Path(snapshot_path)
    if not path.exists():
        return None
    return task_configuration_from_payload(json.loads(path.read_text(encoding="utf-8")))


def read_research_agent_profile_snapshot(snapshot_path: str) -> ResearchAgentProfileSnapshot | None:
    path = Path(snapshot_path)
    if not path.exists():
        return None
    return research_agent_profile_from_payload(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def prompt_summary_from_payload(payload: dict[str, Any]) -> TaskPromptSummary:
    return TaskPromptSummary(
        rendered_prompt=str(payload["rendered_prompt"]),
        layer_order=[str(item) for item in payload["layer_order"]],
        layers=[
            TaskPromptLayer(
                position=int(item["position"]),
                name=str(item["name"]),
                label=str(item["label"]),
                content=str(item["content"]),
                char_count=int(item["char_count"]),
            )
            for item in payload["layers"]
        ],
        manifest_path=str(payload["manifest_path"]),
    )


def raw_prompt_configuration(task_input: str) -> TaskConfigurationSnapshot:
    return TaskConfigurationSnapshot(
        mode=TaskConfigurationMode.RAW_PROMPT,
        template_id=None,
        template_vars={},
        raw_prompt=task_input,
        rendered_task_input=task_input,
    )


def task_configuration_payload(configuration: TaskConfigurationSnapshot) -> dict[str, Any]:
    return {
        "mode": configuration.mode.value,
        "template_id": configuration.template_id,
        "template_vars": configuration.template_vars,
        "raw_prompt": configuration.raw_prompt,
        "rendered_task_input": configuration.rendered_task_input,
    }


def task_configuration_from_payload(payload: dict[str, Any]) -> TaskConfigurationSnapshot:
    return TaskConfigurationSnapshot(
        mode=TaskConfigurationMode(str(payload["mode"])),
        template_id=payload.get("template_id"),
        template_vars=dict(payload.get("template_vars", {})),
        raw_prompt=payload.get("raw_prompt"),
        rendered_task_input=str(payload["rendered_task_input"]),
    )


def research_agent_profile_payload(profile: ResearchAgentProfileSnapshot) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "system_prompt": profile.system_prompt,
        "skills": profile.skills,
        "skills_prompt": profile.skills_prompt,
        "settings_json": profile.settings_json,
        "settings_artifact_path": profile.settings_artifact_path,
    }
    if profile.model is not None:
        payload["model"] = profile.model
    if profile.permission_mode is not None:
        payload["permission_mode"] = profile.permission_mode
    if profile.max_turns is not None:
        payload["max_turns"] = profile.max_turns
    if profile.max_budget_usd is not None:
        payload["max_budget_usd"] = profile.max_budget_usd
    if profile.mcp_servers is not None:
        payload["mcp_servers"] = profile.mcp_servers
    if profile.disallowed_tools is not None:
        payload["disallowed_tools"] = profile.disallowed_tools
    if profile.api_base_url is not None:
        payload["api_base_url"] = profile.api_base_url
    if profile.api_key is not None:
        payload["api_key"] = profile.api_key
    if profile.default_opus_model is not None:
        payload["default_opus_model"] = profile.default_opus_model
    if profile.default_sonnet_model is not None:
        payload["default_sonnet_model"] = profile.default_sonnet_model
    if profile.default_haiku_model is not None:
        payload["default_haiku_model"] = profile.default_haiku_model
    if profile.env_overrides is not None:
        payload["env_overrides"] = profile.env_overrides
    if profile.codex_base_url is not None:
        payload["codex_base_url"] = profile.codex_base_url
    if profile.codex_api_key is not None:
        payload["codex_api_key"] = profile.codex_api_key
    if profile.codex_model is not None:
        payload["codex_model"] = profile.codex_model
    if profile.codex_app_server_command is not None:
        payload["codex_app_server_command"] = profile.codex_app_server_command
    if profile.codex_approval_policy is not None:
        payload["codex_approval_policy"] = profile.codex_approval_policy
    if profile.codex_config_toml is not None:
        payload["codex_config_toml"] = profile.codex_config_toml
    if profile.codex_auth_json is not None:
        payload["codex_auth_json"] = profile.codex_auth_json
    return payload


def research_agent_profile_from_payload(payload: dict[str, Any]) -> ResearchAgentProfileSnapshot:
    settings_json = payload.get("settings_json")
    skills_raw = payload.get("skills", [])
    skills = [str(s) for s in skills_raw] if isinstance(skills_raw, list) else []
    env_overrides = payload.get("env_overrides")
    return ResearchAgentProfileSnapshot(
        profile_id=str(payload["profile_id"]),
        label=str(payload["label"]),
        system_prompt=payload.get("system_prompt"),
        skills=skills,
        skills_prompt=payload.get("skills_prompt"),
        settings_json=dict(settings_json) if isinstance(settings_json, dict) else None,
        settings_artifact_path=payload.get("settings_artifact_path"),
        model=payload.get("model"),
        permission_mode=payload.get("permission_mode"),
        max_turns=payload.get("max_turns"),
        max_budget_usd=payload.get("max_budget_usd"),
        mcp_servers=payload.get("mcp_servers"),
        disallowed_tools=payload.get("disallowed_tools"),
        api_base_url=payload.get("api_base_url"),
        api_key=payload.get("api_key"),
        default_opus_model=payload.get("default_opus_model"),
        default_sonnet_model=payload.get("default_sonnet_model"),
        default_haiku_model=payload.get("default_haiku_model"),
        env_overrides=dict(env_overrides) if isinstance(env_overrides, dict) else None,
        codex_base_url=payload.get("codex_base_url"),
        codex_api_key=payload.get("codex_api_key"),
        codex_model=payload.get("codex_model"),
        codex_app_server_command=payload.get("codex_app_server_command"),
        codex_approval_policy=payload.get("codex_approval_policy"),
        codex_config_toml=payload.get("codex_config_toml"),
        codex_auth_json=payload.get("codex_auth_json"),
    )


def workspace_summary(workspace: WorkspaceRecord) -> WorkspaceSummary:
    return _workspace_summary(workspace)


def environment_summary(environment: EnvironmentRegistryEntry) -> EnvironmentSummary:
    return _environment_summary(environment)


def workspace_summary_from_json(value: str) -> WorkspaceSummary:
    payload = json.loads(value)
    return WorkspaceSummary(
        workspace_id=str(payload["workspace_id"]),
        project_id=str(payload.get("project_id", "default")),
        label=str(payload["label"]),
        description=payload.get("description"),
        default_workdir=payload.get("default_workdir"),
    )


def environment_summary_from_json(value: str) -> EnvironmentSummary:
    payload = json.loads(value)
    return EnvironmentSummary(
        environment_id=str(payload["environment_id"]),
        alias=str(payload["alias"]),
        display_name=str(payload["display_name"]),
        host=str(payload["host"]),
        default_workdir=payload.get("default_workdir"),
    )


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def binding_snapshot_payload(
    binding: TaskBindingSummary,
    workspace: WorkspaceRecord,
    environment: EnvironmentRegistryEntry,
) -> dict[str, Any]:
    return {
        "workspace": {
            **asdict(binding.workspace),
            "workspace_prompt": workspace.workspace_prompt,
            "created_at": workspace.created_at.isoformat(),
            "updated_at": workspace.updated_at.isoformat(),
        },
        "environment": {
            **asdict(binding.environment),
            "task_harness_profile": environment.task_harness_profile,
            "created_at": environment.created_at.isoformat()
            if environment.created_at is not None
            else None,
            "updated_at": environment.updated_at.isoformat()
            if environment.updated_at is not None
            else None,
        },
        "task_profile": binding.task_profile,
        "title": binding.title,
        "task_input": binding.task_input,
        "resolved_workdir": binding.resolved_workdir,
        "snapshot_path": binding.snapshot_path,
        "execution_engine": binding.execution_engine,
        "research_agent_profile": research_agent_profile_payload(binding.research_agent_profile),
        "task_configuration": task_configuration_payload(binding.task_configuration),
    }


def _workspace_summary(workspace: WorkspaceRecord) -> WorkspaceSummary:
    return WorkspaceSummary(
        workspace_id=workspace.workspace_id,
        project_id=workspace.project_id,
        label=workspace.label,
        description=workspace.description,
        default_workdir=workspace.default_workdir,
    )


def _environment_summary(environment: EnvironmentRegistryEntry) -> EnvironmentSummary:
    return EnvironmentSummary(
        environment_id=environment.id,
        alias=environment.alias,
        display_name=environment.display_name,
        host=environment.host,
        default_workdir=environment.default_workdir,
    )

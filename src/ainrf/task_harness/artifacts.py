from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.task_harness.models import (
    EnvironmentSummary,
    TaskBindingSummary,
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
REMOTE_LAUNCH_FILENAME = "remote-launch.sh"


def binding_snapshot_path(task_dir: Path) -> Path:
    return task_dir / BINDING_SNAPSHOT_FILENAME


def prompt_manifest_path(task_dir: Path) -> Path:
    return task_dir / PROMPT_MANIFEST_FILENAME


def rendered_prompt_path(task_dir: Path) -> Path:
    return task_dir / RENDERED_PROMPT_FILENAME


def launch_payload_path(task_dir: Path) -> Path:
    return task_dir / LAUNCH_PAYLOAD_FILENAME


def remote_launch_path(task_dir: Path) -> Path:
    return task_dir / REMOTE_LAUNCH_FILENAME


def write_binding_snapshot(
    path: Path,
    *,
    workspace: WorkspaceRecord,
    environment: EnvironmentRegistryEntry,
    task_profile: str,
    title: str,
    task_input: str,
    resolved_workdir: str,
) -> TaskBindingSummary:
    binding = TaskBindingSummary(
        workspace=_workspace_summary(workspace),
        environment=_environment_summary(environment),
        task_profile=task_profile,
        title=title,
        task_input=task_input,
        resolved_workdir=resolved_workdir,
        snapshot_path=str(path),
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
) -> tuple[Path, TaskPromptSummary]:
    prompt_composition = compose_task_prompt(
        workspace=workspace,
        environment=environment,
        task_profile=task_profile,
        task_input=task_input,
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
    )


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


def workspace_summary(workspace: WorkspaceRecord) -> WorkspaceSummary:
    return _workspace_summary(workspace)


def environment_summary(environment: EnvironmentRegistryEntry) -> EnvironmentSummary:
    return _environment_summary(environment)


def workspace_summary_from_json(value: str) -> WorkspaceSummary:
    payload = json.loads(value)
    return WorkspaceSummary(
        workspace_id=str(payload["workspace_id"]),
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
    }


def _workspace_summary(workspace: WorkspaceRecord) -> WorkspaceSummary:
    return WorkspaceSummary(
        workspace_id=workspace.workspace_id,
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

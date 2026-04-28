from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ainrf.environments.models import EnvironmentAuthKind
from ainrf.environments.service import InMemoryEnvironmentService
from ainrf.task_harness.artifacts import (
    binding_snapshot_path,
    launch_payload_path,
    prompt_manifest_path,
    write_binding_snapshot,
    write_launch_payload,
    write_prompt_artifacts,
)
from ainrf.task_harness.launcher import LaunchPayload
from ainrf.task_harness.models import TaskHarnessStatus, TaskConfigurationMode
from ainrf.task_harness.service import TaskHarnessService
from ainrf.workspaces.service import WorkspaceRegistryService


def test_task_harness_initialize_marks_unfinished_tasks_failed(tmp_path: Path) -> None:
    environment_service = InMemoryEnvironmentService()
    workspace_service = WorkspaceRegistryService(tmp_path)
    service = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    service.initialize()

    with service._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            INSERT INTO task_harness_tasks (
                task_id,
                workspace_id,
                environment_id,
                task_profile,
                title,
                task_input,
                status,
                created_at,
                updated_at,
                workspace_summary_json,
                environment_summary_json,
                binding_snapshot_path,
                prompt_manifest_path,
                launch_payload_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-restart",
                "workspace-default",
                "env-localhost",
                "claude-code",
                "Restart me",
                "Restart me",
                "running",
                "2026-04-23T08:00:00+00:00",
                "2026-04-23T08:00:00+00:00",
                '{"default_workdir":"/workspace/projects","description":"Seed workspace","label":"Repository Default","workspace_id":"workspace-default"}',
                '{"alias":"localhost","default_workdir":"/workspace/projects","display_name":"Localhost","environment_id":"env-localhost","host":"127.0.0.1"}',
                str(service.task_directory("task-restart") / "binding_snapshot.json"),
                str(service.task_directory("task-restart") / "prompt_layer_manifest.json"),
                str(service.task_directory("task-restart") / "resolved_launch_payload.json"),
            ),
        )
        connection.commit()

    restored = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    restored.initialize()
    task = restored.get_task("task-restart")
    output = restored.get_output("task-restart")

    assert task.status.value == "failed"
    assert task.result.failure_category == "startup failure"
    assert task.error_summary == (
        "startup failure: harness restart prevented Task Harness v1 from resuming this task"
    )
    assert output.items[-1].content == task.error_summary


def test_task_harness_persists_and_reloads_known_artifacts(tmp_path: Path) -> None:
    environment_service = InMemoryEnvironmentService()
    environment = environment_service.create_environment(
        alias="artifact-lab",
        display_name="Artifact Lab",
        host="127.0.0.1",
        user="root",
        auth_kind=EnvironmentAuthKind.SSH_KEY,
        default_workdir=str(tmp_path),
        task_harness_profile="Use the artifact lab profile.",
    )
    workspace_service = WorkspaceRegistryService(tmp_path)
    service = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    service.initialize()
    task_dir = service.task_directory("task-artifacts")
    task_dir.mkdir(parents=True, exist_ok=True)
    binding_path = binding_snapshot_path(task_dir)
    manifest_path = prompt_manifest_path(task_dir)
    launch_path = launch_payload_path(task_dir)
    workspace = workspace_service.get_workspace("workspace-default")
    workspace_summary = {
        "workspace_id": workspace.workspace_id,
        "label": workspace.label,
        "description": workspace.description,
        "default_workdir": workspace.default_workdir,
    }
    environment_summary = {
        "environment_id": environment.id,
        "alias": environment.alias,
        "display_name": environment.display_name,
        "host": environment.host,
        "default_workdir": environment.default_workdir,
    }

    write_binding_snapshot(
        binding_path,
        workspace=workspace,
        environment=environment,
        task_profile="claude-code",
        title="Artifact task",
        task_input="Inspect artifacts",
        resolved_workdir=str(tmp_path),
    )
    prompt_file, prompt_summary = write_prompt_artifacts(
        task_dir,
        manifest_path,
        workspace=workspace,
        environment=environment,
        task_profile="claude-code",
        task_input="Inspect artifacts",
    )
    write_launch_payload(
        launch_path,
        LaunchPayload(
            runner_kind="local-process",
            working_directory=str(tmp_path),
            command=["claude", "-p", "Inspect artifacts"],
            prompt_file=str(prompt_file),
            launch_payload_path=str(launch_path),
        ),
    )
    with service._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            INSERT INTO task_harness_tasks (
                task_id,
                workspace_id,
                environment_id,
                task_profile,
                title,
                task_input,
                status,
                created_at,
                updated_at,
                workspace_summary_json,
                environment_summary_json,
                binding_snapshot_path,
                prompt_manifest_path,
                launch_payload_path,
                resolved_workdir,
                runner_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-artifacts",
                workspace.workspace_id,
                environment.id,
                "claude-code",
                "Artifact task",
                "Inspect artifacts",
                TaskHarnessStatus.SUCCEEDED.value,
                "2026-04-23T08:00:00+00:00",
                "2026-04-23T08:00:00+00:00",
                json.dumps(workspace_summary, ensure_ascii=True, sort_keys=True),
                json.dumps(environment_summary, ensure_ascii=True, sort_keys=True),
                str(binding_path),
                str(manifest_path),
                str(launch_path),
                str(tmp_path),
                "local-process",
            ),
        )
        connection.commit()

    restored = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    restored.initialize()
    task = restored.get_task("task-artifacts")

    assert task.binding is not None
    assert task.prompt is not None
    assert task.runtime is not None
    assert (
        json.loads(binding_path.read_text(encoding="utf-8"))["workspace"]["workspace_prompt"]
        == workspace.workspace_prompt
    )
    assert (task_dir / "rendered_prompt.txt").read_text(
        encoding="utf-8"
    ) == task.prompt.rendered_prompt
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["layer_order"]
        == task.prompt.layer_order
    )
    assert json.loads(launch_path.read_text(encoding="utf-8")) == asdict(task.runtime)
    assert task.binding.snapshot_path == str(binding_path)
    assert task.binding.resolved_workdir == str(tmp_path)
    assert task.prompt.manifest_path == str(manifest_path)
    assert task.prompt.rendered_prompt == prompt_summary.rendered_prompt
    assert task.runtime.launch_payload_path == str(launch_path)


def test_task_harness_normalizes_three_layer_task_configuration(tmp_path: Path) -> None:
    environment_service = InMemoryEnvironmentService()
    environment = environment_service.create_environment(
        alias="profile-lab",
        display_name="Profile Lab",
        host="127.0.0.1",
        user="root",
        auth_kind=EnvironmentAuthKind.SSH_KEY,
        default_workdir=str(tmp_path),
        task_harness_profile="Use the profile lab runtime.",
    )
    workspace_service = WorkspaceRegistryService(tmp_path)
    service = TaskHarnessService(
        state_root=tmp_path,
        environment_service=environment_service,
        workspace_service=workspace_service,
    )
    service.initialize()

    task = service.create_task(
        workspace_id="workspace-default",
        environment_id=environment.id,
        task_profile="claude-code",
        task_input="ignored legacy input",
        title="Structured task",
        execution_engine="claude-code",
        research_agent_profile={
            "profile_id": "agent-literature",
            "label": "Literature Agent",
            "system_prompt": "Prefer careful literature synthesis.",
            "skills_prompt": "Use citation and repo-inspection skills.",
            "settings_json": {"permissions": {"allow": ["Read", "Grep"]}},
        },
        task_configuration={
            "mode": "structured_research",
            "template_id": "structured-research-default",
            "template_vars": {
                "research_goal": "Compare task harness designs",
                "context": "AINRF runtime refactor",
                "constraints": "Keep Claude Code as the only enabled engine",
                "deliverables": "Architecture notes and implementation steps",
                "validation_plan": "Run unit tests and build",
            },
        },
    )

    detail = service.get_task(task.task_id)

    assert detail.execution_engine == "claude-code"
    assert detail.research_agent_profile is not None
    assert detail.research_agent_profile.profile_id == "agent-literature"
    assert detail.research_agent_profile.settings_artifact_path is not None
    assert detail.task_configuration is not None
    assert detail.task_configuration.mode == TaskConfigurationMode.STRUCTURED_RESEARCH
    assert "Compare task harness designs" in detail.task_configuration.rendered_task_input
    assert detail.binding is not None
    assert detail.binding.task_input == detail.task_configuration.rendered_task_input

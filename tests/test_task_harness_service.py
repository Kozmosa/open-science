from __future__ import annotations

from pathlib import Path

from ainrf.environments.service import InMemoryEnvironmentService
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

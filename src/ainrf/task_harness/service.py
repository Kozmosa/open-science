from __future__ import annotations

import asyncio
import shlex
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry, utc_now
from ainrf.task_harness.artifacts import (
    binding_snapshot_path,
    claude_settings_path,
    dump_json,
    environment_summary,
    environment_summary_from_json,
    launch_payload_path,
    prompt_manifest_path,
    raw_prompt_configuration,
    read_binding_summary,
    read_prompt_summary,
    read_runtime_summary,
    research_agent_profile_from_payload,
    research_agent_profile_path,
    task_configuration_from_payload,
    task_configuration_snapshot_path,
    workspace_summary,
    workspace_summary_from_json,
    write_binding_snapshot,
    write_claude_settings_artifact,
    write_launch_payload,
    write_prompt_artifacts,
    write_research_agent_profile_snapshot,
    write_task_configuration_snapshot,
)
from ainrf.task_harness.launcher import (
    TaskLaunchError,
    build_local_launcher,
    build_remote_launcher,
    build_ssh_executor,
    is_local_environment,
)
from ainrf.task_harness.models import (
    ResearchAgentProfileSnapshot,
    TaskConfigurationMode,
    TaskConfigurationSnapshot,
    TaskDetail,
    TaskEdge,
    TaskHarnessStatus,
    TaskListItem,
    TaskOutputEvent,
    TaskOutputKind,
    TaskOutputPage,
    TaskResultSummary,
)
from ainrf.task_harness.prompting import (
    PromptCompositionError,
    derive_task_title,
)
from ainrf.workspaces import WorkspaceNotFoundError, WorkspaceRegistryService
from ainrf.workspaces.models import WorkspaceRecord

_FINAL_STATUSES = {
    TaskHarnessStatus.SUCCEEDED,
    TaskHarnessStatus.FAILED,
    TaskHarnessStatus.CANCELLED,
}
_TASK_PROFILE = "claude-code"
_EXECUTION_ENGINE = "claude-code"
_SUPPORTED_ENGINES = {"claude-code", "kimi-claude-code"}
_ARIS_SKILL_REQUIREMENTS: dict[TaskConfigurationMode, list[str]] = {
    TaskConfigurationMode.REPRODUCE_BASELINE: ["research-pipeline"],
    TaskConfigurationMode.DISCOVER_IDEAS: ["research-lit"],
    TaskConfigurationMode.VALIDATE_IDEAS: ["research-refine-pipeline"],
}


def _check_aris_skills(mode: TaskConfigurationMode, skill_root: Path) -> None:
    required = _ARIS_SKILL_REQUIREMENTS.get(mode)
    if not required:
        return
    missing = [s for s in required if not (skill_root / s).exists()]
    if missing:
        raise TaskHarnessError(
            f"ARIS skill(s) not installed: {', '.join(missing)}. "
            f"Install via Settings > Skill Repository before using {mode.value} mode."
        )


_HARNESS_RESTART_REASON = (
    "startup failure: harness restart prevented Task Harness v1 from resuming this task"
)


class TaskHarnessError(RuntimeError):
    pass


class TaskHarnessNotFoundError(TaskHarnessError):
    pass


class TaskHarnessOutputStoreError(TaskHarnessError):
    pass


class TaskHarnessService:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: InMemoryEnvironmentService,
        workspace_service: WorkspaceRegistryService,
        skill_root: Path | str | None = None,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._task_root = self._runtime_root / "task-harness" / "tasks"
        self._db_path = self._runtime_root / "task_harness.sqlite3"
        self._environment_service = environment_service
        self._workspace_service = workspace_service
        self._skill_root = Path(skill_root) if skill_root is not None else (state_root / "skills")
        self._initialized = False
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._running_processes: dict[str, Any] = {}

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        self._task_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_harness_tasks (
                    task_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    task_profile TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    latest_output_seq INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT,
                    failure_category TEXT,
                    exit_code INTEGER,
                    workspace_summary_json TEXT NOT NULL,
                    environment_summary_json TEXT NOT NULL,
                    binding_snapshot_path TEXT NOT NULL,
                    prompt_manifest_path TEXT NOT NULL,
                    launch_payload_path TEXT NOT NULL,
                    resolved_workdir TEXT,
                    runner_kind TEXT,
                    execution_engine TEXT NOT NULL DEFAULT 'claude-code'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_harness_output_events (
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq)
                )
                """
            )
            connection.commit()
            self._ensure_column(
                connection,
                "task_harness_tasks",
                "project_id",
                "ALTER TABLE task_harness_tasks ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'",
            )
            self._ensure_column(
                connection,
                "task_harness_tasks",
                "archived_at",
                "ALTER TABLE task_harness_tasks ADD COLUMN archived_at TEXT",
            )
            self._ensure_column(
                connection,
                "task_harness_tasks",
                "execution_engine",
                "ALTER TABLE task_harness_tasks ADD COLUMN execution_engine TEXT NOT NULL DEFAULT 'claude-code'",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_harness_edges (
                    edge_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    target_task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        self._fail_unfinished_tasks_for_restart()
        self._initialized = True

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        statement: str,
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(statement)

    def create_task(
        self,
        *,
        project_id: str = "default",
        workspace_id: str,
        environment_id: str,
        task_profile: str,
        task_input: str,
        title: str | None = None,
        execution_engine: str | None = None,
        research_agent_profile: dict[str, object] | None = None,
        task_configuration: dict[str, object] | None = None,
        auto_connect: bool = False,
    ) -> TaskListItem:
        self.initialize()
        if task_profile != _TASK_PROFILE:
            raise TaskHarnessError(f"Unsupported task profile: {task_profile}")
        resolved_execution_engine = execution_engine or _EXECUTION_ENGINE
        if resolved_execution_engine not in _SUPPORTED_ENGINES:
            raise TaskHarnessError(f"Unsupported execution engine: {resolved_execution_engine}")
        workspace = self._workspace_service.get_workspace(workspace_id)
        environment = self._environment_service.get_environment(environment_id)
        task_dir = self.task_directory(uuid4().hex)
        profile_snapshot = _normalize_research_agent_profile(research_agent_profile)
        settings_artifact_path = write_claude_settings_artifact(
            claude_settings_path(task_dir),
            profile_snapshot.settings_json,
            resolved_execution_engine,
        )
        if settings_artifact_path is not None:
            profile_snapshot.settings_artifact_path = settings_artifact_path
        configuration_snapshot = _normalize_task_configuration(task_input, task_configuration)
        _check_aris_skills(configuration_snapshot.mode, self._skill_root)
        resolved_task_input = configuration_snapshot.rendered_task_input
        resolved_title = (
            title.strip()
            if title is not None and title.strip()
            else derive_task_title(resolved_task_input)
        )
        task_id = task_dir.name
        task_dir.mkdir(parents=True, exist_ok=True)
        write_task_configuration_snapshot(
            task_configuration_snapshot_path(task_dir), configuration_snapshot
        )
        write_research_agent_profile_snapshot(
            research_agent_profile_path(task_dir), profile_snapshot
        )
        now = utc_now()
        workspace_summary_value = workspace_summary(workspace)
        environment_summary_value = environment_summary(environment)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_harness_tasks (
                    task_id,
                    project_id,
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
                    execution_engine
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    project_id,
                    workspace_id,
                    environment_id,
                    task_profile,
                    resolved_title,
                    resolved_task_input,
                    TaskHarnessStatus.QUEUED.value,
                    now.isoformat(),
                    now.isoformat(),
                    dump_json(asdict(workspace_summary_value)),
                    dump_json(asdict(environment_summary_value)),
                    str(binding_snapshot_path(task_dir)),
                    str(prompt_manifest_path(task_dir)),
                    str(launch_payload_path(task_dir)),
                    resolved_execution_engine,
                ),
            )
            connection.commit()
        self._append_output_event(
            task_id,
            TaskOutputKind.LIFECYCLE,
            "Task queued in Task Harness v1",
        )
        if auto_connect:
            self._maybe_auto_connect_task(project_id, task_id)
        try:
            self._schedule_task(task_id)
        except TaskHarnessError:
            pass
        return self._load_list_item(task_id)

    def create_task_edge(
        self,
        project_id: str,
        source_task_id: str,
        target_task_id: str,
    ) -> TaskEdge:
        self.initialize()
        edge_id = f"edge-{uuid4().hex[:12]}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_harness_edges (
                    edge_id, project_id, source_task_id, target_task_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (edge_id, project_id, source_task_id, target_task_id, now.isoformat()),
            )
            connection.commit()
        return TaskEdge(
            edge_id=edge_id,
            project_id=project_id,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            created_at=now,
        )

    def get_task_edges(self, project_id: str) -> list[TaskEdge]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT edge_id, project_id, source_task_id, target_task_id, created_at
                FROM task_harness_edges
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [
            TaskEdge(
                edge_id=row["edge_id"],
                project_id=row["project_id"],
                source_task_id=row["source_task_id"],
                target_task_id=row["target_task_id"],
                created_at=_parse_required_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def delete_task_edge(self, edge_id: str) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_harness_edges WHERE edge_id = ?",
                (edge_id,),
            )
            connection.commit()

    def _maybe_auto_connect_task(self, project_id: str, new_task_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task_id FROM task_harness_tasks
                WHERE project_id = ? AND task_id != ? AND archived_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id, new_task_id),
            ).fetchone()
        if row is not None:
            self.create_task_edge(project_id, row["task_id"], new_task_id)

    def list_tasks(self, *, include_archived: bool = False) -> list[TaskListItem]:
        self.initialize()
        with self._connect() as connection:
            if include_archived:
                rows = connection.execute(
                    """
                    SELECT * FROM task_harness_tasks
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM task_harness_tasks
                    WHERE archived_at IS NULL
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        return [self._row_to_list_item(row) for row in rows]

    def list_project_tasks(self, project_id: str, *, include_archived: bool = False) -> list[TaskListItem]:
        self.initialize()
        with self._connect() as connection:
            if include_archived:
                rows = connection.execute(
                    """
                    SELECT * FROM task_harness_tasks
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM task_harness_tasks
                    WHERE project_id = ? AND archived_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
        return [self._row_to_list_item(row) for row in rows]

    def archive_task(self, task_id: str) -> TaskListItem:
        self.initialize()
        _ = self._load_task_row(task_id)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET archived_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (now.isoformat(), now.isoformat(), task_id),
            )
            connection.commit()
        return self._load_list_item(task_id)

    async def cancel_task(self, task_id: str) -> TaskListItem:
        self.initialize()
        row = self._load_task_row(task_id)
        status = TaskHarnessStatus(row["status"])
        if status in _FINAL_STATUSES or status == TaskHarnessStatus.CANCELLED:
            raise TaskHarnessError(f"Cannot cancel task in status: {status.value}")

        process = self._running_processes.pop(task_id, None)
        if process is not None:
            try:
                await process.kill()
                await process.wait()
            except Exception:
                pass

        asyncio_task = self._running_tasks.pop(task_id, None)
        if asyncio_task is not None and not asyncio_task.done():
            asyncio_task.cancel()
            try:
                await asyncio_task
            except asyncio.CancelledError:
                pass

        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, completed_at = ?, exit_code = ?, failure_category = ?, error_summary = ?
                WHERE task_id = ? AND status NOT IN (?, ?, ?)
                """,
                (
                    TaskHarnessStatus.CANCELLED.value,
                    now.isoformat(),
                    now.isoformat(),
                    -1,
                    "cancelled",
                    "Task cancelled by user",
                    task_id,
                    TaskHarnessStatus.SUCCEEDED.value,
                    TaskHarnessStatus.FAILED.value,
                    TaskHarnessStatus.CANCELLED.value,
                ),
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise TaskHarnessError("Cannot cancel task that already reached a terminal state")
        self._append_output_event(task_id, TaskOutputKind.LIFECYCLE, "Task cancelled by user")
        return self._load_list_item(task_id)

    def get_task(self, task_id: str) -> TaskDetail:
        self.initialize()
        row = self._load_task_row(task_id)
        binding = read_binding_summary(row["binding_snapshot_path"])
        if binding is None:
            task_dir = self.task_directory(row["task_id"])
            profile_snapshot = _load_research_agent_profile(task_dir)
            configuration_snapshot = _load_task_configuration(task_dir, row["task_input"])
            execution_engine = _EXECUTION_ENGINE
            binding = write_binding_snapshot(
                Path(row["binding_snapshot_path"]),
                workspace=self._workspace_service.get_workspace(row["workspace_id"]),
                environment=self._environment_service.get_environment(row["environment_id"]),
                task_profile=row["task_profile"],
                title=row["title"],
                task_input=row["task_input"],
                resolved_workdir=row["resolved_workdir"] or "",
                execution_engine=execution_engine,
                research_agent_profile=profile_snapshot,
                task_configuration=configuration_snapshot,
            )
        else:
            profile_snapshot = binding.research_agent_profile
            configuration_snapshot = binding.task_configuration
            execution_engine = binding.execution_engine
        prompt = read_prompt_summary(row["prompt_manifest_path"])
        runtime = read_runtime_summary(row["launch_payload_path"])
        return TaskDetail(
            task_id=row["task_id"],
            project_id=row["project_id"],
            title=row["title"],
            task_profile=row["task_profile"],
            status=TaskHarnessStatus(row["status"]),
            workspace_summary=workspace_summary_from_json(row["workspace_summary_json"]),
            environment_summary=environment_summary_from_json(row["environment_summary_json"]),
            created_at=_parse_required_datetime(row["created_at"]),
            updated_at=_parse_required_datetime(row["updated_at"]),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
            error_summary=row["error_summary"],
            latest_output_seq=int(row["latest_output_seq"]),
            binding=binding,
            prompt=prompt,
            runtime=runtime,
            result=TaskResultSummary(
                exit_code=row["exit_code"],
                failure_category=row["failure_category"],
                error_summary=row["error_summary"],
                completed_at=_parse_datetime(row["completed_at"]),
            ),
            execution_engine=execution_engine,
            research_agent_profile=profile_snapshot,
            task_configuration=configuration_snapshot,
        )

    def get_output(self, task_id: str, *, after_seq: int = 0) -> TaskOutputPage:
        self.initialize()
        _ = self._load_task_row(task_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, seq, kind, content, created_at
                FROM task_harness_output_events
                WHERE task_id = ? AND seq > ?
                ORDER BY seq ASC
                """,
                (task_id, after_seq),
            ).fetchall()
        items = [
            TaskOutputEvent(
                task_id=row["task_id"],
                seq=int(row["seq"]),
                kind=TaskOutputKind(row["kind"]),
                content=row["content"],
                created_at=_parse_required_datetime(row["created_at"]),
            )
            for row in rows
        ]
        next_seq = items[-1].seq if items else after_seq
        return TaskOutputPage(items=items, next_seq=next_seq)

    def task_directory(self, task_id: str) -> Path:
        return self._task_root / task_id

    def _schedule_task(self, task_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise TaskHarnessError("Task harness scheduling requires a running event loop") from exc
        existing = self._running_tasks.get(task_id)
        if existing is not None and not existing.done():
            return
        task = loop.create_task(self._run_task(task_id))
        self._running_tasks[task_id] = task

        def _cleanup(_task: asyncio.Task[None]) -> None:
            self._running_tasks.pop(task_id, None)

        task.add_done_callback(_cleanup)

    async def _run_task(self, task_id: str) -> None:
        row = self._load_task_row(task_id)
        started_at = utc_now()
        self._update_task_status(
            task_id,
            status=TaskHarnessStatus.STARTING,
            started_at=started_at,
            error_summary=None,
        )
        self._append_output_event(task_id, TaskOutputKind.LIFECYCLE, "Task entered starting state")
        try:
            workspace = self._workspace_service.get_workspace(row["workspace_id"])
            environment = self._environment_service.get_environment(row["environment_id"])
            task_dir = self.task_directory(task_id)
            profile_snapshot = _load_research_agent_profile(task_dir)
            configuration_snapshot = _load_task_configuration(task_dir, row["task_input"])
            resolved_workdir = _resolve_workdir(workspace, environment)
            write_binding_snapshot(
                Path(row["binding_snapshot_path"]),
                workspace=workspace,
                environment=environment,
                task_profile=row["task_profile"],
                title=row["title"],
                task_input=row["task_input"],
                resolved_workdir=resolved_workdir,
                execution_engine=_EXECUTION_ENGINE,
                research_agent_profile=profile_snapshot,
                task_configuration=configuration_snapshot,
            )
            prompt_file, prompt_summary = write_prompt_artifacts(
                self.task_directory(task_id),
                Path(row["prompt_manifest_path"]),
                workspace=workspace,
                environment=environment,
                task_profile=row["task_profile"],
                task_input=row["task_input"],
                research_agent_profile=profile_snapshot,
            )
            settings_path = (
                Path(profile_snapshot.settings_artifact_path)
                if profile_snapshot.settings_artifact_path is not None
                else None
            )

            # Skill injection: generate .ainrf/ and sync to .claude/
            if profile_snapshot.skills:
                from ainrf.skills.injection import SkillInjectionService

                skill_root = self._skill_root
                if skill_root.is_dir():
                    injector = SkillInjectionService(skill_root)
                    injector.generate_ainrf(
                        workdir=resolved_workdir,
                        selected_skills=profile_snapshot.skills,
                        task_settings_override=profile_snapshot.settings_json,
                    )
                    # Only sync locally; remote sync is handled by build_remote_launcher
                    if is_local_environment(environment):
                        injector.sync_to_claude(workdir=resolved_workdir)

            if is_local_environment(environment):
                launch_payload, launch = build_local_launcher(
                    working_directory=resolved_workdir,
                    prompt_file=prompt_file,
                    rendered_prompt=prompt_summary.rendered_prompt,
                    settings_path=str(settings_path) if settings_path is not None else None,
                )
            else:
                executor = build_ssh_executor(environment, project_dir=resolved_workdir)
                try:
                    ainrf_dir = Path(resolved_workdir) / ".ainrf"
                    launch_payload, launch = await build_remote_launcher(
                        executor=executor,
                        task_id=task_id,
                        local_task_dir=self.task_directory(task_id),
                        working_directory=resolved_workdir,
                        prompt_file=prompt_file,
                        settings_path=settings_path,
                        ainrf_dir=ainrf_dir if ainrf_dir.exists() else None,
                    )
                except Exception:
                    await executor.close()
                    raise
            launch_payload.launch_payload_path = row["launch_payload_path"]
            write_launch_payload(Path(row["launch_payload_path"]), launch_payload)
            self._update_runtime_fields(
                task_id,
                resolved_workdir=resolved_workdir,
                runner_kind=launch_payload.runner_kind,
            )
            process = await launch()
            self._running_processes[task_id] = process
        except (
            EnvironmentNotFoundError,
            WorkspaceNotFoundError,
            PromptCompositionError,
            TaskLaunchError,
        ) as exc:
            self._fail_task(task_id, error_summary=str(exc), failure_category="startup failure")
            self._append_output_event(task_id, TaskOutputKind.SYSTEM, str(exc))
            return
        except Exception as exc:
            detail = f"startup failure: unexpected launch error: {exc}"
            self._fail_task(task_id, error_summary=detail, failure_category="startup failure")
            self._append_output_event(task_id, TaskOutputKind.SYSTEM, detail)
            return

        self._update_task_status(task_id, status=TaskHarnessStatus.RUNNING)
        self._append_output_event(task_id, TaskOutputKind.LIFECYCLE, "Task is running")

        try:
            exit_code = await self._stream_process_output(task_id, process)
        except TaskHarnessOutputStoreError as exc:
            await process.terminate()
            await process.wait()
            self._fail_task(
                task_id,
                error_summary=f"runtime failure: output store write failed: {exc}",
                failure_category="runtime failure",
            )
            return
        except Exception as exc:
            await process.terminate()
            await process.wait()
            self._fail_task(
                task_id,
                error_summary=f"runtime failure: process monitoring failed: {exc}",
                failure_category="runtime failure",
            )
            return
        finally:
            self._running_processes.pop(task_id, None)
            await process.cleanup()

        if exit_code == 0:
            self._complete_task(task_id, exit_code=0)
        else:
            self._fail_task(
                task_id,
                error_summary=f"runtime failure: task exited with code {exit_code}",
                failure_category="runtime failure",
                exit_code=exit_code,
            )

    async def _stream_process_output(self, task_id: str, process: Any) -> int:
        stdout_task = asyncio.create_task(
            self._pump_stream(task_id, process.stdout, TaskOutputKind.STDOUT)
        )
        stderr_task = asyncio.create_task(
            self._pump_stream(task_id, process.stderr, TaskOutputKind.STDERR)
        )
        wait_task = asyncio.create_task(process.wait())
        try:
            pending = {stdout_task, stderr_task, wait_task}
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if stdout_task in done and (exc := stdout_task.exception()) is not None:
                    raise exc
                if stderr_task in done and (exc := stderr_task.exception()) is not None:
                    raise exc
                if wait_task in done:
                    exit_code = int(wait_task.result())
                    await asyncio.gather(*pending)
                    self._append_output_event(
                        task_id,
                        TaskOutputKind.LIFECYCLE,
                        f"Process exited with code {exit_code}",
                    )
                    return exit_code
            raise TaskHarnessError("runtime failure: process wait loop ended unexpectedly")
        finally:
            for task in (stdout_task, stderr_task, wait_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, wait_task, return_exceptions=True)

    async def _pump_stream(self, task_id: str, stream: Any, kind: TaskOutputKind) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            text = (
                chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
            )
            self._append_output_event(task_id, kind, text)

    def _append_output_event(
        self,
        task_id: str,
        kind: TaskOutputKind,
        content: str,
    ) -> int:
        timestamp = utc_now()
        try:
            with self._connect() as connection:
                current = connection.execute(
                    """
                    SELECT COALESCE(MAX(seq), 0) AS seq
                    FROM task_harness_output_events
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                next_seq = int(current["seq"]) + 1 if current is not None else 1
                connection.execute(
                    """
                    INSERT INTO task_harness_output_events (task_id, seq, kind, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, next_seq, kind.value, content, timestamp.isoformat()),
                )
                connection.execute(
                    """
                    UPDATE task_harness_tasks
                    SET latest_output_seq = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (next_seq, timestamp.isoformat(), task_id),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise TaskHarnessOutputStoreError(str(exc)) from exc
        return next_seq

    def _complete_task(self, task_id: str, *, exit_code: int) -> None:
        completed_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, completed_at = ?, exit_code = ?, failure_category = NULL, error_summary = NULL
                WHERE task_id = ?
                """,
                (
                    TaskHarnessStatus.SUCCEEDED.value,
                    completed_at.isoformat(),
                    completed_at.isoformat(),
                    exit_code,
                    task_id,
                ),
            )
            connection.commit()

    def _fail_task(
        self,
        task_id: str,
        *,
        error_summary: str,
        failure_category: str,
        exit_code: int | None = None,
    ) -> None:
        completed_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, completed_at = ?, exit_code = ?, failure_category = ?, error_summary = ?
                WHERE task_id = ?
                """,
                (
                    TaskHarnessStatus.FAILED.value,
                    completed_at.isoformat(),
                    completed_at.isoformat(),
                    exit_code,
                    failure_category,
                    error_summary,
                    task_id,
                ),
            )
            connection.commit()
        self._append_output_event(task_id, TaskOutputKind.LIFECYCLE, error_summary)

    def _update_task_status(
        self,
        task_id: str,
        *,
        status: TaskHarnessStatus,
        started_at: datetime | None = None,
        error_summary: str | None = None,
    ) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, started_at = COALESCE(?, started_at), error_summary = ?
                WHERE task_id = ?
                """,
                (
                    status.value,
                    now.isoformat(),
                    started_at.isoformat() if started_at is not None else None,
                    error_summary,
                    task_id,
                ),
            )
            connection.commit()

    def _update_runtime_fields(
        self,
        task_id: str,
        *,
        resolved_workdir: str,
        runner_kind: str,
    ) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET resolved_workdir = ?, runner_kind = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (resolved_workdir, runner_kind, now.isoformat(), task_id),
            )
            connection.commit()

    def _load_list_item(self, task_id: str) -> TaskListItem:
        return self._row_to_list_item(self._load_task_row(task_id))

    def _load_task_row(self, task_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_harness_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise TaskHarnessNotFoundError("Task not found")
        return row

    def _row_to_list_item(self, row: sqlite3.Row) -> TaskListItem:
        return TaskListItem(
            task_id=row["task_id"],
            project_id=row["project_id"],
            title=row["title"],
            task_profile=row["task_profile"],
            status=TaskHarnessStatus(row["status"]),
            workspace_summary=workspace_summary_from_json(row["workspace_summary_json"]),
            environment_summary=environment_summary_from_json(row["environment_summary_json"]),
            created_at=_parse_required_datetime(row["created_at"]),
            updated_at=_parse_required_datetime(row["updated_at"]),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
            error_summary=row["error_summary"],
            latest_output_seq=int(row["latest_output_seq"]),
            execution_engine=row["execution_engine"] or _EXECUTION_ENGINE,
        )

    def _fail_unfinished_tasks_for_restart(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id
                FROM task_harness_tasks
                WHERE status NOT IN (?, ?, ?)
                """,
                (
                    TaskHarnessStatus.SUCCEEDED.value,
                    TaskHarnessStatus.FAILED.value,
                    TaskHarnessStatus.CANCELLED.value,
                ),
            ).fetchall()
            if not rows:
                return
            timestamp = utc_now().isoformat()
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, completed_at = ?, failure_category = ?, error_summary = ?
                WHERE status NOT IN (?, ?, ?)
                """,
                (
                    TaskHarnessStatus.FAILED.value,
                    timestamp,
                    timestamp,
                    "startup failure",
                    _HARNESS_RESTART_REASON,
                    TaskHarnessStatus.SUCCEEDED.value,
                    TaskHarnessStatus.FAILED.value,
                    TaskHarnessStatus.CANCELLED.value,
                ),
            )
            connection.commit()
        for row in rows:
            try:
                self._append_output_event(
                    row["task_id"],
                    TaskOutputKind.LIFECYCLE,
                    _HARNESS_RESTART_REASON,
                )
            except TaskHarnessOutputStoreError:
                continue

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


def _load_research_agent_profile(task_dir: Path) -> ResearchAgentProfileSnapshot:
    path = research_agent_profile_path(task_dir)
    if not path.exists():
        return _normalize_research_agent_profile(None)
    return research_agent_profile_from_payload(_load_json(path))


def _load_task_configuration(task_dir: Path, task_input: str) -> TaskConfigurationSnapshot:
    path = task_configuration_snapshot_path(task_dir)
    if not path.exists():
        return raw_prompt_configuration(task_input)
    return task_configuration_from_payload(_load_json(path))


def _load_json(path: Path) -> dict[str, object]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_research_agent_profile(
    payload: dict[str, object] | None,
) -> ResearchAgentProfileSnapshot:
    if payload is None:
        return ResearchAgentProfileSnapshot(
            profile_id="claude-code-default",
            label="Claude Code Default",
            system_prompt=None,
            skills=[],
            skills_prompt=None,
            settings_json=None,
        )
    settings_json = payload.get("settings_json")
    normalized_settings: dict[str, object] | None = None
    if isinstance(settings_json, dict):
        normalized_settings = {str(key): value for key, value in settings_json.items()}
    skills_raw = payload.get("skills", [])
    skills = [str(s) for s in skills_raw] if isinstance(skills_raw, list) else []
    return ResearchAgentProfileSnapshot(
        profile_id=str(payload.get("profile_id", "claude-code-custom")),
        label=str(payload.get("label", "Claude Code Custom")),
        system_prompt=_optional_str(payload.get("system_prompt")),
        skills=skills,
        skills_prompt=_optional_str(payload.get("skills_prompt")),
        settings_json=normalized_settings,
    )


def _normalize_task_configuration(
    legacy_task_input: str,
    payload: dict[str, object] | None,
) -> TaskConfigurationSnapshot:
    if payload is None:
        return raw_prompt_configuration(legacy_task_input)
    mode_raw = str(payload.get("mode", TaskConfigurationMode.RAW_PROMPT.value))
    try:
        mode = TaskConfigurationMode(mode_raw)
    except ValueError as exc:
        raise TaskHarnessError(f"Unsupported task configuration mode: {mode_raw}") from exc
    if mode == TaskConfigurationMode.RAW_PROMPT:
        raw_prompt = str(payload.get("raw_prompt") or legacy_task_input)
        return raw_prompt_configuration(raw_prompt)
    template_vars_value = payload.get("template_vars")
    template_vars: dict[str, object] = {}
    if isinstance(template_vars_value, dict):
        template_vars = {str(key): value for key, value in template_vars_value.items()}
    rendered_task_input = _render_task_prompt(legacy_task_input, mode, template_vars)
    return TaskConfigurationSnapshot(
        mode=mode,
        template_id=_optional_str(payload.get("template_id")) or "structured-research-default",
        template_vars=template_vars,
        raw_prompt=None,
        rendered_task_input=rendered_task_input,
    )


def _render_task_prompt(
    task_input: str,
    mode: TaskConfigurationMode,
    template_vars: dict[str, object],
) -> str:
    if mode == TaskConfigurationMode.STRUCTURED_RESEARCH:
        return _render_structured_research_prompt(template_vars)
    if mode == TaskConfigurationMode.REPRODUCE_BASELINE:
        return _render_reproduce_baseline_prompt(template_vars)
    if mode == TaskConfigurationMode.DISCOVER_IDEAS:
        return _render_discover_ideas_prompt(template_vars)
    if mode == TaskConfigurationMode.VALIDATE_IDEAS:
        return _render_validate_ideas_prompt(template_vars)
    return str(task_input).strip()


def _render_structured_research_prompt(template_vars: dict[str, object]) -> str:
    labels = [
        ("research_goal", "Research goal"),
        ("context", "Context"),
        ("constraints", "Constraints"),
        ("deliverables", "Expected deliverables"),
        ("validation_plan", "Validation plan"),
    ]
    sections = ["Structured research task"]
    for key, label in labels:
        value = str(template_vars.get(key, "")).strip()
        if value:
            sections.append(f"{label}:\n{value}")
    return "\n\n".join(sections)


def _render_reproduce_baseline_prompt(template_vars: dict[str, object]) -> str:
    paper_path = str(template_vars.get("paper_path", "")).strip()
    scope = str(template_vars.get("scope", "core-only")).strip() or "core-only"
    target_table = str(template_vars.get("target_table", "")).strip()
    budget_hours = _as_int(template_vars.get("budget_hours"), default=4)
    cmd = f"/research-pipeline {shlex.quote(paper_path)} --scope {shlex.quote(scope)}"
    if target_table:
        cmd += f" --target {shlex.quote(target_table)}"
    cmd += f" --budget {budget_hours}"
    return (
        f"{cmd}\n\n"
        "Reproduce the target paper. Parse the PDF, implement the core method, "
        "run experiments, and compare results against the paper's reported values."
    )


def _render_discover_ideas_prompt(template_vars: dict[str, object]) -> str:
    topic = str(template_vars.get("topic", "")).strip()
    seed_paper_path = str(template_vars.get("seed_paper_path", "")).strip()
    depth = _as_int(template_vars.get("depth"), default=3)
    budget_hours = _as_int(template_vars.get("budget_hours"), default=4)
    cmd = f"/research-lit {shlex.quote(topic)}"
    if seed_paper_path:
        cmd += f" --seed {shlex.quote(seed_paper_path)}"
    cmd += f" --depth {depth} --budget {budget_hours}"
    return (
        f"{cmd}\n\n"
        "Discover novel research ideas by surveying the literature, analyzing the seed paper "
        "(if provided), and generating concrete, feasible research proposals."
    )


def _render_validate_ideas_prompt(template_vars: dict[str, object]) -> str:
    idea_source = str(template_vars.get("idea_source", "")).strip()
    validation_scope = str(template_vars.get("validation_scope", "full")).strip() or "full"
    budget_hours = _as_int(template_vars.get("budget_hours"), default=4)
    cmd = (
        f"/research-refine-pipeline {shlex.quote(idea_source)} "
        f"--scope {shlex.quote(validation_scope)} --budget {budget_hours}"
    )
    return (
        f"{cmd}\n\n"
        "Validate the given research idea. Design experiments, run pilots, analyze feasibility, "
        "and produce a validation report."
    )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value)) if value is not None else default
    except (ValueError, TypeError):
        return default


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_required_datetime(value: str | None) -> datetime:
    if value is None:
        raise TaskHarnessError("Missing required datetime value in task harness store")
    return datetime.fromisoformat(value)


def _resolve_workdir(workspace: WorkspaceRecord, environment: EnvironmentRegistryEntry) -> str:
    candidate = workspace.default_workdir or environment.default_workdir
    if candidate is None or not candidate.strip():
        raise TaskLaunchError("startup failure: no working directory could be resolved")
    return candidate

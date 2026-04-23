from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry, utc_now
from ainrf.task_harness.launcher import (
    TaskLaunchError,
    build_local_launcher,
    build_remote_launcher,
    build_ssh_executor,
    is_local_environment,
    validate_local_readiness,
    validate_remote_readiness,
)
from ainrf.task_harness.models import (
    EnvironmentSummary,
    TaskBindingSummary,
    TaskDetail,
    TaskHarnessStatus,
    TaskListItem,
    TaskOutputEvent,
    TaskOutputKind,
    TaskOutputPage,
    TaskPromptLayer,
    TaskPromptSummary,
    TaskResultSummary,
    TaskRuntimeSummary,
    WorkspaceSummary,
)
from ainrf.task_harness.prompting import (
    PromptCompositionError,
    compose_task_prompt,
    derive_task_title,
)
from ainrf.workspaces import WorkspaceNotFoundError, WorkspaceRegistryService
from ainrf.workspaces.models import WorkspaceRecord

_FINAL_STATUSES = {TaskHarnessStatus.SUCCEEDED, TaskHarnessStatus.FAILED}
_TASK_PROFILE = "claude-code"
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
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._task_root = self._runtime_root / "task-harness" / "tasks"
        self._db_path = self._runtime_root / "task_harness.sqlite3"
        self._environment_service = environment_service
        self._workspace_service = workspace_service
        self._initialized = False
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

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
                    runner_kind TEXT
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
        self._fail_unfinished_tasks_for_restart()
        self._initialized = True

    def create_task(
        self,
        *,
        workspace_id: str,
        environment_id: str,
        task_profile: str,
        task_input: str,
        title: str | None = None,
    ) -> TaskListItem:
        self.initialize()
        if task_profile != _TASK_PROFILE:
            raise TaskHarnessError(f"Unsupported task profile: {task_profile}")
        workspace = self._workspace_service.get_workspace(workspace_id)
        environment = self._environment_service.get_environment(environment_id)
        resolved_title = (
            title.strip() if title is not None and title.strip() else derive_task_title(task_input)
        )
        task_id = uuid4().hex
        task_dir = self.task_directory(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        workspace_summary = _workspace_summary(workspace)
        environment_summary = _environment_summary(environment)
        with self._connect() as connection:
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
                    task_id,
                    workspace_id,
                    environment_id,
                    task_profile,
                    resolved_title,
                    task_input,
                    TaskHarnessStatus.QUEUED.value,
                    now.isoformat(),
                    now.isoformat(),
                    _dump_json(asdict(workspace_summary)),
                    _dump_json(asdict(environment_summary)),
                    str(task_dir / "binding_snapshot.json"),
                    str(task_dir / "prompt_layer_manifest.json"),
                    str(task_dir / "resolved_launch_payload.json"),
                ),
            )
            connection.commit()
        self._append_output_event(
            task_id,
            TaskOutputKind.LIFECYCLE,
            "Task queued in Task Harness v1",
        )
        self._schedule_task(task_id)
        return self._load_list_item(task_id)

    def list_tasks(self) -> list[TaskListItem]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_harness_tasks
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_list_item(row) for row in rows]

    def get_task(self, task_id: str) -> TaskDetail:
        self.initialize()
        row = self._load_task_row(task_id)
        binding = self._read_binding_summary(row["binding_snapshot_path"])
        prompt = self._read_prompt_summary(row["prompt_manifest_path"])
        runtime = self._read_runtime_summary(row["launch_payload_path"])
        return TaskDetail(
            task_id=row["task_id"],
            title=row["title"],
            task_profile=row["task_profile"],
            status=TaskHarnessStatus(row["status"]),
            workspace_summary=_workspace_summary_from_json(row["workspace_summary_json"]),
            environment_summary=_environment_summary_from_json(row["environment_summary_json"]),
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
            resolved_workdir = _resolve_workdir(workspace, environment)
            binding_snapshot = TaskBindingSummary(
                workspace=_workspace_summary(workspace),
                environment=_environment_summary(environment),
                task_profile=row["task_profile"],
                title=row["title"],
                task_input=row["task_input"],
                resolved_workdir=resolved_workdir,
                snapshot_path=row["binding_snapshot_path"],
            )
            self._write_json(
                Path(row["binding_snapshot_path"]),
                _binding_snapshot_payload(binding_snapshot, workspace, environment),
            )

            prompt_composition = compose_task_prompt(
                workspace=workspace,
                environment=environment,
                task_profile=row["task_profile"],
                task_input=row["task_input"],
            )
            prompt_file = self.task_directory(task_id) / "rendered_prompt.txt"
            prompt_file.write_text(prompt_composition.rendered_prompt, encoding="utf-8")
            self._write_json(
                Path(row["prompt_manifest_path"]),
                {
                    "rendered_prompt": prompt_composition.rendered_prompt,
                    "layer_order": prompt_composition.layer_order,
                    "layers": [asdict(layer) for layer in prompt_composition.layers],
                    "manifest_path": row["prompt_manifest_path"],
                },
            )

            if is_local_environment(environment):
                validate_local_readiness(resolved_workdir)
                launch_payload, launch = build_local_launcher(
                    working_directory=resolved_workdir,
                    prompt_file=prompt_file,
                    rendered_prompt=prompt_composition.rendered_prompt,
                )
            else:
                executor = build_ssh_executor(environment, project_dir=resolved_workdir)
                try:
                    await validate_remote_readiness(executor, working_directory=resolved_workdir)
                    launch_payload, launch = await build_remote_launcher(
                        executor=executor,
                        task_id=task_id,
                        local_task_dir=self.task_directory(task_id),
                        working_directory=resolved_workdir,
                        prompt_file=prompt_file,
                    )
                except Exception:
                    await executor.close()
                    raise
            launch_payload.launch_payload_path = row["launch_payload_path"]
            self._write_json(Path(row["launch_payload_path"]), asdict(launch_payload))
            self._update_runtime_fields(
                task_id,
                resolved_workdir=resolved_workdir,
                runner_kind=launch_payload.runner_kind,
            )
            process = await launch()
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
            title=row["title"],
            task_profile=row["task_profile"],
            status=TaskHarnessStatus(row["status"]),
            workspace_summary=_workspace_summary_from_json(row["workspace_summary_json"]),
            environment_summary=_environment_summary_from_json(row["environment_summary_json"]),
            created_at=_parse_required_datetime(row["created_at"]),
            updated_at=_parse_required_datetime(row["updated_at"]),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
            error_summary=row["error_summary"],
            latest_output_seq=int(row["latest_output_seq"]),
        )

    def _fail_unfinished_tasks_for_restart(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id
                FROM task_harness_tasks
                WHERE status NOT IN (?, ?)
                """,
                (TaskHarnessStatus.SUCCEEDED.value, TaskHarnessStatus.FAILED.value),
            ).fetchall()
            if not rows:
                return
            timestamp = utc_now().isoformat()
            connection.execute(
                """
                UPDATE task_harness_tasks
                SET status = ?, updated_at = ?, completed_at = ?, failure_category = ?, error_summary = ?
                WHERE status NOT IN (?, ?)
                """,
                (
                    TaskHarnessStatus.FAILED.value,
                    timestamp,
                    timestamp,
                    "startup failure",
                    _HARNESS_RESTART_REASON,
                    TaskHarnessStatus.SUCCEEDED.value,
                    TaskHarnessStatus.FAILED.value,
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

    def _read_binding_summary(self, snapshot_path: str) -> TaskBindingSummary | None:
        path = Path(snapshot_path)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TaskBindingSummary(
            workspace=_workspace_summary_from_json(_dump_json(payload["workspace"])),
            environment=_environment_summary_from_json(_dump_json(payload["environment"])),
            task_profile=str(payload["task_profile"]),
            title=str(payload["title"]),
            task_input=str(payload["task_input"]),
            resolved_workdir=str(payload["resolved_workdir"]),
            snapshot_path=str(payload["snapshot_path"]),
        )

    def _read_prompt_summary(self, manifest_path: str) -> TaskPromptSummary | None:
        path = Path(manifest_path)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
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

    def _read_runtime_summary(self, launch_payload_path: str) -> TaskRuntimeSummary | None:
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

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_required_datetime(value: str | None) -> datetime:
    if value is None:
        raise TaskHarnessError("Missing required datetime value in task harness store")
    return datetime.fromisoformat(value)


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


def _workspace_summary_from_json(value: str) -> WorkspaceSummary:
    payload = json.loads(value)
    return WorkspaceSummary(
        workspace_id=str(payload["workspace_id"]),
        label=str(payload["label"]),
        description=payload.get("description"),
        default_workdir=payload.get("default_workdir"),
    )


def _environment_summary_from_json(value: str) -> EnvironmentSummary:
    payload = json.loads(value)
    return EnvironmentSummary(
        environment_id=str(payload["environment_id"]),
        alias=str(payload["alias"]),
        display_name=str(payload["display_name"]),
        host=str(payload["host"]),
        default_workdir=payload.get("default_workdir"),
    )


def _resolve_workdir(workspace: WorkspaceRecord, environment: EnvironmentRegistryEntry) -> str:
    candidate = workspace.default_workdir or environment.default_workdir
    if candidate is None or not candidate.strip():
        raise TaskLaunchError("startup failure: no working directory could be resolved")
    return candidate


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _binding_snapshot_payload(
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

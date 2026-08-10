"""Async worker Adapter for canonical Turn submissions and RuntimeExecutions."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ainrf.db import connect
from ainrf.domain.conversation_contracts import (
    ConversationContractError,
    ConversationErrorCode,
    TurnItemActor,
    TurnItemType,
    TurnStatus,
)
from ainrf.domain.conversation_execution import (
    ConversationExecutionService,
    RuntimeExecutionClaim,
    SubmissionClaim,
)
from ainrf.domain.overview_jobs import OverviewSnapshotPlanner
from ainrf.domain.service import DomainConflictError
from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceModeError,
    maintenance_is_active_read_only,
)
from ainrf.harness_engine.base import EngineEvent, ExecutionContext, HarnessEngineType
from ainrf.harness_engine.conversation_adapter import ConversationRuntimeAdapter
from ainrf.harness_engine.factory import create_engine
from ainrf.harness_engine.mcp_servers import resolve_mcp_servers_for_task
from ainrf.harness_engine.session_state import SessionStateStore
from ainrf.literature.planner import run_planner_cycle
from ainrf.literature.tracking import LiteratureTrackingService
from ainrf.runtime import tenant_identity

if TYPE_CHECKING:
    from ainrf.literature.task_saga import LiteratureTaskSagaService


_EVENT_ITEM: dict[str, tuple[TurnItemType, TurnItemActor]] = {
    "message": (TurnItemType.AGENT_MESSAGE, TurnItemActor.AGENT),
    "thinking": (TurnItemType.REASONING_SUMMARY, TurnItemActor.AGENT),
    "tool_call": (TurnItemType.TOOL_CALL, TurnItemActor.AGENT),
    "tool_result": (TurnItemType.TOOL_RESULT, TurnItemActor.TOOL),
    "system": (TurnItemType.SYSTEM_NOTICE, TurnItemActor.SYSTEM),
    "error": (TurnItemType.ERROR, TurnItemActor.SYSTEM),
    "token": (TurnItemType.SYSTEM_NOTICE, TurnItemActor.SYSTEM),
}


class ConversationDispatcher:
    """Dispatch queued submissions without exposing execution details to HTTP."""

    def __init__(
        self,
        state_root: Path,
        *,
        artifact_sha: str | None = None,
        adapter_factory: Callable[[HarnessEngineType], ConversationRuntimeAdapter] | None = None,
        context_factory: Callable[[SubmissionClaim], ExecutionContext] | None = None,
    ) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._execution = ConversationExecutionService(state_root, artifact_sha=artifact_sha)
        self._checkpoint_store = SessionStateStore(state_root)
        self._adapter_factory = adapter_factory or self._default_adapter
        self._context_factory = context_factory or self._execution_context

    def _default_adapter(self, engine_type: HarnessEngineType) -> ConversationRuntimeAdapter:
        return ConversationRuntimeAdapter(create_engine(engine_type, state_root=self._state_root))

    def _execution_context(self, claim: SubmissionClaim) -> ExecutionContext:
        runtime_identity = self._execution.runtime_identity_for_launch_context(claim)
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                """
                SELECT task.*, project.status AS project_status,
                       workspace.canonical_path, workspace.status AS workspace_status,
                       workspace.owner_user_id AS workspace_owner_user_id,
                       workspace.environment_id AS workspace_environment_id,
                       environment.status AS environment_status,
                       environment.owner_user_id AS environment_owner_user_id,
                       snapshot.content AS context_content
                FROM tasks AS task
                JOIN projects AS project ON project.project_id = task.project_id
                JOIN workspaces AS workspace ON workspace.workspace_id = task.workspace_id
                JOIN environments AS environment ON environment.environment_id = task.environment_id
                JOIN project_workspace_links AS workspace_link
                  ON workspace_link.project_id = task.project_id
                 AND workspace_link.workspace_id = task.workspace_id
                 AND workspace_link.status = 'active'
                LEFT JOIN context_snapshots AS snapshot
                  ON snapshot.context_snapshot_id = ?
                WHERE task.task_id = ?
                """,
                (claim.context_snapshot_ref, claim.task_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Conversation Task domain relationships are unavailable")
        if row["project_status"] != "active":
            raise RuntimeError("Conversation Task Project is inactive")
        if row["workspace_status"] != "active" or row["environment_status"] != "active":
            raise RuntimeError("Conversation Task Workspace or Environment is inactive")
        owner_user_id = str(row["owner_user_id"])
        if row["workspace_owner_user_id"] != owner_user_id:
            raise RuntimeError("Conversation Task owner no longer owns the Workspace")
        if row["workspace_environment_id"] != row["environment_id"]:
            raise RuntimeError("Conversation Task Environment no longer matches the Workspace")
        self._require_environment_grant(row, owner_user_id)
        input_text = claim.input.get("text")
        if not isinstance(input_text, str) or not input_text.strip():
            raise RuntimeError("Turn input requires non-empty text")
        context_content = row["context_content"]
        prompt = (
            f"{context_content}\n\nUser Turn:\n{input_text}"
            if isinstance(context_content, str) and context_content
            else input_text
        )
        canonical_path = Path(str(row["canonical_path"])).expanduser()
        tenant_user = self._tenant_user_for(owner_user_id)
        engine_type = HarnessEngineType(str(row["harness_engine"]))
        if tenant_user is not None and engine_type is HarnessEngineType.AGENT_SDK:
            raise RuntimeError("Agent SDK is not eligible for tenant-isolated execution")
        self._validate_workspace_permissions(canonical_path, tenant_user)
        return ExecutionContext(
            task_id=claim.task_id,
            working_directory=str(canonical_path),
            rendered_prompt=prompt,
            researcher_type=str(row["researcher_type"]),
            engine_type=engine_type,
            skills=self._json_string_list(row["user_skills"]),
            mcp_servers=(
                resolve_mcp_servers_for_task(
                    self._state_root,
                    user_mcp_servers=self._json_string_list(row["user_mcp_servers"]),
                )
                or None
            ),
            runtime_launch_key=claim.submission_id,
            runtime_execution_id=runtime_identity.runtime_execution_id,
            session_state_path=str(
                self._checkpoint_store.checkpoint_path(
                    claim.task_id,
                    runtime_execution_id=runtime_identity.runtime_execution_id,
                )
            ),
            api_base_url=self._optional_string(row, "api_base_url"),
            api_key=self._optional_string(row, "api_key"),
            codex_base_url=self._optional_string(row, "codex_base_url"),
            codex_api_key=self._optional_string(row, "codex_api_key"),
            codex_model=self._optional_string(row, "codex_model"),
            codex_app_server_command=self._optional_string(row, "codex_app_server_command"),
            codex_approval_policy=self._optional_string(row, "codex_approval_policy"),
            tenant_user=tenant_user,
        )

    def _require_environment_grant(self, row: Mapping[str, object], owner_user_id: str) -> None:
        if row["environment_owner_user_id"] == owner_user_id:
            return
        if not self._auth_db_path.is_file():
            raise RuntimeError("Environment grant database is unavailable")
        uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            grant = conn.execute(
                "SELECT 1 FROM environment_access "
                "WHERE environment_id = ? AND user_id = ? AND status = 'active'",
                (str(row["environment_id"]), owner_user_id),
            ).fetchone()
        if grant is None:
            raise RuntimeError("Environment access was revoked or is unavailable")

    def _tenant_user_for(self, owner_user_id: str) -> str | None:
        if not tenant_identity.is_container_environment():
            return None
        if not self._auth_db_path.is_file():
            raise RuntimeError("Tenant identity database is unavailable")
        uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?", (owner_user_id,)
            ).fetchone()
        if row is None or not isinstance(row[0], str):
            raise RuntimeError("Task owner has no tenant identity")
        tenant_user = tenant_identity.tenant_linux_username(row[0])
        if not tenant_identity.linux_user_exists(tenant_user):
            raise RuntimeError("Task owner Linux tenant is not provisioned")
        return tenant_user

    @staticmethod
    def _validate_workspace_permissions(path: Path, tenant_user: str | None) -> None:
        if not path.is_dir():
            raise RuntimeError("Workspace canonical path is unavailable")
        if tenant_user is None:
            if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                raise RuntimeError("Worker lacks Workspace permissions")
            return
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "-u",
                tenant_user,
                "sh",
                "-c",
                'test -r "$1" && test -w "$1" && test -x "$1"',
                "tenant-workspace-permissions",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("Tenant lacks Workspace permissions")

    async def run_once(self) -> bool:
        self._execution.recover_stale_control_delivery()
        claim = self._execution.claim_next_submission()
        if claim is None:
            return False
        try:
            self._execution.begin_delivery(claim.submission_id)
        except ConversationContractError as exc:
            if exc.code is ConversationErrorCode.TASK_NOT_OPEN:
                # Cancellation won before delivery began.  The submission is
                # already terminal and there is no external side effect to
                # reconcile.
                return True
            raise
        except DomainConflictError:
            # A concurrent cancellation may have terminally consumed the
            # claim.  Treat it as handled rather than killing the worker loop.
            return True
        try:
            self._execution.ensure_submission_open(claim.submission_id)
        except ConversationContractError as exc:
            if exc.code is ConversationErrorCode.TASK_NOT_OPEN:
                with suppress(DomainConflictError, ConversationContractError):
                    self._execution.mark_delivery_unknown(
                        claim.submission_id,
                        failure_code="task_cancelled_before_adapter",
                        evidence={
                            "source": "worker_preflight",
                            "reason": "task_cancelled_before_adapter",
                            "replay_forbidden": True,
                        },
                    )
                return True
            raise
        except DomainConflictError:
            return True
        try:
            context = self._context_factory(claim)
            adapter = self._adapter_factory(context.engine_type)
        except asyncio.CancelledError:
            with suppress(DomainConflictError, ConversationContractError):
                self._execution.mark_delivery_unknown(
                    claim.submission_id,
                    failure_code="worker_cancelled_before_acceptance",
                    evidence={
                        "source": "worker_setup",
                        "replay_forbidden": True,
                    },
                )
            raise
        except Exception as exc:
            with suppress(DomainConflictError, ConversationContractError):
                self._execution.mark_delivery_unknown(
                    claim.submission_id,
                    failure_code="worker_failed_before_acceptance",
                    evidence={
                        "source": "worker_setup",
                        "error_type": type(exc).__name__,
                        "replay_forbidden": True,
                    },
                )
            return True
        try:
            self._execution.ensure_submission_open(claim.submission_id)
        except ConversationContractError as exc:
            if exc.code is ConversationErrorCode.TASK_NOT_OPEN:
                with suppress(DomainConflictError, ConversationContractError):
                    self._execution.mark_delivery_unknown(
                        claim.submission_id,
                        failure_code="task_cancelled_before_adapter_start",
                        evidence={
                            "source": "worker_preflight",
                            "reason": "task_cancelled_before_adapter_start",
                            "replay_forbidden": True,
                        },
                    )
                return True
            raise
        except DomainConflictError:
            return True
        execution: RuntimeExecutionClaim | None = None
        terminal_status: TurnStatus | None = None
        failure_code: str | None = None
        cancellation_during_acceptance = False

        async def emit(event: EngineEvent) -> None:
            nonlocal execution, terminal_status, failure_code, cancellation_during_acceptance
            if execution is None:
                native_kind, native_ref = adapter.native_turn_identity(
                    runtime_launch_key=claim.submission_id,
                    fallback_turn_id=claim.reserved_turn_id,
                )
                try:
                    execution = self._execution.accept_and_open_execution(
                        claim,
                        engine_family=(
                            "codex"
                            if context.engine_type is HarnessEngineType.CODEX_APP_SERVER
                            else "claude"
                        ),
                        engine_driver=context.engine_type,
                        native_turn_kind=native_kind,
                        native_turn_ref=native_ref,
                        native_runtime_kind="worker",
                        native_runtime_ref=claim.submission_id,
                        evidence={"source": "first_engine_event"},
                    )
                except ConversationContractError as exc:
                    if exc.code is ConversationErrorCode.TASK_NOT_OPEN:
                        cancellation_during_acceptance = True
                    raise
            if event.event_type == "status":
                raw_status = event.payload.get("status")
                if raw_status == "succeeded":
                    terminal_status = TurnStatus.COMPLETED
                elif raw_status in {"cancelled", "interrupted"}:
                    terminal_status = TurnStatus.INTERRUPTED
                elif raw_status == "failed":
                    terminal_status = TurnStatus.FAILED
                    failure_code = "engine_failed"
            mapping = _EVENT_ITEM.get(event.event_type)
            if mapping is not None and event.event_type != "status":
                item_type, actor = mapping
                payload: dict[str, object] = dict(event.payload)
                if event.token_usage is not None:
                    payload["usage"] = dict(event.token_usage)
                self._execution.append_item(
                    execution,
                    item_type=item_type,
                    actor=actor,
                    payload=payload,
                    native_provenance={"engine_event_type": event.event_type},
                )

        run = asyncio.create_task(adapter.start_turn(context, emit))
        cancelled_by_caller = False
        try:
            while not run.done():
                await self._consume_controls(adapter, claim, execution)
                await asyncio.sleep(0.05)
            await run
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            cancelled_by_caller = current_task is not None and current_task.cancelling() > 0
            terminal_status = TurnStatus.INTERRUPTED
            if not run.done():
                run.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await run
        except Exception:
            terminal_status = TurnStatus.FAILED
            failure_code = failure_code or "runtime_error"
        if execution is None:
            with suppress(DomainConflictError, ConversationContractError):
                self._execution.mark_delivery_unknown(
                    claim.submission_id,
                    failure_code=(
                        "task_cancelled_during_delivery"
                        if cancellation_during_acceptance
                        else "provider_acceptance_unproven"
                    ),
                    evidence={
                        "source": "runtime_adapter",
                        "reason": (
                            "task_cancelled_during_delivery"
                            if cancellation_during_acceptance
                            else "provider_acceptance_unproven"
                        ),
                        "replay_forbidden": True,
                    },
                )
            if cancelled_by_caller:
                raise asyncio.CancelledError
            return True
        terminal_status = terminal_status or TurnStatus.COMPLETED
        self._execution.finish_execution(
            execution,
            status=terminal_status,
            failure_code=failure_code,
            evidence={"source": "engine_terminal"},
        )
        if cancelled_by_caller:
            raise asyncio.CancelledError
        return True

    async def _consume_controls(
        self,
        adapter: ConversationRuntimeAdapter,
        claim: SubmissionClaim,
        execution: RuntimeExecutionClaim | None,
    ) -> None:
        if execution is None:
            return
        for control in self._execution.requested_controls(execution):
            control_id = str(control["control_request_id"])
            kind = str(control["kind"])
            payload = json.loads(str(control["payload_json"]))
            if kind == "steer":
                text = payload.get("text") if isinstance(payload, Mapping) else None
                if not isinstance(text, str):
                    with suppress(DomainConflictError):
                        self._execution.transition_control(
                            control_id,
                            expected_status="requested",
                            status="rejected",
                            evidence={"reason": "steer text is missing"},
                            failure_code="invalid_control_payload",
                        )
                    continue
                try:
                    self._execution.transition_control(
                        control_id,
                        expected_status="requested",
                        status="delivering",
                        evidence={"source": "worker", "phase": "control_delivery"},
                    )
                except DomainConflictError:
                    continue
                try:
                    receipt = await adapter.steer_turn(
                        task_id=claim.task_id,
                        expected_turn_id=execution.turn_id,
                        text=text,
                        runtime_launch_key=claim.submission_id,
                    )
                except asyncio.CancelledError:
                    with suppress(DomainConflictError):
                        self._execution.transition_control(
                            control_id,
                            expected_status="delivering",
                            status="delivery_unknown",
                            evidence={
                                "source": "runtime_adapter",
                                "phase": "control_delivery",
                                "reason": "adapter_cancelled",
                                "replay_forbidden": True,
                            },
                            failure_code="adapter_cancelled",
                        )
                    raise
                except Exception as exc:
                    with suppress(DomainConflictError):
                        self._execution.transition_control(
                            control_id,
                            expected_status="delivering",
                            status="delivery_unknown",
                            evidence={
                                "source": "runtime_adapter",
                                "phase": "control_delivery",
                                "error_type": type(exc).__name__,
                                "replay_forbidden": True,
                            },
                            failure_code="adapter_error",
                        )
                    continue
                try:
                    self._execution.transition_control(
                        control_id,
                        expected_status="delivering",
                        status="accepted" if receipt.accepted else "rejected",
                        evidence=dict(receipt.evidence),
                        failure_code=None if receipt.accepted else "capability_unsupported",
                    )
                except DomainConflictError:
                    continue
                continue

            claim_id = uuid4().hex
            try:
                if not self._execution.claim_interrupt(control_id, claim_id=claim_id):
                    continue
            except DomainConflictError:
                continue
            try:
                receipt = await adapter.interrupt_turn(
                    task_id=claim.task_id,
                    expected_turn_id=execution.turn_id,
                    runtime_launch_key=claim.submission_id,
                )
            except asyncio.CancelledError:
                with suppress(DomainConflictError):
                    self._execution.transition_control(
                        control_id,
                        expected_status="requested",
                        status="delivery_unknown",
                        evidence={
                            "source": "runtime_adapter",
                            "phase": "control_delivery",
                            "reason": "adapter_cancelled",
                            "delivery_claim_id": claim_id,
                            "replay_forbidden": True,
                        },
                        failure_code="adapter_cancelled",
                    )
                raise
            except Exception as exc:
                with suppress(DomainConflictError):
                    self._execution.transition_control(
                        control_id,
                        expected_status="requested",
                        status="delivery_unknown",
                        evidence={
                            "source": "runtime_adapter",
                            "phase": "control_delivery",
                            "error_type": type(exc).__name__,
                            "delivery_claim_id": claim_id,
                            "replay_forbidden": True,
                        },
                        failure_code="adapter_error",
                    )
                continue
            try:
                self._execution.transition_control(
                    control_id,
                    expected_status="requested",
                    status="accepted" if receipt.accepted else "rejected",
                    evidence=dict(receipt.evidence),
                    failure_code=None if receipt.accepted else "capability_unsupported",
                )
            except DomainConflictError:
                continue

    @staticmethod
    def _json_string_list(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        decoded = json.loads(value)
        return (
            [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []
        )

    @staticmethod
    def _optional_string(row: Mapping[str, object], key: str) -> str | None:
        value = row[key]
        return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class ConversationWorkerRunResult:
    """Observable result of one current domain-worker cycle."""

    outcome: str


class ConversationWorkerRuntime:
    """Compose every current no-port worker capability behind one Interface.

    The worker Adapter owns maintenance participation, Overview scheduling,
    Literature planning/recovery, and Conversation dispatch.  Historical
    Attempt and cutover authorities are deliberately absent.
    """

    def __init__(
        self,
        state_root: Path,
        *,
        artifact_sha: str,
        worker_id: str | None = None,
        adapter_factory: Callable[[HarnessEngineType], ConversationRuntimeAdapter] | None = None,
        context_factory: Callable[[SubmissionClaim], ExecutionContext] | None = None,
    ) -> None:
        if not artifact_sha:
            raise ValueError("Conversation worker requires an immutable artifact SHA")
        self._state_root = state_root
        self._artifact_sha = artifact_sha
        self.worker_id = worker_id or f"domain-worker-{uuid4().hex[:12]}"
        self._maintenance = DomainMaintenanceService(state_root)
        self._participant = DomainWriteParticipant(
            self._maintenance,
            "task-dispatcher",
            participant_id=self.worker_id,
            details={"component": "domain-worker"},
        )
        self._adapter_factory = adapter_factory
        self._context_factory = context_factory
        self._dispatcher: ConversationDispatcher | None = None
        self._overview_planner: OverviewSnapshotPlanner | None = None
        self._literature_tracking: LiteratureTrackingService | None = None
        self._literature_saga: LiteratureTaskSagaService | None = None
        self._started = False
        self._writable_runtime_ready = False
        self._maintenance_startup_read_only = maintenance_is_active_read_only(state_root)
        if not self._maintenance_startup_read_only:
            self._initialize_writable_runtime()

    def _initialize_writable_runtime(self) -> None:
        try:
            lease = self._maintenance.begin_mutation(source="domain-worker.bootstrap")
        except MaintenanceModeError:
            self._maintenance_startup_read_only = True
            return
        try:
            self._maintenance.check_lease(lease)
            self._dispatcher = ConversationDispatcher(
                self._state_root,
                artifact_sha=self._artifact_sha,
                adapter_factory=self._adapter_factory,
                context_factory=self._context_factory,
            )
            self._maintenance.check_lease(lease)
            self._overview_planner = OverviewSnapshotPlanner(
                self._state_root,
                planner_id=f"{self.worker_id}:overview",
                artifact_sha=self._artifact_sha,
            )
            self._maintenance.check_lease(lease)
            self._literature_tracking = LiteratureTrackingService(self._state_root)
            self._literature_tracking.initialize()
            self._maintenance.check_lease(lease)
            from ainrf.literature.task_saga import LiteratureTaskSagaService

            self._literature_saga = LiteratureTaskSagaService(
                self._state_root,
                artifact_sha=self._artifact_sha,
            )
            self._maintenance.check_lease(lease)
            self._writable_runtime_ready = True
        except MaintenanceModeError:
            self._maintenance_startup_read_only = True
        finally:
            self._maintenance.finish_mutation(lease)

    def start(self) -> bool:
        if self._maintenance_startup_read_only:
            if not maintenance_is_active_read_only(self._state_root):
                return False
            if not self._started:
                self._maintenance.adopt_existing_maintenance_schema()
                self._participant.start()
                self._started = True
            return False
        if not self._writable_runtime_ready:
            return False
        status = self._participant.heartbeat() if self._started else self._participant.start()
        self._started = True
        return status.status == "active"

    def stop(self) -> None:
        if self._overview_planner is not None:
            self._overview_planner.stop()
        if self._started:
            self._participant.stop()
            self._started = False

    async def run_once(self) -> ConversationWorkerRunResult:
        if not self.start():
            return ConversationWorkerRunResult(outcome="maintenance_drained")
        assert self._dispatcher is not None
        assert self._overview_planner is not None
        assert self._literature_tracking is not None
        assert self._literature_saga is not None
        overview = self._overview_planner.run_once()
        if overview.outcome == "maintenance_drained":
            self._participant.drain()
            return ConversationWorkerRunResult(outcome="maintenance_drained")
        try:
            lease = self._participant.begin_mutation(source="task-dispatcher.cycle")
        except MaintenanceModeError:
            self._participant.drain()
            return ConversationWorkerRunResult(outcome="maintenance_drained")
        try:
            run_planner_cycle(
                self._literature_tracking,
                check_lease=lambda: self._participant.check_lease(lease),
            )
            self._maintenance.check_lease(lease)
            self._literature_saga.recover_pending(worker_id=f"{self.worker_id}:literature")
            self._maintenance.check_lease(lease)
            processed = await self._dispatcher.run_once()
            self._participant.heartbeat()
            return ConversationWorkerRunResult(outcome="completed" if processed else "idle")
        except MaintenanceModeError:
            self._participant.drain()
            return ConversationWorkerRunResult(outcome="maintenance_drained")
        finally:
            self._participant.finish_mutation(lease)

    async def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.start()
        heartbeat_task = asyncio.create_task(self._heartbeat_forever(poll_seconds=poll_seconds))
        try:
            while True:
                result = await self.run_once()
                if result.outcome in {"idle", "maintenance_drained"}:
                    await asyncio.sleep(poll_seconds)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            self.stop()

    async def _heartbeat_forever(self, *, poll_seconds: float) -> None:
        interval = min(5.0, max(1.0, poll_seconds))
        while True:
            if self._started:
                self._participant.heartbeat()
            await asyncio.sleep(interval)

"""No-port durable Task dispatcher for the v2 domain worker process."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ainrf.auth.service import _is_container_environment, _linux_user_exists, tenant_linux_username
from ainrf.db import connect
from ainrf.domain.attempts import AttemptService, DispatchClaim, DispatchClaimError
from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceLease,
    MaintenanceModeError,
)
from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
    RuntimeProbeStatus,
    get_engine,
)
from ainrf.harness_engine.db_session_store import DbSessionStore
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine
from ainrf.harness_engine.mcp_servers import resolve_mcp_servers_for_task


@dataclass(frozen=True, slots=True)
class DispatchRunResult:
    outcome: str
    dispatch_id: str | None = None
    attempt_id: str | None = None
    detail: str | None = None


class DispatchValidationError(ValueError):
    """A claimed Task is no longer safe or authorized to start."""


EngineFactory = Callable[[HarnessEngineType], HarnessEngine]


class TaskDispatcher:
    """Claim durable work and launch/adopt one Runtime Session at a time.

    The dispatcher owns no HTTP port and does not call legacy
    ``schedule_task()``.  It records a ``starting`` RuntimeSession before the
    engine call.  If that worker dies afterwards, the next worker recovers the
    expired claim, probes the deterministic launch key, and only starts again
    when the engine can positively report an absent runtime.
    """

    def __init__(
        self,
        state_root: Path,
        *,
        dispatcher_id: str | None = None,
        engine_factory: EngineFactory | None = None,
        lease_seconds: int = 30,
    ) -> None:
        if lease_seconds <= 2:
            raise ValueError("lease_seconds must be greater than two seconds")
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._auth_db_path = state_root / "runtime" / "auth.sqlite3"
        self._attempts = AttemptService(state_root)
        self._maintenance = DomainMaintenanceService(state_root)
        self._maintenance.initialize()
        self.dispatcher_id = dispatcher_id or f"domain-worker-{uuid4().hex[:12]}"
        self._participant = DomainWriteParticipant(
            self._maintenance,
            "task-dispatcher",
            participant_id=self.dispatcher_id,
            details={"component": "domain-worker"},
        )
        self._engine_factory = engine_factory or self._default_engine_factory
        self._engines: dict[HarnessEngineType, HarnessEngine] = {}
        self._lease_seconds = lease_seconds
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._participant.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._participant.stop()
            self._started = False

    async def run_once(self) -> DispatchRunResult:
        self.start()
        try:
            lease = self._participant.begin_mutation(source="task-dispatcher.claim")
        except MaintenanceModeError:
            self._participant.drain()
            return DispatchRunResult(outcome="maintenance_drained")
        try:
            claim = self._attempts.claim_next(self.dispatcher_id, lease_seconds=self._lease_seconds)
            if claim is None:
                self._participant.heartbeat()
                return DispatchRunResult(outcome="idle")
            return await self._run_claim(claim, lease)
        finally:
            self._participant.finish_mutation(lease)

    async def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.start()
        try:
            while True:
                result = await self.run_once()
                if result.outcome in {"idle", "maintenance_drained"}:
                    await asyncio.sleep(poll_seconds)
        finally:
            self.stop()

    async def _run_claim(self, claim: DispatchClaim, lease: MaintenanceLease) -> DispatchRunResult:
        try:
            self._maintenance.check_lease(lease)
        except MaintenanceModeError:
            return self._release_for_maintenance(claim)
        try:
            context, environment_id, grant_version = self._execution_context_for(claim)
        except DispatchValidationError as exc:
            self._attempts.stop_for_permission_revocation(claim, reason=str(exc))
            return DispatchRunResult(
                outcome="stopped_permission_revoked",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
                detail=str(exc),
            )
        self._attempts.record_authorization_snapshot(
            claim,
            environment_id=environment_id,
            grant_version=grant_version,
        )
        try:
            self._maintenance.check_lease(lease)
            preparation = self._attempts.prepare_runtime_launch(claim)
            context, environment_id, grant_version = self._execution_context_for(claim)
            self._attempts.record_authorization_snapshot(
                claim,
                environment_id=environment_id,
                grant_version=grant_version,
            )
            # Check immediately before the engine boundary.  A maintenance
            # epoch that starts after this point still sees this lease as
            # in-flight and cannot pass cutover preflight until it finishes.
            self._maintenance.check_lease(lease)
        except MaintenanceModeError:
            return self._release_for_maintenance(claim)
        except DispatchValidationError as exc:
            self._attempts.stop_for_permission_revocation(claim, reason=str(exc))
            return DispatchRunResult(
                outcome="stopped_permission_revoked",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
                detail=str(exc),
            )
        except DispatchClaimError as exc:
            return DispatchRunResult(
                outcome="claim_lost",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
                detail=str(exc),
            )
        engine = self._engine_for(context.engine_type)
        if preparation.must_probe:
            recovery = await self._recover_existing_runtime(
                claim,
                preparation.runtime_session_id,
                engine,
                allow_start_after_absent=preparation.allow_start_after_absent,
            )
            if recovery is not None:
                return recovery
        return await self._start_new_runtime(claim, preparation.runtime_session_id, engine, context)

    def _release_for_maintenance(self, claim: DispatchClaim) -> DispatchRunResult:
        try:
            self._attempts.release_unstarted_claim(
                claim,
                reason="Maintenance started before external runtime launch",
            )
        except DispatchClaimError:
            # A recovered runtime may have crossed the launch boundary before
            # this worker observed the epoch.  It must remain conservative and
            # be reconciled rather than silently requeued.
            try:
                self._attempts.mark_launch_unknown(
                    claim,
                    reason="Maintenance started while runtime launch state was uncertain",
                )
            except DispatchClaimError:
                pass
        self._participant.drain()
        return DispatchRunResult(
            outcome="maintenance_drained",
            dispatch_id=claim.dispatch_id,
            attempt_id=claim.attempt_id,
        )

    async def _recover_existing_runtime(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        engine: HarnessEngine,
        *,
        allow_start_after_absent: bool,
    ) -> DispatchRunResult | None:
        probe = await engine.probe_runtime(
            task_id=claim.task_id,
            launch_key=claim.runtime_launch_key,
        )
        if probe.status is RuntimeProbeStatus.ABSENT:
            if allow_start_after_absent:
                return None
            self._attempts.mark_launch_unknown(
                claim,
                reason="Previously launched runtime is no longer observable",
            )
            return DispatchRunResult(
                outcome="launch_unknown",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
            )
        if probe.status is RuntimeProbeStatus.UNKNOWN:
            self._attempts.mark_launch_unknown(
                claim,
                reason="Engine could not determine whether the prior runtime launched",
            )
            return DispatchRunResult(
                outcome="launch_unknown",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
            )
        adopted = await engine.adopt_runtime(
            task_id=claim.task_id,
            launch_key=claim.runtime_launch_key,
        )
        if adopted.status is not RuntimeProbeStatus.RUNNING:
            self._attempts.mark_launch_unknown(
                claim,
                reason="Engine reported a runtime but could not adopt it safely",
            )
            return DispatchRunResult(
                outcome="launch_unknown",
                dispatch_id=claim.dispatch_id,
                attempt_id=claim.attempt_id,
            )
        self._attempts.adopt_runtime(
            claim,
            runtime_session_id,
            engine_session_key=adopted.engine_session_key,
            metadata=dict(adopted.metadata),
        )
        return DispatchRunResult(
            outcome="adopted",
            dispatch_id=claim.dispatch_id,
            attempt_id=claim.attempt_id,
        )

    async def _start_new_runtime(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        engine: HarnessEngine,
        context: ExecutionContext,
    ) -> DispatchRunResult:
        active_claim = claim
        heartbeat_stop = asyncio.Event()

        async def heartbeat() -> None:
            nonlocal active_claim
            interval = max(1.0, self._lease_seconds / 3)
            try:
                while True:
                    try:
                        await asyncio.wait_for(heartbeat_stop.wait(), timeout=interval)
                        return
                    except TimeoutError:
                        active_claim = self._attempts.heartbeat_claim(
                            active_claim, lease_seconds=self._lease_seconds
                        )
                        self._participant.heartbeat()
            except DispatchClaimError:
                return

        heartbeat_task = asyncio.create_task(heartbeat())

        async def emit(event: EngineEvent) -> None:
            self._attempts.record_event(active_claim, event)

        try:
            await engine.start(context, emit)
            state = self._attempts.dispatch_state(active_claim.dispatch_id)
            if state["status"] in {"claimed", "dispatched"}:
                if state["status"] == "claimed":
                    self._attempts.mark_runtime_running(active_claim, runtime_session_id)
                self._attempts.mark_runtime_completed(active_claim, runtime_session_id)
                outcome = "completed"
            else:
                outcome = str(state["status"])
            return DispatchRunResult(
                outcome=outcome,
                dispatch_id=active_claim.dispatch_id,
                attempt_id=active_claim.attempt_id,
            )
        except asyncio.CancelledError:
            self._attempts.mark_launch_unknown(
                active_claim,
                reason="Dispatcher was cancelled while runtime launch was in progress",
            )
            raise
        except Exception as exc:
            state = self._attempts.dispatch_state(active_claim.dispatch_id)
            if state["status"] in {"cancelled", "completed", "failed", "launch_unknown"}:
                return DispatchRunResult(
                    outcome=str(state["status"]),
                    dispatch_id=active_claim.dispatch_id,
                    attempt_id=active_claim.attempt_id,
                    detail=str(exc),
                )
            await self._recover_after_start_error(
                active_claim, runtime_session_id, engine, str(exc)
            )
            state = self._attempts.dispatch_state(active_claim.dispatch_id)
            return DispatchRunResult(
                outcome=str(state["status"]),
                dispatch_id=active_claim.dispatch_id,
                attempt_id=active_claim.attempt_id,
                detail=str(exc),
            )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _recover_after_start_error(
        self,
        claim: DispatchClaim,
        runtime_session_id: str,
        engine: HarnessEngine,
        error: str,
    ) -> None:
        probe = await engine.probe_runtime(
            task_id=claim.task_id, launch_key=claim.runtime_launch_key
        )
        if probe.status is RuntimeProbeStatus.RUNNING:
            adopted = await engine.adopt_runtime(
                task_id=claim.task_id, launch_key=claim.runtime_launch_key
            )
            if adopted.status is RuntimeProbeStatus.RUNNING:
                self._attempts.adopt_runtime(
                    claim,
                    runtime_session_id,
                    engine_session_key=adopted.engine_session_key,
                    metadata=dict(adopted.metadata),
                )
                return
            self._attempts.mark_launch_unknown(
                claim,
                reason="Engine reported a running runtime but could not adopt it safely",
            )
            return
        if probe.status is RuntimeProbeStatus.UNKNOWN:
            self._attempts.mark_launch_unknown(claim, reason=error)
            return
        self._attempts.mark_runtime_failed(claim, runtime_session_id, reason=error)

    def _execution_context_for(self, claim: DispatchClaim) -> tuple[ExecutionContext, str, int]:
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                """SELECT
                       task.*, project.status AS project_status,
                       task.status AS task_status,
                       attempt.status AS attempt_status,
                       workspace.status AS workspace_status,
                       workspace.owner_user_id AS workspace_owner_user_id,
                       workspace.environment_id AS workspace_environment_id,
                       workspace.canonical_path AS workspace_canonical_path,
                       environment.status AS environment_status,
                       environment.owner_user_id AS environment_owner_user_id,
                       snapshot.content AS context_content,
                       attempt.authorization_grant_version AS prior_grant_version
                   FROM tasks AS task
                   JOIN projects AS project ON project.project_id = task.project_id
                   JOIN workspaces AS workspace ON workspace.workspace_id = task.workspace_id
                   JOIN environments AS environment ON environment.environment_id = task.environment_id
                   JOIN project_workspace_links AS workspace_link
                     ON workspace_link.project_id = task.project_id
                    AND workspace_link.workspace_id = task.workspace_id
                    AND workspace_link.status = 'active'
                   JOIN agent_task_attempts AS attempt
                     ON attempt.attempt_id = ? AND attempt.task_id = task.task_id
                   LEFT JOIN context_snapshots AS snapshot
                     ON snapshot.context_snapshot_id = attempt.context_snapshot_id
                   WHERE task.task_id = ?""",
                (claim.attempt_id, claim.task_id),
            ).fetchone()
        if row is None:
            raise DispatchValidationError("Task, Attempt, or domain relationship no longer exists")
        if row["project_status"] != "active":
            raise DispatchValidationError("Project is not active")
        if row["task_status"] not in {"queued", "starting", "running"}:
            raise DispatchValidationError("Task is no longer eligible to start")
        if row["attempt_status"] not in {"queued", "starting", "running"}:
            raise DispatchValidationError("Attempt is no longer eligible to start")
        if row["workspace_status"] != "active":
            raise DispatchValidationError("Workspace is not active")
        if row["environment_status"] != "active":
            raise DispatchValidationError("Environment is not active")
        if row["workspace_owner_user_id"] != row["owner_user_id"]:
            raise DispatchValidationError("Task owner no longer owns the Workspace")
        if row["workspace_environment_id"] != row["environment_id"]:
            raise DispatchValidationError("Task Environment no longer matches the Workspace")
        context_content = row["context_content"]
        if not isinstance(context_content, str) or not context_content:
            raise DispatchValidationError("Attempt has no immutable Context Snapshot")
        environment_id = str(row["environment_id"])
        owner_user_id = str(row["owner_user_id"])
        grant_version = self._active_grant_version(
            environment_id=environment_id,
            owner_user_id=owner_user_id,
            environment_owner_user_id=row["environment_owner_user_id"],
        )
        prior_grant_version = row["prior_grant_version"]
        if prior_grant_version is not None and int(prior_grant_version) != grant_version:
            raise DispatchValidationError("Environment grant version changed while Task was queued")
        canonical_path = Path(str(row["workspace_canonical_path"])).expanduser()
        tenant_user = self._tenant_user_for(owner_user_id)
        engine_type = HarnessEngineType(str(row["harness_engine"]))
        if tenant_user is not None and engine_type is HarnessEngineType.AGENT_SDK:
            # Agent SDK currently launches through Popen without a sudo-based
            # tenant handoff.  Treat it as ineligible rather than validating a
            # tenant path and then executing it as the backend user.
            raise DispatchValidationError(
                "Agent SDK is not eligible for tenant-isolated durable execution"
            )
        self._validate_workspace_permissions(canonical_path, tenant_user)
        task_id = str(row["task_id"])
        return (
            ExecutionContext(
                task_id=task_id,
                working_directory=str(canonical_path),
                rendered_prompt=context_content,
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
                session_state_path=str(
                    self._state_root / "session-states" / claim.attempt_id / "checkpoint.json"
                ),
                tenant_user=tenant_user,
                api_base_url=self._optional_string(row, "api_base_url"),
                api_key=self._optional_string(row, "api_key"),
                codex_base_url=self._optional_string(row, "codex_base_url"),
                codex_api_key=self._optional_string(row, "codex_api_key"),
                codex_model=self._optional_string(row, "codex_model"),
                codex_app_server_command=self._optional_string(row, "codex_app_server_command"),
                codex_approval_policy=self._optional_string(row, "codex_approval_policy"),
                runtime_launch_key=claim.runtime_launch_key,
                attempt_id=claim.attempt_id,
            ),
            environment_id,
            grant_version,
        )

    def _active_grant_version(
        self,
        *,
        environment_id: str,
        owner_user_id: str,
        environment_owner_user_id: object,
    ) -> int:
        if environment_owner_user_id == owner_user_id:
            return 0
        if not self._auth_db_path.is_file():
            raise DispatchValidationError("Environment grant database is unavailable")
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                grant = conn.execute(
                    """SELECT grant_version FROM environment_access
                       WHERE environment_id = ? AND user_id = ? AND status = 'active'""",
                    (environment_id, owner_user_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DispatchValidationError("Environment grant cannot be read") from exc
        if grant is None:
            raise DispatchValidationError("Environment access was revoked or is unavailable")
        return int(grant[0])

    def _tenant_user_for(self, owner_user_id: str) -> str | None:
        if not _is_container_environment():
            return None
        if not self._auth_db_path.is_file():
            raise DispatchValidationError("Tenant identity database is unavailable")
        auth_uri = f"{self._auth_db_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(auth_uri, uri=True)) as conn:
                row = conn.execute(
                    "SELECT username FROM users WHERE id = ?", (owner_user_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise DispatchValidationError("Tenant identity cannot be read") from exc
        if row is None or not isinstance(row[0], str):
            raise DispatchValidationError("Task owner has no tenant identity")
        tenant_user = tenant_linux_username(row[0])
        if not _linux_user_exists(tenant_user):
            raise DispatchValidationError("Task owner Linux tenant is not provisioned")
        return tenant_user

    @staticmethod
    def _validate_workspace_permissions(path: Path, tenant_user: str | None) -> None:
        if not path.is_dir():
            raise DispatchValidationError("Workspace canonical path is unavailable")
        if tenant_user is None:
            if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                raise DispatchValidationError("Worker lacks Workspace permissions")
            return
        result = subprocess.run(
            ["sudo", "-n", "-u", tenant_user, "test", "-rwx", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise DispatchValidationError("Tenant lacks Workspace permissions")

    def _engine_for(self, engine_type: HarnessEngineType) -> HarnessEngine:
        engine = self._engines.get(engine_type)
        if engine is None:
            engine = self._engine_factory(engine_type)
            if engine_type is HarnessEngineType.AGENT_SDK and isinstance(engine, AgentSdkEngine):
                engine._session_store = DbSessionStore(str(self._db_path))
            self._engines[engine_type] = engine
        return engine

    @staticmethod
    def _default_engine_factory(engine_type: HarnessEngineType) -> HarnessEngine:
        return get_engine(engine_type.value)

    @staticmethod
    def _json_string_list(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return (
            [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []
        )

    @staticmethod
    def _optional_string(row: sqlite3.Row, column: str) -> str | None:
        try:
            value = row[column]
        except IndexError:
            return None
        return value if isinstance(value, str) and value else None

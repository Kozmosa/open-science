"""Async worker Adapter for canonical Turn submissions and RuntimeExecutions."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path

from ainrf.db import connect
from ainrf.domain.conversation_contracts import TurnItemActor, TurnItemType, TurnStatus
from ainrf.domain.conversation_execution import (
    ConversationExecutionService,
    RuntimeExecutionClaim,
    SubmissionClaim,
)
from ainrf.harness_engine.base import EngineEvent, ExecutionContext, HarnessEngineType
from ainrf.harness_engine.conversation_adapter import ConversationRuntimeAdapter
from ainrf.harness_engine.factory import create_engine
from ainrf.harness_engine.mcp_servers import resolve_mcp_servers_for_task
from ainrf.runtime import tenant_identity


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
        self._adapter_factory = adapter_factory or self._default_adapter
        self._context_factory = context_factory or self._execution_context

    def _default_adapter(self, engine_type: HarnessEngineType) -> ConversationRuntimeAdapter:
        return ConversationRuntimeAdapter(create_engine(engine_type, state_root=self._state_root))

    def _execution_context(self, claim: SubmissionClaim) -> ExecutionContext:
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
            attempt_id=None,
            session_state_path=str(
                self._state_root / "session-states" / claim.task_id / "checkpoint.json"
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
        claim = self._execution.claim_next_submission()
        if claim is None:
            return False
        self._execution.begin_delivery(claim.submission_id)
        context = self._context_factory(claim)
        adapter = self._adapter_factory(context.engine_type)
        execution: RuntimeExecutionClaim | None = None
        terminal_status: TurnStatus | None = None
        failure_code: str | None = None

        async def emit(event: EngineEvent) -> None:
            nonlocal execution, terminal_status, failure_code
            if execution is None:
                native_kind, native_ref = adapter.native_turn_identity(
                    runtime_launch_key=claim.submission_id,
                    fallback_turn_id=claim.reserved_turn_id,
                )
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
        try:
            while not run.done():
                await self._consume_controls(adapter, claim, execution)
                await asyncio.sleep(0.05)
            await run
        except asyncio.CancelledError:
            terminal_status = TurnStatus.INTERRUPTED
        except Exception:
            terminal_status = TurnStatus.FAILED
            failure_code = failure_code or "runtime_error"
        if execution is None:
            raise RuntimeError("Engine ended before producing provider-acceptance evidence")
        terminal_status = terminal_status or TurnStatus.COMPLETED
        self._execution.finish_execution(
            execution,
            status=terminal_status,
            failure_code=failure_code,
            evidence={"source": "engine_terminal"},
        )
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
                    self._execution.transition_control(
                        control_id,
                        expected_status="requested",
                        status="rejected",
                        evidence={"reason": "steer text is missing"},
                        failure_code="invalid_control_payload",
                    )
                    continue
                receipt = await adapter.steer_turn(
                    task_id=claim.task_id,
                    expected_turn_id=execution.turn_id,
                    text=text,
                    runtime_launch_key=claim.submission_id,
                )
            else:
                receipt = await adapter.interrupt_turn(
                    task_id=claim.task_id,
                    expected_turn_id=execution.turn_id,
                    runtime_launch_key=claim.submission_id,
                )
            self._execution.transition_control(
                control_id,
                expected_status="requested",
                status="accepted" if receipt.accepted else "rejected",
                evidence=dict(receipt.evidence),
                failure_code=None if receipt.accepted else "capability_unsupported",
            )

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

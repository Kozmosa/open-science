from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shlex
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ainrf.environments.models import utc_now
from ainrf.harness_engine.base import (
    EngineEmit,
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
)
from ainrf.harness_engine.session_state import SessionCheckpoint

logger = logging.getLogger(__name__)

_DEFAULT_APP_SERVER_COMMAND = "codex app-server --listen stdio://"
_CLIENT_INFO = {
    "name": "ainrf",
    "title": "AINRF Harness Engine",
    "version": "0.1.0",
}


@dataclass(slots=True)
class CodexSession:
    task_id: str
    abort_event: asyncio.Event = field(default_factory=asyncio.Event)
    pause_requested: bool = False
    pending_prompts: deque[str] = field(default_factory=deque)
    thread_id: str | None = None
    turn_id: str | None = None
    turn_count: int = 0
    total_cost_usd: float = 0.0
    had_error: bool = False
    terminal_emitted: bool = False
    request_seq: int = 1
    process: asyncio.subprocess.Process | None = None
    reader_task: asyncio.Task[None] | None = None
    initialized: bool = False
    turn_done: asyncio.Event = field(default_factory=asyncio.Event)
    turn_status: str | None = None
    approvals: dict[int, str] = field(default_factory=dict)
    pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)


class CodexAppServerEngine(HarnessEngine):
    """Codex App Server JSON-RPC stdio engine."""

    def __init__(self) -> None:
        self._sessions: dict[str, CodexSession] = {}
        self._lock = asyncio.Lock()

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CODEX_APP_SERVER

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        async with self._lock:
            session = self._sessions.get(context.task_id)
            is_new_session = session is None
            if session is None:
                session = CodexSession(task_id=context.task_id)
                self._sessions[context.task_id] = session
            session.had_error = False
            session.terminal_emitted = False
            session.abort_event.clear()
            session.turn_done.clear()
            session.turn_status = None

        if context.session_state_path and is_new_session:
            self._restore_checkpoint(context, session)

        prompt = self._resolve_prompt(context, session) or "Continue from where you left off."
        await self._ensure_connection(context, session, emit)
        if session.thread_id is None:
            await self._start_thread(context, session)
        else:
            await self._resume_thread(context, session)
        await self._start_turn(context, session, prompt)
        if session.pause_requested and session.turn_id is not None:
            await self._interrupt_turn(session)
        await self._await_turn(context, session)

    async def pause(self, task_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is None:
                session = CodexSession(task_id=task_id)
                self._sessions[task_id] = session
            session.pause_requested = True
            should_interrupt = session.thread_id is not None and session.turn_id is not None
        if should_interrupt:
            await self._interrupt_turn(session)

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        await self.start(context, emit)

    async def send_input(self, task_id: str, text: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is None:
                session = CodexSession(task_id=task_id)
                self._sessions[task_id] = session
            session.pending_prompts.append(text)

    async def cancel(self, task_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(task_id, None)
            if session is not None:
                session.abort_event.set()
        if session is None:
            return
        if session.thread_id is not None and session.turn_id is not None:
            with contextlib.suppress(Exception):
                await self._interrupt_turn(session)
        await self._cleanup_session(session)

    def _restore_checkpoint(self, context: ExecutionContext, session: CodexSession) -> None:
        checkpoint_path = Path(context.session_state_path or "")
        if not checkpoint_path.exists():
            return
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint = SessionCheckpoint(**data)
        metadata = checkpoint.metadata or {}
        thread_id = metadata.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            session.thread_id = thread_id
        turn_id = metadata.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            session.turn_id = turn_id
        session.turn_count = checkpoint.turn_count
        session.total_cost_usd = checkpoint.total_cost_usd
        if checkpoint.pending_prompts:
            session.pending_prompts = deque(checkpoint.pending_prompts)

    def _resolve_prompt(self, context: ExecutionContext, session: CodexSession) -> str:
        if session.pending_prompts:
            return session.pending_prompts.popleft()
        if session.thread_id is not None:
            return "Continue from where you left off."
        return context.rendered_prompt

    async def _ensure_connection(
        self,
        context: ExecutionContext,
        session: CodexSession,
        emit: EngineEmit,
    ) -> None:
        if (
            session.process is not None
            and session.process.returncode is None
            and session.initialized
        ):
            return

        command_text = context.codex_app_server_command or _DEFAULT_APP_SERVER_COMMAND
        command = shlex.split(command_text)
        if not command:
            raise RuntimeError("Codex App Server command is empty")
        if context.tenant_user:
            command = ["sudo", "-u", context.tenant_user, *command]
        env = os.environ.copy()
        if context.codex_base_url:
            env["OPENAI_BASE_URL"] = context.codex_base_url
        if context.codex_api_key:
            env["OPENAI_API_KEY"] = context.codex_api_key
        if context.codex_home_path:
            env["CODEX_HOME"] = context.codex_home_path

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.working_directory,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("Failed to establish Codex App Server stdio pipes")

        session.command = command
        session.process = process
        session.initialized = False
        session.reader_task = asyncio.create_task(self._read_loop(session, emit))
        try:
            await self._rpc_request(
                session,
                "initialize",
                {"clientInfo": _CLIENT_INFO, "capabilities": {"experimentalApi": True}},
            )
            await self._rpc_notify(session, "initialized", {})
            session.initialized = True
        except Exception:
            await self._cleanup_session(session)
            raise

    async def _read_loop(self, session: CodexSession, emit: EngineEmit) -> None:
        assert session.process is not None
        assert session.process.stdout is not None
        assert session.process.stderr is not None
        stderr = session.process.stderr

        async def read_stderr() -> None:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                await emit(
                    EngineEvent(
                        event_type="system",
                        payload={
                            "subtype": "codex_stderr",
                            "content": line.decode("utf-8", errors="replace"),
                        },
                    )
                )

        stderr_task = asyncio.create_task(read_stderr())
        try:
            while True:
                line = await session.process.stdout.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    logger.warning("Codex App Server: ignoring non-JSON stdout line: %s", exc)
                    continue
                if not isinstance(payload, dict):
                    logger.warning("Codex App Server: ignoring non-dict payload: %s", type(payload))
                    continue
                await self._handle_message(session, payload, emit)
        finally:
            self._fail_pending_requests(
                session,
                RuntimeError("Codex App Server terminated before completing the request"),
            )
            if not session.turn_done.is_set():
                session.turn_status = session.turn_status or "failed"
                session.turn_done.set()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task

    async def _handle_message(
        self,
        session: CodexSession,
        payload: dict[str, Any],
        emit: EngineEmit,
    ) -> None:
        if "id" in payload and ("result" in payload or "error" in payload):
            request_id = int(payload["id"])
            future = session.pending_requests.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(payload)
            session.approvals.pop(request_id, None)
            return
        if "id" in payload and "method" in payload:
            await self._handle_server_request(session, payload, emit)
            return

        method = payload.get("method")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}

        if method == "thread/started":
            thread = params.get("thread", {})
            if isinstance(thread, dict):
                thread_id = thread.get("id")
                if isinstance(thread_id, str):
                    session.thread_id = thread_id
            await emit(
                EngineEvent(event_type="system", payload={"subtype": "task_started", **params})
            )
            return
        if method == "turn/started":
            turn = params.get("turn", {})
            if isinstance(turn, dict):
                turn_id = turn.get("id")
                if isinstance(turn_id, str):
                    session.turn_id = turn_id
            await emit(
                EngineEvent(event_type="system", payload={"subtype": "turn_started", **params})
            )
            return
        if method == "turn/completed":
            await self._handle_turn_completed(session, params, emit)
            return
        if method == "item/started":
            await self._handle_item_started(params, emit)
            return
        if method == "item/completed":
            await self._handle_item_completed(params, emit)
            return
        if method == "item/agentMessage/delta":
            return
        if method in {"item/reasoning/summaryTextDelta", "item/reasoning/textDelta"}:
            await emit(
                EngineEvent(event_type="thinking", payload={"content": params.get("delta", "")})
            )
            return
        if method == "item/commandExecution/outputDelta":
            await emit(
                EngineEvent(
                    event_type="tool_result",
                    payload={
                        "tool_use_id": params.get("itemId"),
                        "content": params.get("delta", ""),
                        "tool_name": "commandExecution",
                    },
                )
            )
            return
        if method == "serverRequest/resolved":
            await emit(
                EngineEvent(
                    event_type="system",
                    payload={"subtype": "server_request_resolved", **params},
                )
            )

    async def _handle_turn_completed(
        self,
        session: CodexSession,
        params: dict[str, Any],
        emit: EngineEmit,
    ) -> None:
        turn = params.get("turn", {})
        if isinstance(turn, dict):
            turn_id = turn.get("id")
            if isinstance(turn_id, str):
                session.turn_id = turn_id
            status = turn.get("status")
            if isinstance(status, str):
                session.turn_status = status
        session.turn_done.set()
        if session.turn_status == "failed":
            session.had_error = True
            await emit(
                EngineEvent(event_type="system", payload={"subtype": "task_failed", "turn": turn})
            )
            await emit(
                EngineEvent(event_type="status", payload={"status": "failed", "exit_code": None})
            )
        elif session.turn_status == "interrupted" and session.pause_requested:
            await emit(
                EngineEvent(event_type="system", payload={"subtype": "task_paused", "turn": turn})
            )
        else:
            session.terminal_emitted = True
            await emit(
                EngineEvent(
                    event_type="system", payload={"subtype": "task_completed", "turn": turn}
                )
            )
            await emit(
                EngineEvent(event_type="status", payload={"status": "succeeded", "exit_code": 0})
            )

    async def _handle_server_request(
        self,
        session: CodexSession,
        payload: dict[str, Any],
        emit: EngineEmit,
    ) -> None:
        request_id = int(payload["id"])
        method = payload.get("method")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}
        session.approvals[request_id] = str(method)

        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
        }:
            await emit(
                EngineEvent(
                    event_type="system",
                    payload={"subtype": "approval_requested", "method": method, **params},
                )
            )
            await self._rpc_response(session, request_id, {"decision": "accept"})
            return

        await emit(
            EngineEvent(
                event_type="system",
                payload={"subtype": "unhandled_server_request", "method": method, **params},
            )
        )
        await self._rpc_response(session, request_id, {"decision": "cancel"})

    async def _handle_item_started(self, params: dict[str, Any], emit: EngineEmit) -> None:
        item = params.get("item", {})
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type == "userMessage":
            return
        if item_type == "commandExecution":
            await emit(
                EngineEvent(
                    event_type="tool_call",
                    payload={
                        "id": item.get("id"),
                        "name": "commandExecution",
                        "arguments": {"command": item.get("command"), "cwd": item.get("cwd")},
                    },
                )
            )
        elif item_type == "fileChange":
            await emit(
                EngineEvent(
                    event_type="tool_call",
                    payload={
                        "id": item.get("id"),
                        "name": "fileChange",
                        "arguments": {"changes": item.get("changes")},
                    },
                )
            )

    async def _handle_item_completed(self, params: dict[str, Any], emit: EngineEmit) -> None:
        item = params.get("item", {})
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type == "agentMessage":
            text = item.get("text")
            if isinstance(text, str) and text:
                await emit(
                    EngineEvent(
                        event_type="message", payload={"role": "assistant", "content": text}
                    )
                )
        elif item_type == "plan":
            text = item.get("text")
            if isinstance(text, str) and text:
                await emit(EngineEvent(event_type="thinking", payload={"content": text}))
        elif item_type in {"commandExecution", "fileChange"}:
            await emit(
                EngineEvent(
                    event_type="tool_result",
                    payload={
                        "tool_use_id": item.get("id"),
                        "content": item,
                        "is_error": item.get("status") in {"failed", "declined"},
                    },
                )
            )

    async def _start_thread(self, context: ExecutionContext, session: CodexSession) -> None:
        params: dict[str, Any] = {
            "cwd": context.working_directory,
            "approvalPolicy": context.codex_approval_policy or "never",
            "personality": "pragmatic",
            "sandbox": "danger-full-access",
        }
        model = context.codex_model or context.model
        if model:
            params["model"] = model
        result = await self._rpc_request(session, "thread/start", params)
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
            if isinstance(thread_id, str):
                session.thread_id = thread_id

    async def _resume_thread(self, context: ExecutionContext, session: CodexSession) -> None:
        if session.thread_id is None:
            raise RuntimeError("Cannot resume Codex thread without thread id")
        params: dict[str, Any] = {
            "threadId": session.thread_id,
            "cwd": context.working_directory,
            "approvalPolicy": context.codex_approval_policy or "never",
            "personality": "pragmatic",
            "excludeTurns": True,
            "sandbox": "danger-full-access",
        }
        model = context.codex_model or context.model
        if model:
            params["model"] = model
        await self._rpc_request(session, "thread/resume", params)

    async def _start_turn(
        self,
        context: ExecutionContext,
        session: CodexSession,
        prompt: str,
    ) -> None:
        if session.thread_id is None:
            raise RuntimeError("Cannot start turn without thread id")
        session.turn_done.clear()
        result = await self._rpc_request(
            session,
            "turn/start",
            {
                "threadId": session.thread_id,
                "approvalPolicy": context.codex_approval_policy or "never",
                "input": [{"type": "text", "text": prompt}],
                "sandboxPolicy": {"type": "dangerFullAccess"},
            },
        )
        turn = result.get("turn", {})
        if isinstance(turn, dict):
            turn_id = turn.get("id")
            if isinstance(turn_id, str):
                session.turn_id = turn_id

    async def _interrupt_turn(self, session: CodexSession) -> None:
        if session.thread_id is None or session.turn_id is None:
            return
        await self._rpc_request(
            session,
            "turn/interrupt",
            {"threadId": session.thread_id, "turnId": session.turn_id},
        )

    async def _await_turn(self, context: ExecutionContext, session: CodexSession) -> None:
        await session.turn_done.wait()
        if session.abort_event.is_set():
            raise asyncio.CancelledError("Task aborted")
        if session.turn_status == "failed":
            raise RuntimeError("Codex App Server turn failed")
        if session.pause_requested:
            session.pause_requested = False
        session.turn_count += 1
        await self._save_checkpoint(context, session)

    async def _save_checkpoint(self, context: ExecutionContext, session: CodexSession) -> None:
        if not context.session_state_path:
            return
        checkpoint_path = Path(context.session_state_path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint = SessionCheckpoint(
            task_id=session.task_id,
            session_id=session.thread_id,
            cwd=context.working_directory,
            created_at=utc_now().isoformat(),
            turn_count=session.turn_count,
            total_cost_usd=session.total_cost_usd,
            pending_prompts=list(session.pending_prompts),
            metadata={
                "thread_id": session.thread_id,
                "turn_id": session.turn_id,
                "command": session.command,
            },
        )
        checkpoint_path.write_text(
            json.dumps(asdict(checkpoint), indent=2),
            encoding="utf-8",
        )

    async def _rpc_request(
        self,
        session: CodexSession,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = session.request_seq
        session.request_seq += 1
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[dict[str, Any]] = loop.create_future()
        session.pending_requests[request_id] = response_future
        await self._write_json(session, {"id": request_id, "method": method, "params": params})
        payload = await response_future
        if "error" in payload:
            raise RuntimeError(f"Codex App Server error for {method}: {payload['error']}")
        result = payload.get("result", {})
        return result if isinstance(result, dict) else {}

    async def _rpc_notify(self, session: CodexSession, method: str, params: dict[str, Any]) -> None:
        await self._write_json(session, {"method": method, "params": params})

    async def _rpc_response(
        self,
        session: CodexSession,
        request_id: int,
        result: dict[str, Any],
    ) -> None:
        await self._write_json(session, {"id": request_id, "result": result})

    async def _write_json(self, session: CodexSession, payload: dict[str, Any]) -> None:
        if session.process is None or session.process.stdin is None:
            raise RuntimeError("Codex App Server stdin unavailable")
        session.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await session.process.stdin.drain()

    async def _cleanup_session(self, session: CodexSession) -> None:
        self._fail_pending_requests(session, RuntimeError("Codex App Server session closed"))
        if session.reader_task is not None:
            session.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.reader_task
            session.reader_task = None
        if session.process is not None:
            if session.process.returncode is None:
                session.process.terminate()
                await session.process.wait()
            session.process = None
        session.initialized = False

    @staticmethod
    def _extract_user_text(item: dict[str, Any]) -> str:
        content = item.get("content", [])
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _fail_pending_requests(session: CodexSession, error: Exception) -> None:
        for future in session.pending_requests.values():
            if not future.done():
                future.set_exception(error)
        session.pending_requests.clear()

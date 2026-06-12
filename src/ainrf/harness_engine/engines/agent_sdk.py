from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    UserMessage,
)
from claude_agent_sdk import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import (
    McpHttpServerConfig,
    McpSdkServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
    PermissionResultAllow,
    SandboxSettings,
    ToolPermissionContext,
)

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

McpServerConfig = (
    McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig
)
_ANTHROPIC_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)

_IGNORED_SYSTEM_SUBTYPES = frozenset({"status", "thinking_tokens"})



def _build_token_usage(sdk_msg: object) -> dict[str, Any] | None:
    """Build token_usage dict from SDK ResultMessage."""
    usage = getattr(sdk_msg, "usage", None)
    if not usage:
        return None
    result: dict[str, Any] = {
        "total": dict(usage),
        "source": "agent-sdk",
    }
    total_cost = getattr(sdk_msg, "total_cost_usd", None) or 0.0
    total = result["total"]
    if isinstance(total, dict) and "cost_usd" not in total:
        total["cost_usd"] = float(total_cost)
    model_usage = getattr(sdk_msg, "model_usage", None)
    if model_usage:
        result["by_model"] = dict(model_usage)
    return result


@dataclass(slots=True)
class AgentSession:
    task_id: str
    abort_event: asyncio.Event = field(default_factory=asyncio.Event)
    should_pause_after_turn: bool = False
    pending_prompts: deque[str] = field(default_factory=deque)
    session_id: str | None = None
    turn_count: int = 0
    total_cost_usd: float = 0.0
    had_error: bool = False
    terminal_emitted: bool = False
    # Streaming state: track current content block being accumulated
    stream_block_index: int = -1
    stream_block_type: str | None = None  # "thinking" or "text"
    stream_block_accumulated: str = ""

class AgentSdkEngine(HarnessEngine):
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = asyncio.Lock()
        self._run_lock = asyncio.Lock()

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.AGENT_SDK

    def _provider_env(self, context: ExecutionContext) -> dict[str, str]:
        env: dict[str, str] = {}
        if context.api_base_url is not None:
            env["ANTHROPIC_BASE_URL"] = context.api_base_url
        if context.api_key is not None:
            has_auth_token_override = (
                context.env_overrides is not None
                and "ANTHROPIC_AUTH_TOKEN" in context.env_overrides
            )
            if has_auth_token_override:
                env["ANTHROPIC_AUTH_TOKEN"] = context.api_key
            else:
                env["ANTHROPIC_API_KEY"] = context.api_key
                env["ANTHROPIC_AUTH_TOKEN"] = context.api_key
        if context.default_opus_model is not None:
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = context.default_opus_model
        if context.default_sonnet_model is not None:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = context.default_sonnet_model
        if context.default_haiku_model is not None:
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = context.default_haiku_model
        if context.env_overrides is not None:
            env.update(context.env_overrides)
        return env

    def _implicit_provider_env_keys(self, context: ExecutionContext) -> tuple[str, ...]:
        has_explicit_provider = any(
            value
            for value in (
                context.api_base_url,
                context.api_key,
                context.default_opus_model,
                context.default_sonnet_model,
                context.default_haiku_model,
            )
        ) or any(key in (context.env_overrides or {}) for key in _ANTHROPIC_PROVIDER_ENV_KEYS)
        return () if has_explicit_provider else _ANTHROPIC_PROVIDER_ENV_KEYS

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        async with self._lock:
            session = self._sessions.get(context.task_id)
            is_new_session = session is None
            if session is None:
                session = AgentSession(task_id=context.task_id)
                self._sessions[context.task_id] = session
            session.had_error = False
            session.terminal_emitted = False
            session.abort_event.clear()

        if context.session_state_path and is_new_session:
            checkpoint_path = Path(context.session_state_path)
            if checkpoint_path.exists():
                data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint = SessionCheckpoint(**data)
                session.session_id = checkpoint.session_id
                session.turn_count = checkpoint.turn_count
                session.total_cost_usd = checkpoint.total_cost_usd
                if checkpoint.pending_prompts:
                    session.pending_prompts = deque(checkpoint.pending_prompts)

        prompt = self._resolve_prompt(context, session)
        prompt_stream = self._wrap_prompt_stream(prompt)
        permission_mode = cast(
            Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]
            | None,
            context.permission_mode or "bypassPermissions",
        )
        mcp_servers: dict[str, McpServerConfig] | str | Path = context.mcp_servers or {}
        # Skills go to the `skills` parameter; allowed_tools includes skills
        # plus built-in tools (WebSearch, Fetch) so agents can search the web.
        skills = context.skills or []
        allowed_tools = list(skills)
        options = ClaudeAgentOptions(
            model=context.model or "claude-sonnet-4-5",
            system_prompt=context.system_prompt,
            permission_mode=permission_mode,
            cwd=context.working_directory,
            resume=session.session_id,
            max_turns=context.max_turns,
            max_budget_usd=context.max_budget_usd,
            mcp_servers=mcp_servers,
            skills=skills,
            allowed_tools=allowed_tools,
            hooks={
                "PostToolUse": [HookMatcher(hooks=[self._post_tool_use_hook(emit)])],
                "Notification": [HookMatcher(hooks=[self._notification_hook(emit)])],
            },
            include_partial_messages=True,
            can_use_tool=self._can_use_tool,
            sandbox=self._build_sandbox_settings(),
            # NOTE: We intentionally do NOT pass user=context.tenant_user here.
            # The SDK's `user` param uses subprocess.Popen(user=...) which calls
            # os.setuid() internally — that requires CAP_SETUID which ainrf (uid=1000)
            # does not have.  Tenant isolation is instead handled by the Claude Code
            # engine via `sudo -u <tenant>`.
        )

        async with self._run_lock:
            env_overrides = self._provider_env(context)
            saved_env: dict[str, str | None] = {}
            for key in self._implicit_provider_env_keys(context):
                saved_env[key] = os.environ.get(key)
                os.environ.pop(key, None)
            for key, value in env_overrides.items():
                saved_env[key] = os.environ.get(key)
                os.environ[key] = value
            try:
                await self._run_query(context, session, prompt_stream, options, emit)
            finally:
                for key, value in saved_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,  # noqa: ARG002
    ) -> PermissionResultAllow:
        """Permission callback for tool calls that require approval.

        Currently a dummy that always allows. Future: integrate with WebUI
        approval flow so users can approve/deny tool calls from the browser.
        """
        _ = tool_name, tool_input
        return PermissionResultAllow()

    @staticmethod
    async def _wrap_prompt_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Wrap a string prompt into an async iterable for SDK streaming mode.

        The can_use_tool callback requires the prompt to be an AsyncIterable
        rather than a plain string. This helper converts a resolved string
        prompt into the single-message stream format expected by the SDK.
        """
        yield {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
        }

    def _build_sandbox_settings(self) -> SandboxSettings | None:
        """Build sandbox settings when bwrap is available on the system.

        Enables the Claude Code sandbox (bubblewrap) for bash command
        isolation. When the sandbox is active, bash commands are
        auto-approved (``autoAllowBashIfSandboxed``), which avoids
        per-command permission prompts without fully bypassing isolation.

        Returns ``None`` when bwrap is not installed (e.g. local dev).
        """
        if shutil.which("bwrap") is None:
            return None
        return SandboxSettings(
            enabled=True,
            autoAllowBashIfSandboxed=True,
            enableWeakerNestedSandbox=True,
        )

    def _resolve_prompt(self, context: ExecutionContext, session: AgentSession) -> str:
        if session.pending_prompts:
            return session.pending_prompts.popleft()
        if session.session_id is not None:
            return "Continue from where you left off."
        return context.rendered_prompt

    async def _run_query(
        self,
        context: ExecutionContext,
        session: AgentSession,
        prompt: AsyncIterator[dict[str, Any]],
        options: ClaudeAgentOptions,
        emit: EngineEmit,
    ) -> None:
        try:
            async for sdk_msg in query(prompt=prompt, options=options):
                if session.abort_event.is_set():
                    break
                for event in self._convert_sdk_message(sdk_msg, session):
                    await emit(event)

            if session.abort_event.is_set():
                raise asyncio.CancelledError("Task aborted")
            if session.had_error and not session.terminal_emitted:
                raise RuntimeError("Agent SDK session completed with errors")

            if session.should_pause_after_turn:
                session.should_pause_after_turn = False
                await emit(
                    EngineEvent(
                        event_type="system",
                        payload={"subtype": "task_paused", "task_id": context.task_id},
                    )
                )
            elif not session.terminal_emitted:
                await emit(
                    EngineEvent(
                        event_type="system",
                        payload={"subtype": "task_completed", "task_id": context.task_id},
                    )
                )
                await emit(
                    EngineEvent(
                        event_type="status",
                        payload={"status": "succeeded", "exit_code": 0},
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            session.had_error = True
            if not session.terminal_emitted:
                await emit(
                    EngineEvent(
                        event_type="error",
                        payload={"message": str(exc), "task_id": context.task_id},
                    )
                )
                await emit(
                    EngineEvent(
                        event_type="status",
                        payload={"status": "failed", "exit_code": None},
                    )
                )
            raise
        finally:
            await self._save_checkpoint(context, session)
            if session.abort_event.is_set():
                async with self._lock:
                    self._sessions.pop(context.task_id, None)

    async def pause(self, task_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is None:
                session = AgentSession(task_id=task_id)
                self._sessions[task_id] = session
            session.should_pause_after_turn = True

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        await self.start(context, emit)

    async def send_input(self, task_id: str, text: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is None:
                session = AgentSession(task_id=task_id)
                self._sessions[task_id] = session
            session.pending_prompts.append(text)

    async def cancel(self, task_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is not None:
                session.abort_event.set()

    def _convert_sdk_message(self, sdk_msg: object, session: AgentSession) -> list[EngineEvent]:
        events: list[EngineEvent] = []
        if isinstance(sdk_msg, AssistantMessage):
            return self._convert_assistant_message(sdk_msg)
        if isinstance(sdk_msg, UserMessage):
            return []
        if isinstance(sdk_msg, SystemMessage):
            subtype = sdk_msg.subtype
            if subtype == "init":
                return [
                    EngineEvent(
                        event_type="system",
                        payload={
                            "subtype": "task_started",
                            "session_id": sdk_msg.data.get("session_id"),
                        },
                    )
                ]
            if subtype in _IGNORED_SYSTEM_SUBTYPES:
                return []
            return [
                EngineEvent(
                    event_type="system",
                    payload={"subtype": subtype, "data": sdk_msg.data},
                )
            ]
        if isinstance(sdk_msg, ResultMessage):
            return self._convert_result_message(sdk_msg, session)
        if isinstance(sdk_msg, StreamEvent):
            return self._convert_stream_event(sdk_msg, session)
        if isinstance(sdk_msg, RateLimitEvent):
            return [
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "rate_limit",
                        "rate_limit_info": sdk_msg.rate_limit_info,
                    },
                )
            ]
        return events

    def _convert_stream_event(self, sdk_msg: StreamEvent, session: AgentSession) -> list[EngineEvent]:
        """Convert raw Anthropic streaming events into incremental thinking/text events.

        Emits partial events with block_id so the frontend can update a single
        thinking bubble in real-time instead of waiting for the full block.
        """
        raw = sdk_msg.event
        event_type = raw.get("type")
        events: list[EngineEvent] = []

        if event_type == "content_block_start":
            block = raw.get("content_block") or {}
            block_type = block.get("type")
            block_index = raw.get("index", 0)
            session.stream_block_index = block_index
            session.stream_block_type = block_type
            session.stream_block_accumulated = ""

        elif event_type == "content_block_delta":
            delta = raw.get("delta") or {}
            delta_type = delta.get("type")

            if delta_type == "thinking_delta" and session.stream_block_type == "thinking":
                delta_text = delta.get("thinking", "")
                session.stream_block_accumulated += delta_text
                events.append(
                    EngineEvent(
                        event_type="thinking",
                        payload={
                            "content": delta_text,
                            "block_id": f"thinking-{session.stream_block_index}",
                            "is_partial": True,
                            "is_delta": True,
                        },
                    )
                )
            elif delta_type == "text_delta" and session.stream_block_type == "text":
                delta_text = delta.get("text", "")
                session.stream_block_accumulated += delta_text
                events.append(
                    EngineEvent(
                        event_type="message",
                        payload={
                            "role": "assistant",
                            "content": delta_text,
                            "block_id": f"text-{session.stream_block_index}",
                            "is_partial": True,
                            "is_delta": True,
                        },
                    )
                )

        elif event_type == "content_block_stop":
            if session.stream_block_type == "thinking":
                events.append(
                    EngineEvent(
                        event_type="thinking",
                        payload={
                            "content": session.stream_block_accumulated,
                            "block_id": f"thinking-{session.stream_block_index}",
                            "is_partial": False,
                        },
                    )
                )
            elif session.stream_block_type == "text":
                events.append(
                    EngineEvent(
                        event_type="message",
                        payload={
                            "role": "assistant",
                            "content": session.stream_block_accumulated,
                            "block_id": f"text-{session.stream_block_index}",
                            "is_partial": False,
                        },
                    )
                )
            session.stream_block_index = -1
            session.stream_block_type = None
            session.stream_block_accumulated = ""

        return events

    def _convert_assistant_message(self, sdk_msg: AssistantMessage) -> list[EngineEvent]:
        events: list[EngineEvent] = []
        for block in sdk_msg.content:
            # Skip thinking/text blocks — already emitted via StreamEvent deltas
            if isinstance(block, (ThinkingBlock, TextBlock)):
                continue
            elif isinstance(block, ToolUseBlock):
                events.append(
                    EngineEvent(
                        event_type="tool_call",
                        payload={"id": block.id, "name": block.name, "arguments": block.input},
                    )
                )
            elif isinstance(block, ToolResultBlock):
                events.append(
                    EngineEvent(
                        event_type="tool_result",
                        payload={
                            "tool_use_id": block.tool_use_id,
                            "content": block.content,
                            "is_error": block.is_error,
                        },
                    )
                )
        usage = getattr(sdk_msg, "usage", None)
        if usage:
            events.append(
                EngineEvent(
                    event_type="token",
                    payload={"turn": len(events)},
                    token_usage={"total": dict(usage), "source": "agent-sdk"},
                )
            )
        return events

    def _convert_result_message(
        self,
        sdk_msg: ResultMessage,
        session: AgentSession,
    ) -> list[EngineEvent]:
        session.session_id = sdk_msg.session_id
        session.turn_count += sdk_msg.num_turns or 0
        session.total_cost_usd += sdk_msg.total_cost_usd or 0.0
        session.terminal_emitted = True
        if sdk_msg.is_error:
            session.had_error = True
            return [
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "task_failed",
                        "session_id": sdk_msg.session_id,
                        "num_turns": sdk_msg.num_turns,
                        "total_cost_usd": sdk_msg.total_cost_usd,
                        "errors": sdk_msg.errors,
                    },
                    token_usage=_build_token_usage(sdk_msg),
                ),
                EngineEvent(
                    event_type="status",
                    payload={"status": "failed", "exit_code": None},
                ),
            ]
        return [
            EngineEvent(
                event_type="system",
                payload={
                    "subtype": "task_completed",
                    "session_id": sdk_msg.session_id,
                    "num_turns": sdk_msg.num_turns,
                    "total_cost_usd": sdk_msg.total_cost_usd,
                },
                token_usage=_build_token_usage(sdk_msg),
            ),
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            ),
        ]

    def _post_tool_use_hook(self, emit: EngineEmit):
        async def hook(
            input_data: dict[str, Any],
            tool_use_id: str,
            context: object,
        ) -> dict[str, Any]:
            _ = context
            await emit(
                EngineEvent(
                    event_type="tool_result",
                    payload={
                        "tool_name": input_data.get("tool_name"),
                        "tool_input": input_data.get("tool_input"),
                        "tool_response": input_data.get("tool_response"),
                        "tool_use_id": tool_use_id,
                    },
                )
            )
            return {}

        return hook

    def _notification_hook(self, emit: EngineEmit):
        async def hook(
            input_data: dict[str, Any],
            tool_use_id: str,
            context: object,
        ) -> dict[str, Any]:
            _ = tool_use_id
            _ = context
            await emit(
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "notification",
                        "message": input_data.get("message"),
                        "title": input_data.get("title"),
                        "notification_type": input_data.get("notification_type"),
                    },
                )
            )
            return {}

        return hook

    async def _save_checkpoint(self, context: ExecutionContext, session: AgentSession) -> None:
        if not context.session_state_path:
            return
        checkpoint_path = Path(context.session_state_path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint = SessionCheckpoint(
            task_id=session.task_id,
            session_id=session.session_id,
            cwd=context.working_directory,
            created_at=utc_now().isoformat(),
            turn_count=session.turn_count,
            total_cost_usd=session.total_cost_usd,
            pending_prompts=list(session.pending_prompts),
        )
        try:
            checkpoint_path.write_text(
                json.dumps(asdict(checkpoint), indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save checkpoint for %s: %s", session.task_id, exc)

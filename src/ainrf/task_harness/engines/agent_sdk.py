from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    UserMessage,
    StreamEvent,
    RateLimitEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from .base import EngineContext, EngineEvent, ExecutionEngine
from ainrf.environments.models import utc_now
from ainrf.task_harness.session_state import SessionCheckpoint

logger = logging.getLogger(__name__)


@dataclass
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


@contextmanager
def _env_override(overrides: dict[str, str | None]) -> Iterator[None]:
    """Temporarily override process environment variables.

    WARNING: This mutates the global os.environ dict. The AgentSdkEngine
    uses a class-level asyncio.Lock (_run_lock) to serialize execution
    and prevent env var cross-contamination between concurrent tasks.
    This design limits agent-sdk tasks to one-at-a-time per process.
    """
    keys = [k for k, v in overrides.items() if v is not None]
    if not keys:
        yield
        return
    original: dict[str, str | None] = {}
    for key in keys:
        original[key] = os.environ.get(key)
        os.environ[key] = overrides[key]  # type: ignore[index]
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AgentSdkEngine(ExecutionEngine):
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = asyncio.Lock()
        self._run_lock = asyncio.Lock()

    def _provider_env(self, context: EngineContext) -> dict[str, str | None]:
        """Build env var overrides from agent profile for provider routing."""
        profile = context.agent_profile
        env: dict[str, str | None] = {}
        if profile.api_base_url is not None:
            env["ANTHROPIC_BASE_URL"] = profile.api_base_url
        if profile.api_key is not None:
            # If user explicitly sets ANTHROPIC_AUTH_TOKEN via env_overrides,
            # don't set ANTHROPIC_API_KEY — some providers (e.g. LongCat) only
            # accept Bearer auth and will 401 on x-api-key.
            has_auth_token_override = (
                profile.env_overrides is not None
                and "ANTHROPIC_AUTH_TOKEN" in profile.env_overrides
            )
            if has_auth_token_override:
                env["ANTHROPIC_AUTH_TOKEN"] = profile.api_key
            else:
                env["ANTHROPIC_API_KEY"] = profile.api_key
                # Also set ANTHROPIC_AUTH_TOKEN for providers that use Bearer auth
                env["ANTHROPIC_AUTH_TOKEN"] = profile.api_key
        if profile.default_opus_model is not None:
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = profile.default_opus_model
        if profile.default_sonnet_model is not None:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = profile.default_sonnet_model
        if profile.default_haiku_model is not None:
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = profile.default_haiku_model
        if profile.env_overrides is not None:
            for key, value in profile.env_overrides.items():
                env[key] = value
        return env

    async def start(self, context: EngineContext, emit) -> None:
        async with self._lock:
            session = self._sessions.get(context.task_id)
            is_new_session = session is None
            if session is None:
                session = AgentSession(task_id=context.task_id)
                self._sessions[context.task_id] = session
            session.had_error = False
            session.terminal_emitted = False
            session.abort_event.clear()

        # Load checkpoint if available (only for fresh sessions to avoid
        # duplicating prompts already queued in memory).
        if context.session_state_path and is_new_session:
            checkpoint_path = Path(context.session_state_path)
            if checkpoint_path.exists():
                data = json.loads(checkpoint_path.read_text())
                checkpoint = SessionCheckpoint(**data)
                session.session_id = checkpoint.session_id
                session.turn_count = checkpoint.turn_count
                session.total_cost_usd = checkpoint.total_cost_usd
                if checkpoint.pending_prompts:
                    session.pending_prompts = deque(checkpoint.pending_prompts)

        # Determine prompt for this turn
        if session.pending_prompts:
            prompt = session.pending_prompts.popleft()
        elif session.session_id is not None:
            # Resuming a paused session without queued user input;
            # use a continuation prompt so we don't replay the original
            # rendered_prompt and repeat tool side effects.
            prompt = "Continue from where you left off."
        else:
            prompt = context.rendered_prompt

        options = ClaudeAgentOptions(
            model=context.agent_profile.model or "claude-sonnet-4-5",
            system_prompt=context.agent_profile.system_prompt,
            permission_mode=context.agent_profile.permission_mode or "acceptEdits",
            cwd=context.working_directory,
            resume=session.session_id,
            max_turns=context.agent_profile.max_turns,
            max_budget_usd=context.agent_profile.max_budget_usd,
            mcp_servers=context.agent_profile.mcp_servers or {},
            allowed_tools=context.agent_profile.skills or [],
            disallowed_tools=context.agent_profile.disallowed_tools or [],
            hooks={
                "PostToolUse": [HookMatcher(hooks=[self._post_tool_use_hook(emit)])],
                "Notification": [HookMatcher(hooks=[self._notification_hook(emit)])],
            },
            include_partial_messages=True,
        )

        async with self._run_lock:
            with _env_override(self._provider_env(context)):
                try:
                    async for sdk_msg in query(prompt=prompt, options=options):
                        if session.abort_event.is_set():
                            break

                        events = self._convert_sdk_message(sdk_msg, session)
                        for event in events:
                            await emit(event)

                    if session.abort_event.is_set():
                        raise asyncio.CancelledError("Task aborted")

                    if session.had_error:
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
                                event_type="system",
                                payload={"subtype": "task_failed", "task_id": context.task_id},
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

    async def resume(self, context: EngineContext, emit) -> None:
        await self.start(context, emit)

    async def send_prompt(self, task_id: str, prompt: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is None:
                session = AgentSession(task_id=task_id)
                self._sessions[task_id] = session
            session.pending_prompts.append(prompt)

    async def abort(self, task_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(task_id)
            if session is not None:
                session.abort_event.set()

    def _convert_sdk_message(self, sdk_msg, session: AgentSession) -> list[EngineEvent]:
        events: list[EngineEvent] = []

        if isinstance(sdk_msg, AssistantMessage):
            for block in sdk_msg.content:
                if isinstance(block, TextBlock):
                    events.append(
                        EngineEvent(
                            event_type="message",
                            payload={"role": "assistant", "content": block.text},
                        )
                    )
                elif isinstance(block, ThinkingBlock):
                    events.append(
                        EngineEvent(
                            event_type="thinking",
                            payload={"content": block.thinking},
                        )
                    )
                elif isinstance(block, ToolUseBlock):
                    events.append(
                        EngineEvent(
                            event_type="tool_call",
                            payload={
                                "id": block.id,
                                "name": block.name,
                                "arguments": block.input,
                            },
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
            return events

        if isinstance(sdk_msg, UserMessage):
            content = sdk_msg.content
            if isinstance(content, list):
                # Serialize list content to string for simplicity
                content = "\n".join(
                    item.get("text", str(item)) if isinstance(item, dict) else str(item)
                    for item in content
                )
            events.append(
                EngineEvent(
                    event_type="message",
                    payload={"role": "user", "content": content},
                )
            )
            return events

        if isinstance(sdk_msg, SystemMessage):
            if sdk_msg.subtype == "init":
                events.append(
                    EngineEvent(
                        event_type="system",
                        payload={
                            "subtype": "task_started",
                            "session_id": sdk_msg.data.get("session_id"),
                        },
                    )
                )
            else:
                events.append(
                    EngineEvent(
                        event_type="system",
                        payload={"subtype": sdk_msg.subtype, "data": sdk_msg.data},
                    )
                )
            return events

        if isinstance(sdk_msg, ResultMessage):
            session.session_id = sdk_msg.session_id
            session.turn_count += sdk_msg.num_turns or 0
            session.total_cost_usd += sdk_msg.total_cost_usd or 0.0
            session.terminal_emitted = True

            if sdk_msg.is_error:
                session.had_error = True
                events.append(
                    EngineEvent(
                        event_type="system",
                        payload={
                            "subtype": "task_failed",
                            "session_id": sdk_msg.session_id,
                            "num_turns": sdk_msg.num_turns,
                            "total_cost_usd": sdk_msg.total_cost_usd,
                            "errors": sdk_msg.errors,
                        },
                    )
                )
            else:
                events.append(
                    EngineEvent(
                        event_type="system",
                        payload={
                            "subtype": "task_completed",
                            "session_id": sdk_msg.session_id,
                            "num_turns": sdk_msg.num_turns,
                            "total_cost_usd": sdk_msg.total_cost_usd,
                        },
                    )
                )
            return events

        if isinstance(sdk_msg, StreamEvent):
            event_type = sdk_msg.event.get("type")
            if event_type == "content_block_delta":
                delta = sdk_msg.event.get("delta", {})
                text = delta.get("text")
                if text:
                    events.append(
                        EngineEvent(
                            event_type="message",
                            payload={"role": "assistant", "content": text, "streaming": True},
                        )
                    )
            return events

        if isinstance(sdk_msg, RateLimitEvent):
            events.append(
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "rate_limit",
                        "rate_limit_info": sdk_msg.rate_limit_info,
                    },
                )
            )
            return events

        return events

    def _post_tool_use_hook(self, emit):
        async def hook(input_data, tool_use_id, context):
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

    def _notification_hook(self, emit):
        async def hook(input_data, tool_use_id, context):
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

    async def _save_checkpoint(self, context: EngineContext, session: AgentSession) -> None:
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
            checkpoint_path.write_text(json.dumps(asdict(checkpoint), indent=2))
        except OSError as exc:
            logger.warning("Failed to save checkpoint for %s: %s", session.task_id, exc)

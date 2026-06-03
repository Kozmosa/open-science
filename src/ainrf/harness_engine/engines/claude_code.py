from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from ainrf.harness_engine.base import (
    EngineEvent,
    ExecutionContext,
    EngineEmit,
    HarnessEngine,
    HarnessEngineNotSupportedError,
    HarnessEngineType,
)

_SESSION_META_DIR = Path.home() / ".claude" / "usage-data" / "session-meta"
_POLL_TIMEOUT_SEC = 30
_POLL_INTERVAL_SEC = 1.0
_ANTHROPIC_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)


def _find_session_meta(started_at: float) -> dict[str, Any] | None:
    """Find the session-meta file whose start_time is closest to started_at."""
    if not _SESSION_META_DIR.exists():
        return None
    best: dict[str, Any] | None = None
    best_diff = float("inf")
    for path in _SESSION_META_DIR.iterdir():
        if path.suffix != ".json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        meta_start = data.get("start_time")
        if not isinstance(meta_start, int | float):
            continue
        diff = abs(meta_start - started_at)
        if diff < best_diff and diff <= 10:
            best_diff = diff
            best = data
    return best


class ClaudeCodeEngine(HarnessEngine):
    """Claude Code 执行引擎"""

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        started_at = time.time()
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
        ]
        env = os.environ.copy()
        self._remove_implicit_provider_env(env, context)
        if context.api_base_url:
            env["ANTHROPIC_BASE_URL"] = context.api_base_url
        if context.api_key:
            env["ANTHROPIC_API_KEY"] = context.api_key
            env["ANTHROPIC_AUTH_TOKEN"] = context.api_key
        if context.default_opus_model:
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = context.default_opus_model
        if context.default_sonnet_model:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = context.default_sonnet_model
        if context.default_haiku_model:
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = context.default_haiku_model
        if context.env_overrides:
            env.update(context.env_overrides)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.working_directory,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[context.task_id] = process
        stdin = process.stdin
        stdout = process.stdout
        stderr = process.stderr
        if stdin is None or stdout is None or stderr is None:
            raise RuntimeError("Claude Code engine failed to attach stdio pipes")

        try:
            if context.rendered_prompt:
                stdin.write(context.rendered_prompt.encode())
                await stdin.drain()
            stdin.close()

            await emit(
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "task_started",
                        "command": command,
                        "cwd": context.working_directory,
                    },
                )
            )

            async def read_stream(
                stream: asyncio.StreamReader,
                kind: str,
                role: str,
            ) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    content = line.decode("utf-8", errors="replace")
                    if kind == "stderr":
                        await emit(
                            EngineEvent(
                                event_type="error",
                                payload={"content": content, "stream": kind},
                            )
                        )
                    else:
                        await emit(
                            EngineEvent(
                                event_type="message",
                                payload={"role": role, "kind": kind, "content": content},
                            )
                        )

            await asyncio.gather(
                read_stream(stdout, "stdout", "assistant"),
                read_stream(stderr, "stderr", "system"),
            )
            await process.wait()

            token_usage = await self._poll_session_meta(started_at)
            status = "succeeded" if process.returncode == 0 else "failed"
            await emit(
                EngineEvent(
                    event_type="system",
                    payload={"subtype": f"task_{status}", "returncode": process.returncode},
                    token_usage=token_usage,
                )
            )
            await emit(
                EngineEvent(
                    event_type="status",
                    payload={"status": status, "exit_code": process.returncode},
                )
            )
        finally:
            self._processes.pop(context.task_id, None)
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def cancel(self, task_id: str) -> None:
        process = self._processes.get(task_id)
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    def _remove_implicit_provider_env(
        self,
        env: dict[str, str],
        context: ExecutionContext,
    ) -> None:
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
        if has_explicit_provider:
            return
        for key in _ANTHROPIC_PROVIDER_ENV_KEYS:
            env.pop(key, None)

    async def _poll_session_meta(self, started_at: float) -> dict[str, Any] | None:
        deadline = time.time() + _POLL_TIMEOUT_SEC
        while time.time() < deadline:
            meta = _find_session_meta(started_at)
            if meta is not None:
                input_tokens = meta.get("input_tokens", 0)
                output_tokens = meta.get("output_tokens", 0)
                if input_tokens or output_tokens:
                    return {
                        "total": {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        },
                        "source": "claude-session-meta",
                    }
            await asyncio.sleep(_POLL_INTERVAL_SEC)
        return None

    async def pause(self, task_id: str) -> None:
        raise HarnessEngineNotSupportedError("Claude Code engine does not support pause")

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        raise HarnessEngineNotSupportedError("Claude Code engine does not support resume")

    async def send_input(self, task_id: str, text: str) -> None:
        raise HarnessEngineNotSupportedError("Claude Code engine does not support send_input")

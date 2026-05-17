from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .base import EngineContext, EngineEvent, ExecutionEngine, NotSupportedError

_SESSION_META_DIR = Path.home() / ".claude" / "usage-data" / "session-meta"
_POLL_TIMEOUT_SEC = 30
_POLL_INTERVAL_SEC = 1.0


def _find_session_meta(started_at: float) -> dict | None:
    """Find the session-meta file whose start_time is closest to started_at."""
    if not _SESSION_META_DIR.exists():
        return None
    best = None
    best_diff = float("inf")
    for f in _SESSION_META_DIR.iterdir():
        if not f.suffix == ".json":
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        meta_start = data.get("start_time")
        if meta_start is None:
            continue
        diff = abs(meta_start - started_at)
        if diff < best_diff and diff <= 10:
            best_diff = diff
            best = data
    return best


class ClaudeCodeEngine(ExecutionEngine):
    async def start(self, context: EngineContext, emit) -> None:
        started_at = time.time()
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.working_directory,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if context.rendered_prompt:
            process.stdin.write(context.rendered_prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

        await emit(EngineEvent(event_type="system", payload={"subtype": "task_started"}))

        async def read_stream(stream, kind):
            while True:
                line = await stream.readline()
                if not line:
                    break
                role = "assistant" if kind == "stdout" else "system"
                await emit(
                    EngineEvent(
                        event_type="message",
                        payload={"role": role, "content": line.decode("utf-8", errors="replace")},
                    )
                )

        await asyncio.gather(
            read_stream(process.stdout, "stdout"),
            read_stream(process.stderr, "stderr"),
        )
        await process.wait()

        # Poll for session-meta token data
        token_usage = await self._poll_session_meta(started_at)
        status = "succeeded" if process.returncode == 0 else "failed"
        await emit(
            EngineEvent(
                event_type="system",
                payload={"subtype": f"task_{status}"},
                token_usage=token_usage,
            )
        )
        await emit(EngineEvent(event_type="status", payload={"status": status}))

    async def _poll_session_meta(self, started_at: float) -> dict | None:
        """Poll session-meta directory for a matching file, up to 30 seconds."""
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
        raise NotSupportedError("ClaudeCodeEngine does not support pause")

    async def resume(self, context: EngineContext, emit) -> None:
        raise NotSupportedError("ClaudeCodeEngine does not support resume")

    async def send_prompt(self, task_id: str, prompt: str) -> None:
        raise NotSupportedError("ClaudeCodeEngine does not support send_prompt")

    async def abort(self, task_id: str) -> None:
        pass

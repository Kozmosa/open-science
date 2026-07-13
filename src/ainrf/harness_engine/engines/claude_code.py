from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

from ainrf.harness_engine.base import (
    EngineEvent,
    ExecutionContext,
    EngineEmit,
    HarnessEngine,
    HarnessEngineNotSupportedError,
    HarnessEngineType,
    RuntimeProbeResult,
    RuntimeProbeStatus,
)
from ainrf.harness_engine.session_state import RuntimeLaunchTracker

logger = logging.getLogger(__name__)

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
    """Claude Code 执行引擎 — ``claude -p`` CLI with session-aware retry.

    Session lifecycle::

        ┌──────────────────────────────────────────────────────┐
        │  _pending_messages[runtime_identity]  ← input queues │
        │  _session_ids[runtime_identity]       ← stored success│
        └──────────────────────────────────────────────────────┘

    Fresh start (no stored session_id)::

        claude -p --session-id <runtime_identity> "prompt"

    Resume (stored session_id + pending message)::

        claude --resume <session_id> -p "pending message"

    Resume failure → fall back to fresh session with prior context::

        claude -p --session-id <runtime_identity> "[context] ↵ message"
    """

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._runtime_task_ids: dict[str, str] = {}
        self._session_ids: dict[str, str] = {}
        self._pending_messages: dict[str, deque[str]] = {}
        self._last_event_at: dict[str, float] = {}
        self._runtime_recovery = RuntimeLaunchTracker(HarnessEngineType.CLAUDE_CODE.value)

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    # ── public API ────────────────────────────────────────────────────

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.bind_runtime_context(context)
        self.arm_runtime_launch(context)
        started_at = time.time()

        skill_cleanup_dirs = self._mount_skills(context)
        mcp_file = self._write_mcp_config(context)
        mcp_path: str | None = mcp_file.name if mcp_file is not None else None

        try:
            await self._start_inner(context, emit, started_at, mcp_path)
        finally:
            if mcp_file is not None:
                try:
                    os.unlink(mcp_file.name)
                except OSError:
                    pass
            self._cleanup_skills(skill_cleanup_dirs)

    async def _start_inner(
        self,
        context: ExecutionContext,
        emit: EngineEmit,
        started_at: float,
        mcp_path: str | None,
    ) -> None:
        # A durable Task can have more than one Attempt.  The launch key is
        # therefore the only safe identity for engine-local maps and Claude's
        # transcript id.  Legacy callers omit it and retain task-scoped maps.
        runtime_identity = context.runtime_identity
        session_id = self._session_ids.get(runtime_identity)
        pending = self._drain_pending(runtime_identity)

        if session_id is not None:
            # → Resume path
            prompt = pending[0] if pending else "Continue from where you left off."
            try:
                await self._run(
                    command=self._build_command(
                        context,
                        resume=session_id,
                        mcp_config_path=mcp_path,
                    ),
                    prompt=prompt,
                    context=context,
                    emit=emit,
                    started_at=started_at,
                )
                # Session still valid after successful resume
                self._session_ids[runtime_identity] = session_id
                return
            except Exception:
                logger.warning(
                    "Session resume failed for task=%s session=%s; "
                    "falling back to fresh session with prior context",
                    context.task_id,
                    session_id,
                )
                self._session_ids.pop(runtime_identity, None)

        # → Fresh path (or resume-failure fallback)
        prompt = self._build_prompt(context, pending)
        session_id = self._make_session_id(context)

        await self._run(
            command=self._build_command(
                context,
                session_id=session_id,
                mcp_config_path=mcp_path,
            ),
            prompt=prompt,
            context=context,
            emit=emit,
            started_at=started_at,
        )
        self._session_ids[runtime_identity] = session_id

    async def send_input(
        self,
        task_id: str,
        text: str,
        *,
        runtime_launch_key: str | None = None,
    ) -> None:
        """Enqueue a follow-up message for the next :meth:`start` call."""
        runtime_identity = runtime_launch_key or task_id
        self._pending_messages.setdefault(runtime_identity, deque()).append(text)

    async def cancel(self, task_id: str, *, runtime_launch_key: str | None = None) -> None:
        runtime_identity = runtime_launch_key or task_id
        process = self._processes.get(runtime_identity)
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def is_alive(self, task_id: str, *, runtime_launch_key: str | None = None) -> bool:
        runtime_identity = runtime_launch_key or task_id
        process = self._processes.get(runtime_identity)
        return process is not None and process.returncode is None

    def bind_runtime_context(self, context: ExecutionContext) -> None:
        self._runtime_recovery.bind(context)

    def arm_runtime_launch(self, context: ExecutionContext) -> None:
        self._runtime_recovery.arm(context)

    async def probe_runtime(
        self,
        *,
        task_id: str,
        launch_key: str,
    ) -> RuntimeProbeResult:
        process = self._processes.get(launch_key)
        if process is not None and process.returncode is None:
            if self._runtime_task_ids.get(launch_key) == task_id:
                return RuntimeProbeResult(
                    status=RuntimeProbeStatus.RUNNING,
                    engine_session_key=self._session_ids.get(launch_key, launch_key),
                    metadata={"recovery_evidence": "owned-process"},
                )
            return RuntimeProbeResult(
                status=RuntimeProbeStatus.UNKNOWN,
                metadata={"reason": "Launch key is associated with a different Task"},
            )
        inspection = self._runtime_recovery.inspect(task_id=task_id, launch_key=launch_key)
        return RuntimeProbeResult(
            status=RuntimeProbeStatus(inspection.status),
            engine_session_key=inspection.engine_session_key,
            metadata={
                key: value
                for key, value in {
                    "process_id": inspection.process_id,
                    "reason": inspection.reason,
                }.items()
                if value is not None
            },
        )

    async def adopt_runtime(
        self,
        *,
        task_id: str,
        launch_key: str,
    ) -> RuntimeProbeResult:
        probe = await self.probe_runtime(task_id=task_id, launch_key=launch_key)
        if probe.status is not RuntimeProbeStatus.RUNNING:
            return probe
        # Claude's one-shot CLI owns a private stdin/stdout pipe.  A new
        # dispatcher can prove that process exists, but cannot reconnect to
        # its stream or safely resume its control protocol.  Reporting RUNNING
        # here would make the worker mark a fake adoption as successful.
        return RuntimeProbeResult(
            status=RuntimeProbeStatus.UNKNOWN,
            engine_session_key=probe.engine_session_key,
            metadata={"reason": "Claude Code stdio process is observable but cannot be reattached"},
        )

    async def last_event_at(
        self, task_id: str, *, runtime_launch_key: str | None = None
    ) -> float | None:
        runtime_identity = runtime_launch_key or task_id
        return self._last_event_at.get(runtime_identity)

    async def pause(self, task_id: str, *, runtime_launch_key: str | None = None) -> None:
        _ = task_id, runtime_launch_key
        raise HarnessEngineNotSupportedError("Claude Code engine does not support pause")

    async def resume(self, context: ExecutionContext, emit: EngineEmit) -> None:
        raise HarnessEngineNotSupportedError("Claude Code engine does not support resume")

    # ── command construction ──────────────────────────────────────────

    @staticmethod
    def _make_session_id(context: ExecutionContext) -> str:
        """Derive a deterministic session id from the runtime identity.

        The CLI uses this as a filename component under
        ``~/.claude/projects/<key>/<session_id>.jsonl``.
        """
        return context.runtime_identity

    def _build_command(
        self,
        context: ExecutionContext,
        *,
        session_id: str | None = None,
        resume: str | None = None,
        mcp_config_path: str | None = None,
    ) -> list[str]:
        """Build the ``claude`` command line for one run.

        Parameters:
            session_id: Write the session transcript under this id
                (``--session-id``, used for fresh starts).
            resume: Resume a previous session (``--resume``, used for
                retry / continue).
            mcp_config_path: Path to a temporary MCP config JSON file.
        """
        command = ["claude", "-p", "--permission-mode", "bypassPermissions"]
        if resume is not None:
            command.extend(["--resume", resume])
        if session_id is not None:
            command.extend(["--session-id", session_id])
        if mcp_config_path is not None:
            command.extend(["--mcp-config", mcp_config_path])
        if context.tenant_user:
            command = ["sudo", "-u", context.tenant_user, *command]
        return command

    # ── subprocess orchestration ──────────────────────────────────────

    async def _run(
        self,
        *,
        command: list[str],
        prompt: str,
        context: ExecutionContext,
        emit: EngineEmit,
        started_at: float,
    ) -> None:
        """Spawn the CLI, stream stdout/stderr, and emit lifecycle events."""

        async def _emit(event: EngineEvent) -> None:
            self._last_event_at[context.runtime_identity] = time.time()
            await emit(event)

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
        engine_session_key = self._session_ids.get(
            context.runtime_identity,
            self._make_session_id(context),
        )
        self._runtime_recovery.begin(context, engine_session_key=engine_session_key)
        env.update(self._runtime_recovery.environment(context))

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.working_directory,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[context.runtime_identity] = process
        self._runtime_task_ids[context.runtime_identity] = context.task_id
        self._runtime_recovery.mark_running(
            context,
            process_id=(process.pid if isinstance(getattr(process, "pid", None), int) else None),
            engine_session_key=engine_session_key,
        )
        stdin = process.stdin
        stdout = process.stdout
        stderr = process.stderr

        try:
            if stdin is None or stdout is None or stderr is None:
                raise RuntimeError("Claude Code engine failed to attach stdio pipes")
            if prompt:
                stdin.write(prompt.encode())
                await stdin.drain()
            stdin.close()

            await _emit(
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": "task_started",
                        "command": command,
                        "cwd": context.working_directory,
                    },
                )
            )

            async def _read(stream: asyncio.StreamReader, kind: str, role: str) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    content = line.decode("utf-8", errors="replace")
                    evt_type = "error" if kind == "stderr" else "message"
                    await _emit(
                        EngineEvent(
                            event_type=evt_type,
                            payload={
                                "role": role,
                                "kind": kind,
                                "content": content,
                            },
                        )
                    )

            await asyncio.gather(
                _read(stdout, "stdout", "assistant"),
                _read(stderr, "stderr", "system"),
            )
            await process.wait()

            token_usage = await self._poll_session_meta(started_at)
            status = "succeeded" if process.returncode == 0 else "failed"
            await _emit(
                EngineEvent(
                    event_type="system",
                    payload={
                        "subtype": f"task_{status}",
                        "returncode": process.returncode,
                    },
                    token_usage=token_usage,
                )
            )
            await _emit(
                EngineEvent(
                    event_type="status",
                    payload={
                        "status": status,
                        "exit_code": process.returncode,
                    },
                )
            )
            if process.returncode != 0:
                raise RuntimeError(f"claude exited with code {process.returncode}")
        finally:
            self._processes.pop(context.runtime_identity, None)
            self._runtime_task_ids.pop(context.runtime_identity, None)
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            self._runtime_recovery.finish(context)

    # ── helpers ────────────────────────────────────────────────────────

    def _drain_pending(self, runtime_identity: str) -> list[str]:
        """Return and clear pending messages for one runtime identity."""
        q = self._pending_messages.pop(runtime_identity, None)
        return list(q) if q else []

    def _build_prompt(
        self,
        context: ExecutionContext,
        pending: list[str],
    ) -> str:
        """Build the prompt for a fresh (non-resume) session.

        When *pending* messages exist (retry / continue) and
        ``context.prior_messages`` is available, we inject the prior
        conversation as a degraded context prefix so the model has
        awareness of earlier turns even though the fresh session lacks
        tool-execution history.
        """
        if pending:
            message = pending[0]
        else:
            message = context.rendered_prompt

        if not context.prior_messages:
            return message

        prior = context.prior_messages
        if len(prior) > 100:
            prior = prior[-100:]

        lines: list[str] = []
        lines.append(
            "[Previous conversation — recovered from task history. "
            "You are continuing a prior session whose state was lost. "
            "You do NOT remember the exact tool calls or file edits "
            "from the prior session, but the messages below summarize "
            "what was discussed. Resume from the last checkpoint and "
            "use Read / Bash to re-discover the current file state.]"
        )
        for msg in prior:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role_label}: {msg['content']}")
        lines.append("---")
        lines.append(message)
        return "\n\n".join(lines)

    @staticmethod
    def _mount_skills(context: ExecutionContext) -> list[Path]:
        """Symlink workspace skills; return the list of dirs to clean up."""
        if not (context.skill_load_dir and context.skills):
            return []
        from ainrf.skills.mount import prepare_workspace_skills

        return prepare_workspace_skills(
            context.working_directory,
            context.skill_load_dir,
            context.skills,
            tenant_user=context.tenant_user,
        )

    @staticmethod
    def _cleanup_skills(dirs: list[Path]) -> None:
        for d in dirs:
            try:
                if d.is_symlink():
                    d.unlink()
            except OSError:
                pass

    def _write_mcp_config(
        self, context: ExecutionContext
    ) -> tempfile._TemporaryFileWrapper[bytes] | None:
        if not context.mcp_servers:
            return None
        mcp_json = json.dumps({"mcpServers": context.mcp_servers})
        f = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".json",
            prefix="ainrf-mcp-",
            delete=False,
        )
        f.write(mcp_json.encode())
        f.close()
        os.chmod(f.name, 0o644)
        # Inject the temp config file path into the command at call site.
        # We return the file object so the caller can unlink it later.
        return f

    def _remove_implicit_provider_env(self, env: dict[str, str], context: ExecutionContext) -> None:
        has_explicit = any(
            value
            for value in (
                context.api_base_url,
                context.api_key,
                context.default_opus_model,
                context.default_sonnet_model,
                context.default_haiku_model,
            )
        ) or any(key in (context.env_overrides or {}) for key in _ANTHROPIC_PROVIDER_ENV_KEYS)
        if has_explicit:
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

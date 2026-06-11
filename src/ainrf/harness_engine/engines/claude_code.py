from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
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
    """Claude Code 执行引擎"""

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        started_at = time.time()

        # Prepare .claude/skills/ symlinks from the registry load directory
        # so that Claude Code discovers slash-command skills at startup.
        skill_cleanup_dirs: list[Path] = []
        if context.skill_load_dir and context.skills:
            skill_cleanup_dirs = self._prepare_workspace_skills(
                context.working_directory,
                context.skill_load_dir,
                context.skills,
            )

        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
        ]
        if context.tenant_user:
            command = ["sudo", "-u", context.tenant_user, *command]
        # If MCP servers are configured, write a temporary config file and
        # pass it via --mcp-config so Claude Code spawns the servers.
        mcp_config_file: tempfile._TemporaryFileWrapper[bytes] | None = None
        if context.mcp_servers:
            mcp_json = json.dumps({"mcpServers": context.mcp_servers})
            mcp_config_file = tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".json",
                prefix="ainrf-mcp-",
                delete=False,
            )
            mcp_config_file.write(mcp_json.encode())
            mcp_config_file.close()
            command.extend(["--mcp-config", mcp_config_file.name])

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
            # Clean up skill symlinks created for this task
            for skill_dir in skill_cleanup_dirs:
                try:
                    if skill_dir.is_symlink():
                        skill_dir.unlink()
                except OSError:
                    pass
            if mcp_config_file is not None:
                try:
                    os.unlink(mcp_config_file.name)
                except OSError:
                    pass
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    @staticmethod
    def _prepare_workspace_skills(
        working_directory: str,
        skill_load_dir: str,
        requested_skills: list[str],
    ) -> list[Path]:
        """Symlink requested skill directories into ``<workdir>/.claude/skills/``.

        Claude Code discovers slash-command skills by scanning
        ``.claude/skills/<name>/SKILL.md`` in the project directory.  This
        method creates one symlink per requested skill that exists in the
        registry load directory, allowing the engine to inject the ARIS
        skill set into any workspace without copying files.

        Returns a list of symlink paths created (for cleanup).
        """
        workdir = Path(working_directory)
        claude_skills_dir = workdir / ".claude" / "skills"
        load_dir = Path(skill_load_dir)
        cleanup: list[Path] = []

        for skill_id in requested_skills:
            source = load_dir / skill_id
            if not source.is_dir():
                logger.debug("skill %s not found in load dir %s, skipping", skill_id, load_dir)
                continue

            dest = claude_skills_dir / skill_id
            # Skip if a non-symlink (user-owned) directory already exists.
            if dest.exists() and not dest.is_symlink():
                logger.debug("skill %s already exists as real dir, skipping", skill_id)
                continue
            # Remove stale symlink pointing to a different target.
            if dest.is_symlink():
                try:
                    current_target = dest.resolve()
                    if current_target == source.resolve():
                        # Already linked correctly — nothing to do.
                        continue
                    dest.unlink()
                except OSError:
                    continue

            claude_skills_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(str(source), str(dest))
                cleanup.append(dest)
                logger.debug("linked skill %s -> %s", dest, source)
            except OSError as exc:
                logger.warning("failed to symlink skill %s: %s", skill_id, exc)

        return cleanup

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

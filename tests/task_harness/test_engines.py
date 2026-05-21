from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from ainrf.task_harness.engines.base import EngineContext
from ainrf.task_harness.engines import ClaudeCodeEngine, CodexAppServerEngine, NotSupportedError, get_engine
from ainrf.task_harness.models import ResearchAgentProfileSnapshot, TaskConfigurationMode, TaskConfigurationSnapshot


def _make_context() -> EngineContext:
    return EngineContext(
        task_id="t-1",
        working_directory="/tmp",
        rendered_prompt="hello",
        agent_profile=ResearchAgentProfileSnapshot(
            profile_id="p-1",
            label="Test",
            system_prompt=None,
            skills=[],
            skills_prompt=None,
            settings_json=None,
            settings_artifact_path=None,
        ),
        task_config=TaskConfigurationSnapshot(
            mode=TaskConfigurationMode.RAW_PROMPT,
            template_id=None,
            template_vars={},
            raw_prompt="hello",
            rendered_task_input="hello",
        ),
    )


def test_get_engine_unknown():
    with pytest.raises(ValueError, match="Unknown execution engine"):
        get_engine("unknown")


def test_claude_code_engine_not_supported():
    engine = ClaudeCodeEngine()
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.pause("t-1"))
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.resume(_make_context(), lambda _event: None))
    with pytest.raises(NotSupportedError):
        asyncio.run(engine.send_prompt("t-1", "hello"))


def test_get_engine_codex_app_server():
    engine = get_engine("codex-app-server")
    assert isinstance(engine, CodexAppServerEngine)


@pytest.mark.anyio
async def test_codex_app_server_start_fails_when_process_exits_before_response():
    engine = CodexAppServerEngine()

    class FakeStreamReader:
        async def readline(self) -> bytes:
            return b""

    class FakeStreamWriter:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStreamWriter()
            self.stdout = FakeStreamReader()
            self.stderr = FakeStreamReader()
            self.returncode = None

        async def wait(self) -> int:
            return 1

        def terminate(self) -> None:
            return None

    async def emit(_event) -> None:
        return None

    with patch(
        "ainrf.task_harness.engines.codex_app_server.asyncio.create_subprocess_exec",
        return_value=FakeProcess(),
    ):
        with pytest.raises(RuntimeError, match="terminated before completing the request"):
            await engine.start(_make_context(), emit)

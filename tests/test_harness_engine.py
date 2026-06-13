from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from claude_agent_sdk import ResultMessage, StreamEvent, SystemMessage

from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineNotSupportedError,
    HarnessEngineType,
    OutputEvent,
    get_engine,
)
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine, AgentSession
from ainrf.harness_engine.engines.claude_code import ClaudeCodeEngine
from ainrf.harness_engine.engines.codex_app_server import CodexAppServerEngine, CodexSession


pytestmark = [pytest.mark.engine]


def test_get_engine_claude_code() -> None:
    engine = get_engine("claude-code")
    assert isinstance(engine, ClaudeCodeEngine)
    assert engine.engine_type == HarnessEngineType.CLAUDE_CODE


def test_get_engine_agent_sdk() -> None:
    engine = get_engine("agent-sdk")
    assert isinstance(engine, AgentSdkEngine)
    assert engine.engine_type == HarnessEngineType.AGENT_SDK


def test_get_engine_codex_app_server() -> None:
    engine = get_engine("codex-app-server")
    assert isinstance(engine, CodexAppServerEngine)
    assert engine.engine_type == HarnessEngineType.CODEX_APP_SERVER


def test_get_engine_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown execution engine"):
        get_engine("unknown-engine")


def test_execution_context_creation() -> None:
    ctx = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
        skills=["skill1"],
        mcp_servers=[],
    )
    assert ctx.task_id == "task-001"
    assert ctx.prompt == "test prompt"
    assert ctx.system_prompt is None


def test_claude_code_engine_scrubs_implicit_anthropic_env() -> None:
    engine = ClaudeCodeEngine()
    env = {
        "ANTHROPIC_API_KEY": "stale",
        "ANTHROPIC_AUTH_TOKEN": "stale",
        "PATH": "/usr/bin",
    }
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

    engine._remove_implicit_provider_env(env, context)

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"


def test_claude_code_engine_keeps_explicit_anthropic_env() -> None:
    engine = ClaudeCodeEngine()
    env = {"ANTHROPIC_API_KEY": "explicit"}
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
        api_key="explicit",
    )

    engine._remove_implicit_provider_env(env, context)

    assert env["ANTHROPIC_API_KEY"] == "explicit"


def test_agent_sdk_ignores_partial_stream_deltas() -> None:
    engine = AgentSdkEngine()
    session = AgentSession(task_id="task-001")
    event = StreamEvent(
        uuid="event-001",
        session_id="session-001",
        event={"type": "content_block_delta", "delta": {"text": "Hello"}},
    )

    assert engine._convert_sdk_message(event, session) == []


def test_agent_sdk_ignores_noisy_system_progress_updates() -> None:
    engine = AgentSdkEngine()
    session = AgentSession(task_id="task-001")

    thinking_tokens = SystemMessage(
        subtype="thinking_tokens",
        data={"estimated_tokens": 12, "estimated_tokens_delta": 2},
    )
    status = SystemMessage(
        subtype="status",
        data={"status": "requesting"},
    )

    assert engine._convert_sdk_message(thinking_tokens, session) == []
    assert engine._convert_sdk_message(status, session) == []


def test_agent_sdk_failed_result_does_not_require_extra_stderr() -> None:
    engine = AgentSdkEngine()
    session = AgentSession(task_id="task-001")
    result = ResultMessage(
        subtype="result",
        duration_ms=1,
        duration_api_ms=1,
        is_error=True,
        num_turns=1,
        session_id="session-001",
        errors=["Failed to authenticate"],
    )

    events = engine._convert_sdk_message(result, session)

    assert session.had_error is True
    assert session.terminal_emitted is True
    assert [event.event_type for event in events] == ["system", "status"]


@pytest.mark.anyio
async def test_agent_sdk_start_restores_session_id_when_send_input_precreated_session(
    tmp_path: Path,
) -> None:
    """Regression: send_input() pre-creates a session (session_id=None) before
    start() runs on follow-up messages. After a process restart the in-memory
    session is gone, so start() must still restore session_id from the
    checkpoint — otherwise --resume is dropped and the conversation restarts
    fresh, losing multi-turn context.
    """
    import json

    engine = AgentSdkEngine()

    # Persisted checkpoint from a prior completed turn (process restarted after).
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "version": 1,
                "task_id": "task-restart",
                "session_id": "prev-session-abc",
                "cwd": "/tmp",
                "created_at": "2026-01-01T00:00:00Z",
                "turn_count": 2,
                "total_cost_usd": 0.5,
                "pending_prompts": [],
            }
        ),
        encoding="utf-8",
    )

    context = ExecutionContext(
        task_id="task-restart",
        working_directory="/tmp",
        rendered_prompt="ignored",
        session_state_path=str(checkpoint_path),
    )

    # Simulate the timing: send_input runs first (follow-up message), creating
    # a session with session_id=None and queuing the user's new message.
    await engine.send_input("task-restart", "What about the second approach?")

    captured: dict[str, object] = {}

    async def fake_run_query(ctx, sess, prompt_stream, options, emit, stderr_lines=None):
        captured["session_id"] = sess.session_id
        captured["resume"] = options.resume
        captured["pending_prompts_after"] = list(sess.pending_prompts)

    with patch.object(engine, "_run_query", fake_run_query):
        await engine.start(context, lambda _event: None)

    # session_id restored from checkpoint → --resume flag will be set.
    assert captured["session_id"] == "prev-session-abc"
    assert captured["resume"] == "prev-session-abc"
    # The follow-up message queued by send_input was consumed by _resolve_prompt,
    # not lost to the checkpoint overwrite.
    assert captured["pending_prompts_after"] == []


@pytest.mark.anyio
async def test_codex_app_server_ignores_partial_agent_message_delta() -> None:
    engine = CodexAppServerEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    await engine._handle_message(
        session=CodexSession(task_id="task-001"),
        payload={
            "method": "item/agentMessage/delta",
            "params": {"delta": "Hello"},
        },
        emit=emit,
    )

    assert emitted == []


@pytest.mark.anyio
async def test_codex_app_server_suppresses_echoed_user_messages() -> None:
    engine = CodexAppServerEngine()
    emitted: list[EngineEvent] = []

    async def emit(event: EngineEvent) -> None:
        emitted.append(event)

    await engine._handle_message(
        session=CodexSession(task_id="task-001"),
        payload={
            "method": "item/started",
            "params": {"item": {"type": "userMessage", "text": "hello"}},
        },
        emit=emit,
    )

    assert emitted == []


@pytest.mark.anyio
async def test_codex_app_server_starts_with_yolo_sandbox_defaults() -> None:
    engine = CodexAppServerEngine()
    session = CodexSession(task_id="task-001")
    captured: list[tuple[str, dict]] = []

    async def fake_rpc_request(
        _session: CodexSession,
        method: str,
        params: dict,
    ) -> dict:
        captured.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-001"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-001"}}
        return {}

    engine._rpc_request = fake_rpc_request  # type: ignore[method-assign]
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="hello",
    )

    await engine._start_thread(context, session)
    await engine._start_turn(context, session, "hello")

    assert captured[0] == (
        "thread/start",
        {
            "cwd": "/tmp",
            "approvalPolicy": "never",
            "personality": "pragmatic",
            "sandbox": "danger-full-access",
        },
    )
    assert captured[1] == (
        "turn/start",
        {
            "threadId": "thread-001",
            "approvalPolicy": "never",
            "input": [{"type": "text", "text": "hello"}],
            "sandboxPolicy": {"type": "dangerFullAccess"},
        },
    )


def test_engine_event_creation() -> None:
    event = EngineEvent(
        event_type="system",
        payload={"subtype": "task_started"},
        token_usage={"total": {"input_tokens": 1}},
    )
    assert event.event_type == "system"
    assert event.payload["subtype"] == "task_started"
    assert event.token_usage == {"total": {"input_tokens": 1}}


def test_output_event_creation() -> None:
    event = OutputEvent(kind="stdout", content="hello", seq=1, created_at="2026-01-01")
    assert event.kind == "stdout"
    assert event.content == "hello"


def test_harness_engine_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        HarnessEngine()


@pytest.mark.anyio
async def test_default_unsupported_operations_raise_typed_error() -> None:
    engine = get_engine("claude-code")
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

    async def emit(event: EngineEvent) -> None:
        _ = event

    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.pause("task-001")
    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.resume(context, emit)
    with pytest.raises(HarnessEngineNotSupportedError):
        await engine.send_input("task-001", "hello")


@pytest.mark.anyio
async def test_codex_app_server_start_fails_when_process_exits_before_response() -> None:
    engine = CodexAppServerEngine()
    context = ExecutionContext(
        task_id="task-001",
        working_directory="/tmp",
        rendered_prompt="test prompt",
    )

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
            self.returncode = 1

    async def emit(event: EngineEvent) -> None:
        _ = event

    with patch(
        "ainrf.harness_engine.engines.codex_app_server.asyncio.create_subprocess_exec",
        return_value=FakeProcess(),
    ):
        with pytest.raises(RuntimeError, match="terminated before completing the request"):
            await engine.start(context, emit)


def test_prepare_workspace_skills_symlinks(tmp_path: Path) -> None:
    """_prepare_workspace_skills creates symlinks in .claude/skills/ for each
    requested skill that exists in the load directory."""
    # Set up a load directory with two skills
    load_dir = tmp_path / "load" / "skills"
    for name in ("research-lit", "arxiv"):
        skill_dir = load_dir / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n")

    workdir = tmp_path / "workspace"
    workdir.mkdir()

    cleanup = ClaudeCodeEngine._prepare_workspace_skills(
        working_directory=str(workdir),
        skill_load_dir=str(load_dir),
        requested_skills=["research-lit", "arxiv", "missing-skill"],
    )

    # Two skills symlinked, one skipped (missing)
    assert len(cleanup) == 2
    claude_skills = workdir / ".claude" / "skills"
    assert (claude_skills / "research-lit").is_symlink()
    assert (claude_skills / "arxiv").is_symlink()
    assert not (claude_skills / "missing-skill").exists()

    # Symlinks point to the correct targets
    assert (claude_skills / "research-lit" / "SKILL.md").read_text() == "# research-lit\n"
    assert (claude_skills / "arxiv" / "SKILL.md").read_text() == "# arxiv\n"


def test_prepare_workspace_skills_preserves_user_owned_dirs(tmp_path: Path) -> None:
    """_prepare_workspace_skills does not overwrite a real (non-symlink) directory."""
    load_dir = tmp_path / "load" / "skills"
    skill_dir = load_dir / "research-lit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# from registry\n")

    workdir = tmp_path / "workspace"
    workdir.mkdir()
    claude_skills = workdir / ".claude" / "skills"
    user_skill = claude_skills / "research-lit"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("# user owned\n")

    cleanup = ClaudeCodeEngine._prepare_workspace_skills(
        working_directory=str(workdir),
        skill_load_dir=str(load_dir),
        requested_skills=["research-lit"],
    )

    # No symlink created — user-owned dir preserved
    assert len(cleanup) == 0
    assert (claude_skills / "research-lit" / "SKILL.md").read_text() == "# user owned\n"


def test_prepare_workspace_skills_replaces_stale_symlink(tmp_path: Path) -> None:
    """_prepare_workspace_skills replaces a symlink pointing to a different target."""
    old_target = tmp_path / "old" / "skills" / "research-lit"
    old_target.mkdir(parents=True)
    (old_target / "SKILL.md").write_text("# old\n")

    new_load_dir = tmp_path / "new" / "skills"
    new_skill = new_load_dir / "research-lit"
    new_skill.mkdir(parents=True)
    (new_skill / "SKILL.md").write_text("# new\n")

    workdir = tmp_path / "workspace"
    workdir.mkdir()
    claude_skills = workdir / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "research-lit").symlink_to(str(old_target))

    cleanup = ClaudeCodeEngine._prepare_workspace_skills(
        working_directory=str(workdir),
        skill_load_dir=str(new_load_dir),
        requested_skills=["research-lit"],
    )

    assert len(cleanup) == 1
    assert (claude_skills / "research-lit" / "SKILL.md").read_text() == "# new\n"

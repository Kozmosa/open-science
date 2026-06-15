"""Test utilities shared across the backend test suite."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from ainrf.agentic_researcher.models import (
    AgenticResearcher,
    AgenticResearcherType,
    HarnessEngineType,
)
from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.environments.service import InMemoryEnvironmentService
from ainrf.harness_engine import EngineEvent, ExecutionContext, HarnessEngine
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def seed_user(
    auth_service: AuthService,
    username: str = "test-user",
    password: str = "test-pass",
    *,
    role: str = "admin",
    user_id: str | None = None,
) -> str:
    """Create and activate a test user, returning the user ID.

    If the user already exists, it is activated and its role updated.
    """
    auth_service.initialize()
    with auth_service._connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            user = auth_service.register(
                username=username, display_name=username.title(), password=password
            )
            user_id_created = user.id
        else:
            user_id_created = row["id"]

        conn.execute(
            "UPDATE users SET status = 'active', activated_at = ?, role = ? WHERE username = ?",
            ("2025-01-01T00:00:00+00:00", role, username),
        )
        if user_id is not None:
            conn.execute("UPDATE users SET id = ? WHERE username = ?", (user_id, username))
            user_id_created = user_id
        conn.commit()
    return user_id_created


def get_jwt_headers(
    app,
    username: str = "test-user",
    password: str = "test-pass",
    user_id: str | None = None,
) -> dict:
    """Register a test user (admin role), log in, and return Authorization headers.

    If *user_id* is given, the user's ID is set to that value (useful when tests
    assert against a well-known user ID such as ``"browser-user"``).
    """
    auth_service = app.state.auth_service
    seed_user(auth_service, username, password, role="admin", user_id=user_id)
    token_data = auth_service.login(username=username, password=password)
    return {"Authorization": f"Bearer {token_data['access_token']}"}


def make_client(tmp_path: Path, *, max_file_size_bytes: int | None = None) -> httpx.AsyncClient:
    """Create an authenticated test client with an admin JWT token."""
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config, max_file_size_bytes=max_file_size_bytes)
    headers = get_jwt_headers(app, "admin", "test-admin-password")

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


def make_client_and_app(tmp_path: Path, *, max_file_size_bytes: int | None = None) -> tuple:
    """Create an authenticated test client with admin JWT, returning (app, client, headers)."""
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config)
    headers = get_jwt_headers(app, "admin", "test-admin-password")

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )
    return app, client, headers


# ---------------------------------------------------------------------------
# Harness engine fakes
# ---------------------------------------------------------------------------
EngineEmit = Callable[[EngineEvent], Awaitable[None]]


class FakeEngine(HarnessEngine):
    """Minimal harness engine that records prompts and emits a success status."""

    def __init__(self) -> None:
        self.pending_prompts: list[str] = []
        self.cancelled_task_ids: set[str] = set()
        self.started_count = 0
        self.completion_event: threading.Event | None = None

    @property
    def engine_type(self) -> HarnessEngineType:
        return HarnessEngineType.CLAUDE_CODE

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.started_count += 1
        prompt = self.pending_prompts.pop(0) if self.pending_prompts else context.rendered_prompt
        await emit(
            EngineEvent(
                event_type="message",
                payload={"role": "assistant", "content": f"ran: {prompt}"},
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )
        if self.completion_event is not None:
            self.completion_event.set()

    async def cancel(self, task_id: str) -> None:
        self.cancelled_task_ids.add(task_id)

    async def send_input(self, task_id: str, text: str) -> None:
        _ = task_id
        self.pending_prompts.append(text)


class TokenEngine(FakeEngine):
    """Fake engine that emits token usage events for cost aggregation tests."""

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        await emit(
            EngineEvent(
                event_type="token",
                payload={"turn": 1},
                token_usage={
                    "source": "agent-sdk",
                    "total": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_creation_input_tokens": 3,
                        "cache_read_input_tokens": 2,
                        "cost_usd": 0.01,
                    },
                    "by_model": {
                        "claude-sonnet": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cost_usd": 0.01,
                        }
                    },
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="system",
                payload={"subtype": "task_completed", "total_cost_usd": 0.02},
                token_usage={
                    "source": "agent-sdk",
                    "total": {
                        "input_tokens": 20,
                        "output_tokens": 8,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "cost_usd": 0.02,
                    },
                    "by_model": {
                        "claude-sonnet": {
                            "input_tokens": 20,
                            "output_tokens": 8,
                            "cost_usd": 0.02,
                        }
                    },
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )


class HangingEngine(FakeEngine):
    """Engine that blocks until cancelled, useful for testing cancel races."""

    def __init__(self) -> None:
        super().__init__()
        self.cancel_event: asyncio.Event | None = None

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        self.started_count += 1
        self.cancel_event = asyncio.Event()
        try:
            await self.cancel_event.wait()
        except asyncio.CancelledError:
            pass

    async def cancel(self, task_id: str) -> None:
        await super().cancel(task_id)
        if self.cancel_event is not None:
            self.cancel_event.set()


# ---------------------------------------------------------------------------
# Service factories
# ---------------------------------------------------------------------------
def make_researcher(**kwargs) -> AgenticResearcher:
    """Return a default AgenticResearcher for task creation tests."""
    defaults = {
        "type": AgenticResearcherType.VANILLA,
        "harness_engine": HarnessEngineType.CLAUDE_CODE,
        "skills": [],
        "mcp_servers": [],
        "system_prompt": None,
    }
    defaults.update(kwargs)
    return AgenticResearcher(**defaults)


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------
def make_terminal_manager(
    tmp_path: Path, *, user_id: str = "daemon-user"
) -> tuple[SessionManager, InMemoryEnvironmentService]:
    """Return a SessionManager with an in-memory environment service for tests."""
    environment_service = InMemoryEnvironmentService()
    manager = SessionManager(
        state_root=tmp_path,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(tmp_path),
        default_shell="/bin/bash",
        user_id=user_id,
    )
    return manager, environment_service


def make_terminal_app(tmp_path: Path) -> FastAPI:
    """Return a FastAPI app with terminal support enabled."""
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            terminal_command=("/bin/bash", "-l"),
        )
    )


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------
def run_threaded(
    operation: Callable[[Any], Any],
    items: int | list[Any],
    *,
    max_workers: int = 8,
) -> list[Any]:
    """Run *operation(i)* for each item across a thread pool.

    *items* may be an integer (range(items)) or a list of arguments.  Any
    exception raised by a worker is propagated to the caller.
    """
    args = range(items) if isinstance(items, int) else items
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(operation, i) for i in args]
    return [f.result() for f in futures]


async def run_async_concurrent(
    operation: Callable[[int], Awaitable[Any]],
    count: int,
) -> list[Any]:
    """Run *operation(i)* concurrently via asyncio.gather."""
    return await asyncio.gather(*(operation(i) for i in range(count)))


# ---------------------------------------------------------------------------
# File corruption helpers
# ---------------------------------------------------------------------------
def corrupt_json_file(path: Path) -> None:
    """Overwrite *path* with malformed JSON."""
    path.write_text("not valid json{", encoding="utf-8")


def corrupt_sqlite_header(path: Path) -> None:
    """Overwrite *path* with bytes that are not a valid SQLite header."""
    path.write_bytes(b"this is not a sqlite database file content")


def truncate_file(path: Path) -> None:
    """Truncate *path* to zero bytes."""
    path.write_bytes(b"")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def load_json(path: Path) -> Any:
    """Load JSON from *path*, raising a plain AssertionError on failure."""
    return json.loads(path.read_text(encoding="utf-8"))

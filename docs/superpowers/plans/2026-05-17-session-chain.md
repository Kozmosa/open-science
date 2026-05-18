# AINRF Session Chain — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TaskSession + TaskAttempt data model and SessionsPage UI, providing the infrastructure for Token Tracking and Timeline features.

**Architecture:** New `src/ainrf/sessions/` package (models + service + SQLite tables) coexists with existing task_harness DB. SessionService shares the `task_harness.sqlite3` file but owns its own tables. Frontend adds `/sessions` route with SplitPane layout (SessionList | SessionDetail + AttemptChain), reusing PageShell/SplitPane/SectionStack/Badge/StatusDot.

**Tech Stack:** Python 3.13 dataclasses, SQLite3, FastAPI, React 19 + TanStack Query + Tailwind v4, Vitest + Testing Library

---

## File Structure

```
src/ainrf/sessions/
    __init__.py              # re-exports SessionService, models
    models.py                # Session, Attempt dataclasses + errors
    service.py               # SessionService (DB init, CRUD, aggregation)

src/ainrf/api/
    schemas.py               # + SessionCreateRequest, SessionResponse, AttemptResponse, ...
    routes/sessions.py       # session routes (CRUD + attempts sub-resource)
    app.py                   # register session_router, init SessionService

src/ainrf/task_harness/
    service.py               # + TaskAttempt auto-create/update hooks (opt-in via session_id)

frontend/src/
    types/index.ts           # + SessionRecord, AttemptRecord, SessionListResponse, ...
    api/endpoints.ts         # + getSessions, getSession, createSession, ...
    api/mock.ts              # + mock functions for session endpoints
    pages/SessionsPage.tsx   # main page component
    pages/sessions/
        SessionList.tsx       # sidebar list
        SessionDetail.tsx     # main detail pane
        AttemptChain.tsx      # vertical timeline of attempts
    i18n/messages.ts         # + sessions.* i18n keys (en + zh)
    components/common/Layout.tsx  # + nav item
    App.tsx                  # + lazy import + route
```

---

## Task 1: DB Schema + SessionService

**Files:**
- Create: `src/ainrf/sessions/__init__.py`
- Create: `src/ainrf/sessions/models.py`
- Create: `src/ainrf/sessions/service.py`

- [ ] **Step 1: Create package init**

```python
# src/ainrf/sessions/__init__.py
"""Session and attempt tracking for research task chains."""

from ainrf.sessions.models import (
    AttemptStatus,
    Session,
    SessionAttempt,
    SessionError,
    SessionNotFoundError,
    SessionStatus,
)
from ainrf.sessions.service import SessionService

__all__ = [
    "AttemptStatus",
    "Session",
    "SessionAttempt",
    "SessionError",
    "SessionNotFoundError",
    "SessionService",
    "SessionStatus",
]
```

- [ ] **Step 2: Write models with dataclasses**

```python
# src/ainrf/sessions/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class SessionError(RuntimeError):
    """Base error for session operations."""


class SessionNotFoundError(SessionError):
    """Session not found."""


class AttemptNotFoundError(SessionError):
    """Attempt not found."""


@dataclass(slots=True)
class Session:
    id: str
    project_id: str
    title: str
    status: SessionStatus
    task_count: int
    total_duration_ms: int
    total_cost_usd: float
    created_at: str
    updated_at: str


@dataclass(slots=True)
class SessionAttempt:
    id: str
    session_id: str
    task_id: str | None
    parent_attempt_id: str | None
    attempt_seq: int
    intervention_reason: str | None
    status: AttemptStatus
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    token_usage_json: str | None
    created_at: str
```

- [ ] **Step 3: Write SessionService with DB initialization**

```python
# src/ainrf/sessions/service.py
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ainrf.sessions.models import (
    AttemptNotFoundError,
    AttemptStatus,
    Session,
    SessionAttempt,
    SessionError,
    SessionNotFoundError,
    SessionStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class SessionService:
    def __init__(self, *, state_root: Path) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "task_harness.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    task_count INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms INTEGER NOT NULL DEFAULT 0,
                    total_cost_usd REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_attempts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    parent_attempt_id TEXT,
                    attempt_seq INTEGER NOT NULL,
                    intervention_reason TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    token_usage_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_attempts_session
                ON task_attempts(session_id)
            """)
            conn.commit()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        return conn

    # --- Session CRUD ---

    def create_session(self, *, project_id: str, title: str) -> Session:
        sid = _new_id()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_sessions (id, project_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (sid, project_id, title, now, now),
            )
            conn.commit()
        return self._load_session(sid)

    def list_sessions(
        self, *, project_id: str | None = None, status: str | None = None
    ) -> list[Session]:
        clauses = []
        params: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_sessions {where} ORDER BY created_at DESC",
                tuple(params),
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def get_session(self, session_id: str) -> Session:
        return self._load_session(session_id)

    def update_session(
        self, session_id: str, *, title: str | None = None, status: str | None = None
    ) -> Session:
        s = self._load_session(session_id)
        new_title = title if title is not None else s.title
        new_status = status if status is not None else s.status.value
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_sessions SET title = ?, status = ?, updated_at = ? WHERE id = ?",
                (new_title, new_status, now, session_id),
            )
            conn.commit()
        return self._load_session(session_id)

    def delete_session(self, session_id: str) -> None:
        self._load_session(session_id)
        with self._connect() as conn:
            conn.execute("UPDATE task_sessions SET status = 'archived', updated_at = ? WHERE id = ?",
                         (_now_iso(), session_id))
            conn.commit()

    # --- Attempt management ---

    def create_attempt(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
        parent_attempt_id: str | None = None,
        intervention_reason: str | None = None,
    ) -> SessionAttempt:
        self._load_session(session_id)
        next_seq = self._next_attempt_seq(session_id)
        aid = _new_id()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_attempts "
                "(id, session_id, task_id, parent_attempt_id, attempt_seq, "
                "intervention_reason, status, started_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                (aid, session_id, task_id, parent_attempt_id, next_seq,
                 intervention_reason, now, now),
            )
            conn.commit()
        return self._load_attempt(aid)

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        duration_ms: int | None = None,
        token_usage_json: str | None = None,
    ) -> SessionAttempt:
        a = self._load_attempt(attempt_id)
        now = _now_iso()
        duration = duration_ms if duration_ms is not None else a.duration_ms
        token = token_usage_json if token_usage_json is not None else a.token_usage_json
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_attempts SET status = ?, finished_at = ?, duration_ms = ?, "
                "token_usage_json = ? WHERE id = ?",
                (status, now, duration, token, attempt_id),
            )
            conn.commit()
        self._recalc_session(a.session_id)
        return self._load_attempt(attempt_id)

    def list_attempts(self, session_id: str) -> list[SessionAttempt]:
        self._load_session(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_attempts WHERE session_id = ? ORDER BY attempt_seq ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_attempt(r) for r in rows]

    def get_attempt(self, attempt_id: str) -> SessionAttempt:
        return self._load_attempt(attempt_id)

    # --- Internal helpers ---

    def _load_session(self, session_id: str) -> Session:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return _row_to_session(row)

    def _load_attempt(self, attempt_id: str) -> SessionAttempt:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(f"Attempt not found: {attempt_id}")
        return _row_to_attempt(row)

    def _next_attempt_seq(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt_seq), 0) AS seq FROM task_attempts WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return (int(row["seq"]) if row else 0) + 1

    def _recalc_session(self, session_id: str) -> None:
        with self._connect() as conn:
            agg = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(duration_ms), 0) AS dur "
                "FROM task_attempts WHERE session_id = ? AND duration_ms IS NOT NULL",
                (session_id,),
            ).fetchone()
            if agg:
                conn.execute(
                    "UPDATE task_sessions SET task_count = ?, total_duration_ms = ?, updated_at = ? "
                    "WHERE id = ?",
                    (agg["cnt"], agg["dur"], _now_iso(), session_id),
                )
                conn.commit()


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        status=SessionStatus(row["status"]),
        task_count=int(row["task_count"]),
        total_duration_ms=int(row["total_duration_ms"]),
        total_cost_usd=float(row["total_cost_usd"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_attempt(row: sqlite3.Row) -> SessionAttempt:
    return SessionAttempt(
        id=row["id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        parent_attempt_id=row["parent_attempt_id"],
        attempt_seq=int(row["attempt_seq"]),
        intervention_reason=row["intervention_reason"],
        status=AttemptStatus(row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        token_usage_json=row["token_usage_json"],
        created_at=row["created_at"],
    )
```

- [ ] **Step 4: Run a quick Python import check to verify no syntax errors**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.sessions import SessionService, Session, SessionAttempt; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/sessions/
git commit -m "feat: add SessionService with task_sessions + task_attempts tables"
```

---

## Task 2: API Schemas

**Files:**
- Modify: `src/ainrf/api/schemas.py`

- [ ] **Step 1: Add Pydantic schemas to schemas.py**

Append to `src/ainrf/api/schemas.py`:

```python
# ── Session schemas ──────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)


class SessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: str | None = None  # "active" | "completed" | "archived"


class AttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    session_id: str
    task_id: str | None
    parent_attempt_id: str | None
    attempt_seq: int
    intervention_reason: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    token_usage_json: str | None
    created_at: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    title: str
    status: str
    task_count: int
    total_duration_ms: int
    total_cost_usd: float
    created_at: str
    updated_at: str


class SessionDetailResponse(SessionResponse):
    attempts: list["AttemptResponse"] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list["SessionResponse"]


class AttemptListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list["AttemptResponse"]
```

- [ ] **Step 2: Run import check**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.api.schemas import SessionCreateRequest, SessionResponse, SessionDetailResponse; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/api/schemas.py
git commit -m "feat: add Session + Attempt API schemas"
```

---

## Task 3: API Routes

**Files:**
- Create: `src/ainrf/api/routes/sessions.py`
- Modify: `src/ainrf/api/app.py`

- [ ] **Step 1: Write session routes**

```python
# src/ainrf/api/routes/sessions.py
"""Session and attempt API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.api.schemas import (
    AttemptListResponse,
    AttemptResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from ainrf.sessions import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _get_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="session service not initialized")
    return service


def _translate_error(exc: Exception) -> HTTPException:
    name = exc.__class__.__name__
    if name == "SessionNotFoundError":
        return HTTPException(status_code=404, detail=str(exc))
    if name == "AttemptNotFoundError":
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected session error")


def _serialize_session(s) -> dict[str, Any]:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "title": s.title,
        "status": s.status.value if hasattr(s.status, "value") else s.status,
        "task_count": s.task_count,
        "total_duration_ms": s.total_duration_ms,
        "total_cost_usd": s.total_cost_usd,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _serialize_attempt(a) -> dict[str, Any]:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "task_id": a.task_id,
        "parent_attempt_id": a.parent_attempt_id,
        "attempt_seq": a.attempt_seq,
        "intervention_reason": a.intervention_reason,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "started_at": a.started_at,
        "finished_at": a.finished_at,
        "duration_ms": a.duration_ms,
        "token_usage_json": a.token_usage_json,
        "created_at": a.created_at,
    }


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> SessionListResponse:
    service = _get_service(request)
    try:
        sessions = service.list_sessions(project_id=project_id, status=status)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionListResponse.model_validate({
        "items": [_serialize_session(s) for s in sessions],
    })


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest, request: Request
) -> SessionResponse:
    service = _get_service(request)
    try:
        s = service.create_session(project_id=payload.project_id, title=payload.title)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    service = _get_service(request)
    try:
        s = service.get_session(session_id)
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionDetailResponse.model_validate({
        **_serialize_session(s),
        "attempts": [_serialize_attempt(a) for a in attempts],
    })


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str, payload: SessionUpdateRequest, request: Request
) -> SessionResponse:
    service = _get_service(request)
    try:
        s = service.update_session(
            session_id, title=payload.title, status=payload.status
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return SessionResponse.model_validate(_serialize_session(s))


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    service = _get_service(request)
    try:
        service.delete_session(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return Response(status_code=204)


@router.get("/{session_id}/attempts", response_model=AttemptListResponse)
async def list_attempts(
    session_id: str, request: Request
) -> AttemptListResponse:
    service = _get_service(request)
    try:
        attempts = service.list_attempts(session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return AttemptListResponse.model_validate({
        "items": [_serialize_attempt(a) for a in attempts],
    })
```

- [ ] **Step 2: Register routes and service in app.py**

In `src/ainrf/api/app.py`:

Add import near other route imports:
```python
from ainrf.api.routes.sessions import router as sessions_router
```

Add to `ROUTERS` tuple:
```python
ROUTERS: tuple[APIRouter, ...] = (
    health_router,
    environments_router,
    code_router,
    terminal_router,
    files_router,
    workspaces_router,
    projects_router,
    skills_router,
    skill_registries_router,
    resources_router,
    tasks_router,
    task_edges_router,
    sessions_router,
)
```

In `create_app` function, add before other services:
```python
from ainrf.sessions import SessionService

session_service = SessionService(state_root=api_config.state_root)
app.state.session_service = session_service
```

In `lifespan` function, add after `task_harness_service.initialize`:
```python
await _run_sync_in_lifespan(session_service.initialize)
```

- [ ] **Step 3: Check everything imports**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.api.app import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/api/routes/sessions.py src/ainrf/api/app.py
git commit -m "feat: add session API routes and service registration"
```

---

## Task 4: Backend Tests

**Files:**
- Create: `tests/test_sessions.py`

- [ ] **Step 1: Write session service tests**

```python
# tests/test_sessions.py
"""Tests for session service and API routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestSessionService:
    @pytest.fixture
    def service(self):
        from ainrf.sessions import SessionService

        with tempfile.TemporaryDirectory() as td:
            svc = SessionService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_create_and_get_session(self, service):
        s = service.create_session(project_id="proj_1", title="Test Session")
        assert s.title == "Test Session"
        assert s.project_id == "proj_1"
        assert s.status.value == "active"

        got = service.get_session(s.id)
        assert got.id == s.id

    def test_list_sessions_filter(self, service):
        service.create_session(project_id="p1", title="A")
        service.create_session(project_id="p2", title="B")

        all_s = service.list_sessions()
        assert len(all_s) == 2

        p1 = service.list_sessions(project_id="p1")
        assert len(p1) == 1
        assert p1[0].project_id == "p1"

    def test_list_sessions_status_filter(self, service):
        service.create_session(project_id="p1", title="Active")
        s2 = service.create_session(project_id="p1", title="Archived")
        service.update_session(s2.id, status="archived")

        active = service.list_sessions(status="active")
        assert len(active) == 1

    def test_update_session(self, service):
        s = service.create_session(project_id="p1", title="Old")
        updated = service.update_session(s.id, title="New")
        assert updated.title == "New"

    def test_delete_session_archives(self, service):
        s = service.create_session(project_id="p1", title="X")
        service.delete_session(s.id)
        got = service.get_session(s.id)
        assert got.status.value == "archived"

    def test_session_not_found(self, service):
        from ainrf.sessions import SessionNotFoundError

        with pytest.raises(SessionNotFoundError):
            service.get_session("nonexistent")

    def test_create_attempt(self, service):
        s = service.create_session(project_id="p1", title="S")
        a = service.create_attempt(session_id=s.id, task_id="task_1")
        assert a.session_id == s.id
        assert a.attempt_seq == 1
        assert a.task_id == "task_1"
        assert a.status.value == "running"

    def test_attempt_chain(self, service):
        s = service.create_session(project_id="p1", title="S")
        a1 = service.create_attempt(session_id=s.id)
        a2 = service.create_attempt(
            session_id=s.id, parent_attempt_id=a1.id,
            intervention_reason="fix bugs"
        )
        assert a2.attempt_seq == 2
        assert a2.parent_attempt_id == a1.id
        assert a2.intervention_reason == "fix bugs"

    def test_complete_attempt(self, service):
        s = service.create_session(project_id="p1", title="S")
        a = service.create_attempt(session_id=s.id)
        done = service.complete_attempt(
            a.id, status="completed", duration_ms=5000,
            token_usage_json='{"input": 1000, "output": 200}',
        )
        assert done.status.value == "completed"
        assert done.duration_ms == 5000

    def test_complete_attempt_recalcs_session(self, service):
        s = service.create_session(project_id="p1", title="S")
        a1 = service.create_attempt(session_id=s.id)
        service.complete_attempt(a1.id, status="completed", duration_ms=3000)
        a2 = service.create_attempt(session_id=s.id)
        service.complete_attempt(a2.id, status="completed", duration_ms=7000)

        s2 = service.get_session(s.id)
        assert s2.task_count == 2
        assert s2.total_duration_ms == 10000

    def test_list_attempts_sorted(self, service):
        s = service.create_session(project_id="p1", title="S")
        service.create_attempt(session_id=s.id)
        service.create_attempt(session_id=s.id)
        attempts = service.list_attempts(s.id)
        assert len(attempts) == 2
        assert attempts[0].attempt_seq < attempts[1].attempt_seq

    def test_delete_session_preserves_data(self, service):
        s = service.create_session(project_id="p1", title="S")
        service.create_attempt(session_id=s.id)
        service.delete_session(s.id)
        # attempts still queryable
        attempts = service.list_attempts(s.id)
        assert len(attempts) == 1
```

- [ ] **Step 2: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/test_sessions.py -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sessions.py
git commit -m "test: add SessionService unit tests"
```

---

## Task 5: Task Harness Integration

**Files:**
- Modify: `src/ainrf/task_harness/service.py`
- Modify: `src/ainrf/task_harness/models.py`

- [ ] **Step 1: Add session_id to TaskInput model**

In `src/ainrf/task_harness/models.py`, add `session_id` to the `TaskInput` dataclass:

```python
# In TaskInput dataclass, add field:
session_id: str | None = None
```

If `TaskInput` uses `__init__` explicitly, add the parameter there too.

- [ ] **Step 2: Store session_id in tasks table**

In `src/ainrf/task_harness/service.py`, add column in `initialize()`:

```python
self._ensure_column(
    connection,
    "task_harness_tasks",
    "session_id",
    "ALTER TABLE task_harness_tasks ADD COLUMN session_id TEXT",
)
```

- [ ] **Step 3: Save session_id when creating task**

In the method that creates a task row in `TaskHarnessService`, add `session_id` to the INSERT statement. Find the INSERT into `task_harness_tasks` and include `session_id` from `task_input.session_id`.

- [ ] **Step 4: Expose session_id in task serialization**

In the `_serialize_task_summary` or equivalent helper in `src/ainrf/api/routes/tasks.py`, add `session_id` to the output dict.

- [ ] **Step 5: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All tests pass (new field is optional, no regression).

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/task_harness/
git commit -m "feat: add session_id to TaskInput and task persistence"
```

---

## Task 6: Frontend Types + API

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/api/mock.ts`

- [ ] **Step 1: Add TypeScript types**

In `frontend/src/types/index.ts`, append:

```typescript
// ── Session types ──────────────────────────────────────

export type SessionStatus = 'active' | 'completed' | 'archived';
export type AttemptStatus = 'running' | 'completed' | 'failed' | 'interrupted';

export interface AttemptRecord {
  id: string;
  session_id: string;
  task_id: string | null;
  parent_attempt_id: string | null;
  attempt_seq: number;
  intervention_reason: string | null;
  status: AttemptStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  token_usage_json: string | null;
  created_at: string;
}

export interface SessionRecord {
  id: string;
  project_id: string;
  title: string;
  status: SessionStatus;
  task_count: number;
  total_duration_ms: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface SessionDetailRecord extends SessionRecord {
  attempts: AttemptRecord[];
}

export interface SessionListResponse {
  items: SessionRecord[];
}

export interface AttemptListResponse {
  items: AttemptRecord[];
}

export interface SessionCreateRequest {
  project_id: string;
  title: string;
}

export interface SessionUpdateRequest {
  title?: string | null;
  status?: string | null;
}
```

- [ ] **Step 2: Add API functions**

In `frontend/src/api/endpoints.ts`, append:

```typescript
import type {
  AttemptListResponse,
  SessionCreateRequest,
  SessionDetailRecord,
  SessionListResponse,
  SessionRecord,
  SessionUpdateRequest,
} from '../types';
```

```typescript
// ── Session endpoints ───────────────────────────────────

export const getSessions = (
  projectId?: string,
  status?: string,
): Promise<SessionListResponse> => {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  if (status) params.set('status', status);
  const qs = params.toString();
  return USE_MOCK
    ? Promise.resolve(mockGetSessions({ projectId, status }))
    : api.get<SessionListResponse>(`/sessions${qs ? `?${qs}` : ''}`);
};

export const getSession = (id: string): Promise<SessionDetailRecord> =>
  USE_MOCK
    ? Promise.resolve(mockGetSession(id))
    : api.get<SessionDetailRecord>(`/sessions/${id}`);

export const createSession = (
  payload: SessionCreateRequest,
): Promise<SessionRecord> =>
  USE_MOCK
    ? Promise.resolve(mockCreateSession(payload))
    : api.post<SessionRecord>('/sessions', payload);

export const updateSession = (
  id: string,
  payload: SessionUpdateRequest,
): Promise<SessionRecord> =>
  USE_MOCK
    ? Promise.resolve(mockUpdateSession(id, payload))
    : api.patch<SessionRecord>(`/sessions/${id}`, payload);

export const deleteSession = (id: string): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteSession(id))
    : api.delete<void>(`/sessions/${id}`);

export const getAttempts = (sessionId: string): Promise<AttemptListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetAttempts(sessionId))
    : api.get<AttemptListResponse>(`/sessions/${sessionId}/attempts`);
```

- [ ] **Step 3: Add mock functions**

In `frontend/src/api/mock.ts`, append:

```typescript
// ── Session mocks ───────────────────────────────────────

const _mockSessions: SessionRecord[] = [];

export function mockGetSessions(_filters?: {
  projectId?: string;
  status?: string;
}): SessionListResponse {
  return { items: _mockSessions };
}

export function mockGetSession(id: string): SessionDetailRecord {
  const s = _mockSessions.find((x) => x.id === id);
  if (!s) throw new ApiError(404, 'Session not found', `/sessions/${id}`);
  return { ...s, attempts: [] };
}

export function mockCreateSession(
  payload: SessionCreateRequest,
): SessionRecord {
  const s: SessionRecord = {
    id: `sess_${_mockSessions.length + 1}`,
    project_id: payload.project_id,
    title: payload.title,
    status: 'active',
    task_count: 0,
    total_duration_ms: 0,
    total_cost_usd: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  _mockSessions.unshift(s);
  return s;
}

export function mockUpdateSession(
  id: string,
  payload: SessionUpdateRequest,
): SessionRecord {
  const s = _mockSessions.find((x) => x.id === id);
  if (!s) throw new ApiError(404, 'Session not found', `/sessions/${id}`);
  if (payload.title !== undefined) s.title = payload.title;
  if (payload.status !== undefined)
    s.status = payload.status as SessionRecord['status'];
  s.updated_at = new Date().toISOString();
  return s;
}

export function mockDeleteSession(_id: string): void {
  const idx = _mockSessions.findIndex((x) => x.id === _id);
  if (idx >= 0) _mockSessions.splice(idx, 1);
}

export function mockGetAttempts(_sessionId: string): AttemptListResponse {
  return { items: [] };
}
```

Add the mock function imports at the top of `endpoints.ts`:
```typescript
import {
  // ... existing imports
  mockGetSessions,
  mockGetSession,
  mockCreateSession,
  mockUpdateSession,
  mockDeleteSession,
  mockGetAttempts,
} from './mock';
```

- [ ] **Step 4: Type-check frontend**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/endpoints.ts frontend/src/api/mock.ts
git commit -m "feat: add session types, API functions, and mocks"
```

---

## Task 7: SessionsPage + Subcomponents

**Files:**
- Create: `frontend/src/pages/SessionsPage.tsx`
- Create: `frontend/src/pages/sessions/SessionList.tsx`
- Create: `frontend/src/pages/sessions/SessionDetail.tsx`
- Create: `frontend/src/pages/sessions/AttemptChain.tsx`

- [ ] **Step 1: Write SessionsPage**

```typescript
// frontend/src/pages/SessionsPage.tsx
import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getSession, getSessions } from '../api';
import { PageShell } from '../components/layout/PageShell';
import { SplitPane } from '../components/layout/SplitPane';
import { useT } from '../i18n';
import type { SessionRecord } from '../types';
import { SessionDetail } from './sessions/SessionDetail';
import { SessionList } from './sessions/SessionList';

export default function SessionsPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);

  const sessionsQuery = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(),
    refetchInterval: 10000,
  });

  const sessions = useMemo(
    () => sessionsQuery.data?.items ?? [],
    [sessionsQuery.data],
  );

  const detailQuery = useQuery({
    queryKey: ['session', selectedId],
    queryFn: () => getSession(selectedId!),
    enabled: selectedId !== null,
  });

  const handleSelect = useCallback(
    (id: string) => {
      setSelectedId(id);
      queryClient.invalidateQueries({ queryKey: ['session', id] });
    },
    [queryClient],
  );

  return (
    <PageShell>
      <SplitPane
        sidebar={
          <SessionList
            sessions={sessions}
            selectedId={selectedId}
            onSelect={handleSelect}
            loading={sessionsQuery.isLoading}
          />
        }
        sidebarWidth={sidebarWidth}
        onSidebarWidthChange={setSidebarWidth}
      >
        <SessionDetail
          detail={detailQuery.data ?? null}
          loading={detailQuery.isLoading}
          selectedId={selectedId}
        />
      </SplitPane>
    </PageShell>
  );
}
```

- [ ] **Step 2: Write SessionList**

```typescript
// frontend/src/pages/sessions/SessionList.tsx
import { Input } from '../../components/ui/Input';
import { StatusDot } from '../../components/ui/StatusDot';
import { useT } from '../../i18n';
import type { SessionRecord } from '../../types';
import { useState } from 'react';

interface Props {
  sessions: SessionRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}

const STATUS_COLOR: Record<string, 'green' | 'yellow' | 'gray'> = {
  active: 'green',
  completed: 'yellow',
  archived: 'gray',
};

export function SessionList({ sessions, selectedId, onSelect, loading }: Props) {
  const t = useT();
  const [search, setSearch] = useState('');

  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3 p-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t('pages.sessions.sidebarTitle')}</h3>
        <span className="text-xs text-gray-500">
          {t('pages.sessions.sidebarCount', { count: sessions.length })}
        </span>
      </div>
      <Input
        placeholder={t('pages.sessions.searchPlaceholder')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {loading && filtered.length === 0 ? (
        <p className="text-sm text-gray-400 px-1">{t('common.loading')}</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-gray-400 px-1">{t('pages.sessions.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {filtered.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedId === s.id
                    ? 'bg-blue-50 border border-blue-200'
                    : 'hover:bg-gray-50 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2">
                  <StatusDot color={STATUS_COLOR[s.status] ?? 'gray'} />
                  <span className="font-medium truncate">{s.title}</span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                  <span>{t('pages.sessions.taskCount', { count: s.task_count })}</span>
                  <span>${s.total_cost_usd.toFixed(2)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write SessionDetail**

```typescript
// frontend/src/pages/sessions/SessionDetail.tsx
import { Badge } from '../../components/ui/Badge';
import { SectionStack } from '../../components/layout/SectionStack';
import { useT } from '../../i18n';
import type { SessionDetailRecord } from '../../types';
import { AttemptChain } from './AttemptChain';

interface Props {
  detail: SessionDetailRecord | null;
  loading: boolean;
  selectedId: string | null;
}

const STATUS_BADGE: Record<string, 'green' | 'yellow' | 'gray'> = {
  active: 'green',
  completed: 'yellow',
  archived: 'gray',
};

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function SessionDetail({ detail, loading, selectedId }: Props) {
  const t = useT();

  if (!selectedId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('pages.sessions.selectPrompt')}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('common.loading')}
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('pages.sessions.notFound')}
      </div>
    );
  }

  return (
    <div className="p-4">
      <SectionStack gap={4}>
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">{detail.title}</h2>
          <Badge
            variant={STATUS_BADGE[detail.status] ?? 'gray'}
            label={t(`pages.sessions.status.${detail.status}`)}
          />
        </div>

        <div className="flex items-center gap-6 text-sm text-gray-600">
          <span>{t('pages.sessions.taskCount', { count: detail.task_count })}</span>
          <span>
            {t('pages.sessions.totalDuration', {
              duration: formatDuration(detail.total_duration_ms),
            })}
          </span>
          <span>${detail.total_cost_usd.toFixed(2)}</span>
        </div>

        <AttemptChain attempts={detail.attempts} />
      </SectionStack>
    </div>
  );
}
```

- [ ] **Step 4: Write AttemptChain**

```typescript
// frontend/src/pages/sessions/AttemptChain.tsx
import { Badge } from '../../components/ui/Badge';
import { SectionStack } from '../../components/layout/SectionStack';
import { useT } from '../../i18n';
import type { AttemptRecord } from '../../types';

interface Props {
  attempts: AttemptRecord[];
}

const STATUS_BADGE: Record<string, 'green' | 'yellow' | 'red' | 'gray'> = {
  running: 'green',
  completed: 'yellow',
  failed: 'red',
  interrupted: 'gray',
};

function formatDuration(ms: number | null): string {
  if (ms === null) return '--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function AttemptChain({ attempts }: Props) {
  const t = useT();

  if (attempts.length === 0) {
    return <p className="text-sm text-gray-400">{t('pages.sessions.noAttempts')}</p>;
  }

  return (
    <SectionStack gap={2}>
      <h3 className="text-sm font-semibold text-gray-700">
        {t('pages.sessions.attemptsTitle')}
      </h3>
      <div className="relative pl-6">
        {attempts.map((a, i) => (
          <div key={a.id} className="relative pb-4 last:pb-0">
            {/* Timeline dot */}
            <div
              className={`absolute left-[-22px] top-[14px] w-3 h-3 rounded-full border-2 border-white z-10 ${
                a.status === 'running'
                  ? 'bg-blue-500 shadow-[0_0_0_2px_#bfdbfe]'
                  : a.status === 'completed'
                    ? 'bg-green-500'
                    : a.status === 'failed'
                      ? 'bg-red-500'
                      : 'bg-gray-400'
              }`}
            />
            {/* Connector line */}
            {i < attempts.length - 1 && (
              <div className="absolute left-[-16.5px] top-[26px] w-[1px] h-full bg-gray-200" />
            )}

            <div
              className={`rounded-lg border p-3 ${
                a.status === 'running'
                  ? 'bg-blue-50 border-blue-200'
                  : a.status === 'completed'
                    ? 'bg-green-50 border-green-200'
                    : a.status === 'failed'
                      ? 'bg-red-50 border-red-200'
                      : 'bg-yellow-50 border-yellow-200'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-sm">
                  {t('pages.sessions.attemptLabel', { seq: a.attempt_seq })}
                </span>
                <Badge
                  variant={STATUS_BADGE[a.status] ?? 'gray'}
                  label={t(`pages.sessions.attemptStatus.${a.status}`)}
                />
              </div>
              {a.intervention_reason && (
                <p className="text-xs text-gray-500 mt-1">{a.intervention_reason}</p>
              )}
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                {a.task_id && (
                  <a
                    href={`/tasks/${a.task_id}`}
                    className="text-blue-600 hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {t('pages.sessions.viewTask')}
                  </a>
                )}
                <span>{formatDuration(a.duration_ms)}</span>
                {a.token_usage_json && (
                  <span className="text-gray-400">
                    {t('pages.sessions.hasTokens')}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </SectionStack>
  );
}
```

- [ ] **Step 5: Type-check**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors. Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SessionsPage.tsx frontend/src/pages/sessions/
git commit -m "feat: add SessionsPage with SessionList, SessionDetail, AttemptChain"
```

---

## Task 8: Frontend Routing + i18n + Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/common/Layout.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Register route in App.tsx**

Add import:
```typescript
const SessionsPage = lazy(() => import('./pages/SessionsPage'));
```

Add route inside `<Routes>`:
```typescript
<Route path="/sessions" element={<SessionsPage />} />
```

- [ ] **Step 2: Add i18n keys**

In `frontend/src/i18n/messages.ts`, add to the `en` object under `pages`:

```typescript
sessions: {
  sidebarTitle: 'Sessions',
  sidebarCount: '{{count}} sessions',
  searchPlaceholder: 'Search sessions...',
  empty: 'No sessions yet',
  selectPrompt: 'Select a session to view details',
  notFound: 'Session not found',
  taskCount: '{{count}} tasks',
  totalDuration: 'Total {{duration}}',
  attemptsTitle: 'Attempts',
  noAttempts: 'No attempts recorded',
  attemptLabel: 'Attempt #{{seq}}',
  viewTask: 'View task',
  hasTokens: 'Token data',
  status: {
    active: 'Active',
    completed: 'Completed',
    archived: 'Archived',
  },
  attemptStatus: {
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
    interrupted: 'Interrupted',
  },
},
```

In the `zh` object under `pages`:

```typescript
sessions: {
  sidebarTitle: '会话',
  sidebarCount: '{{count}} 个会话',
  searchPlaceholder: '搜索会话...',
  empty: '暂无会话',
  selectPrompt: '选择一个会话查看详情',
  notFound: '未找到会话',
  taskCount: '{{count}} 个任务',
  totalDuration: '总计 {{duration}}',
  attemptsTitle: '尝试记录',
  noAttempts: '暂无尝试记录',
  attemptLabel: '尝试 #{{seq}}',
  viewTask: '查看任务',
  hasTokens: '有 Token 数据',
  status: {
    active: '活跃',
    completed: '已完成',
    archived: '已归档',
  },
  attemptStatus: {
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    interrupted: '已中断',
  },
},
```

Add to the `navigation` object (both `en` and `zh`):
```typescript
// In en.navigation:
sessions: { label: 'Sessions', description: 'Research session history' },

// In zh.navigation:
sessions: { label: '会话', description: '研究会话历史' },
```

- [ ] **Step 3: Add navigation item in Layout.tsx**

In `frontend/src/components/common/Layout.tsx`:

Add to `navigationItems` array:
```typescript
{
  label: t('navigation.sessions.label'),
  to: '/sessions',
  description: t('navigation.sessions.description'),
  icon: History,
}
```

Add `History` to the lucide-react imports:
```typescript
import { ..., History, ... } from 'lucide-react';
```

Add to `ROUTE_TITLE_KEYS`:
```typescript
'/sessions': 'navigation.sessions.label',
```

- [ ] **Step 4: Type-check**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/common/Layout.tsx frontend/src/i18n/messages.ts
git commit -m "feat: add /sessions route, i18n, and navigation item"
```

---

## Task 9: Frontend Tests

**Files:**
- Create: `frontend/src/pages/SessionsPage.test.tsx`

- [ ] **Step 1: Write SessionsPage tests**

```typescript
// frontend/src/pages/SessionsPage.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import SessionsPage from './SessionsPage';
import * as api from '../api';

vi.mock('../api', () => ({
  getSessions: vi.fn(),
  getSession: vi.fn(),
}));

const mockGetSessions = vi.mocked(api.getSessions);
const mockGetSession = vi.mocked(api.getSession);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockGetSessions.mockResolvedValue({ items: [] });
  mockGetSession.mockResolvedValue({
    id: 's1',
    project_id: 'p1',
    title: 'Test',
    status: 'active',
    task_count: 0,
    total_duration_ms: 0,
    total_cost_usd: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    attempts: [],
  });
});

describe('SessionsPage', () => {
  it('renders the session list sidebar', async () => {
    mockGetSessions.mockResolvedValue({
      items: [
        {
          id: 's1',
          project_id: 'p1',
          title: 'My Session',
          status: 'active',
          task_count: 2,
          total_duration_ms: 5000,
          total_cost_usd: 1.5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    });

    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getByText('My Session')).toBeInTheDocument();
    });
  });

  it('shows empty state when no sessions', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getByText('No sessions yet')).toBeInTheDocument();
    });
  });

  it('prompts to select a session initially', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(
        screen.getByText('Select a session to view details'),
      ).toBeInTheDocument();
    });
  });

  it('loads session detail on click', async () => {
    mockGetSessions.mockResolvedValue({
      items: [
        {
          id: 's1',
          project_id: 'p1',
          title: 'My Session',
          status: 'active',
          task_count: 1,
          total_duration_ms: 1000,
          total_cost_usd: 0.5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    });

    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByText('My Session'));
    });

    await waitFor(() => {
      expect(mockGetSession).toHaveBeenCalledWith('s1');
    });
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run -- SessionsPage`
Expected: All tests pass.

- [ ] **Step 3: Run full frontend tests to verify no regression**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SessionsPage.test.tsx
git commit -m "test: add SessionsPage rendering tests"
```

---

## Task 10: Integration Verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -v`
Expected: All tests pass, including new test_sessions.py.

- [ ] **Step 2: Run full frontend test suite**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: All tests pass.

- [ ] **Step 3: Run frontend type-check**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors.

- [ ] **Step 4: Run backend linting**

Run: `cd /home/xuyang/code/scholar-agent && uv run ruff check src/ainrf/sessions/ src/ainrf/api/routes/sessions.py`
Expected: No linting errors.

- [ ] **Step 5: Commit if any fixes were made**

---

## What This Enables (Follow-up)

After this plan is complete:

1. **Token Track** — parse token_usage from agent-sdk events, populate `token_usage_json` in attempts, aggregate to `total_cost_usd` in sessions
2. **Timeline** — Gantt chart view across sessions, using attempt start/finish times + duration_ms

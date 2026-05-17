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

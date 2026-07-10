"""SQLite-backed :class:`SessionStore` adapter for Claude SDK transcript persistence.

Survives container restarts and volume recreation — when the local JSONL
transcript is absent, ``resume`` materializes from the DB.

Only :meth:`append` and :meth:`load` are required by the SDK; the remaining
methods are optional helpers for session management.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from claude_agent_sdk.types import (
    SessionKey,
    SessionListSubkeysKey,
    SessionStoreEntry,
    SessionStoreListEntry,
)

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbSessionStore:
    """SessionStore adapter backed by the agentic_researcher SQLite DB.

    Transcript entries are opaque JSON blobs — ``json.dumps`` / ``json.loads``
    round-trip is the only required invariant. The SDK handles batched append
    (~100ms cadence during turns, coalesced to once per turn) and single
    ``load()`` before subprocess spawn.

    Opens a fresh connection per call to avoid thread-safety issues.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        from ainrf.db.connection import connect

        return connect(self._db_path, row_factory=None)

    def _ensure_table(self) -> None:
        """Create the table if it doesn't exist (idempotent)."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_transcripts (
                    project_key TEXT NOT NULL,
                    session_id  TEXT NOT NULL,
                    subpath     TEXT NOT NULL DEFAULT '',
                    seq         INTEGER NOT NULL,
                    entry_json  TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    PRIMARY KEY (project_key, session_id, subpath, seq)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_transcripts_lookup
                ON session_transcripts(project_key, session_id, subpath)
                """
            )
            conn.commit()

    # ── Required by SessionStore ──────────────────────────────────────────

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        """Mirror a batch of transcript entries to the DB."""
        subpath = key.get("subpath") or ""
        now = _utc_now()
        with closing(self._connect()) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO session_transcripts
                    (project_key, session_id, subpath, seq, entry_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        key["project_key"],
                        key["session_id"],
                        subpath,
                        i,
                        json.dumps(entry, ensure_ascii=False),
                        now,
                    )
                    for i, entry in enumerate(entries)
                ],
            )
            conn.commit()

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        """Load a full session transcript for resume.

        Returns ``None`` when no entries exist for this key.
        """
        subpath = key.get("subpath") or ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT entry_json FROM session_transcripts
                WHERE project_key = ? AND session_id = ? AND subpath = ?
                ORDER BY seq
                """,
                (key["project_key"], key["session_id"], subpath),
            ).fetchall()
        if not rows:
            return None
        return [json.loads(row[0]) for row in rows]

    # ── Optional helpers ──────────────────────────────────────────────────

    async def delete(self, key: SessionKey) -> None:
        """Delete a session transcript. Cascades to subkeys when deleting main."""
        subpath = key.get("subpath") or ""
        with closing(self._connect()) as conn:
            if subpath:
                conn.execute(
                    """
                    DELETE FROM session_transcripts
                    WHERE project_key = ? AND session_id = ? AND subpath = ?
                    """,
                    (key["project_key"], key["session_id"], subpath),
                )
            else:
                conn.execute(
                    """
                    DELETE FROM session_transcripts
                    WHERE project_key = ? AND session_id = ?
                    """,
                    (key["project_key"], key["session_id"]),
                )
            conn.commit()

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        """List main sessions under a project_key."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT session_id, MAX(created_at) AS last_seen
                FROM session_transcripts
                WHERE project_key = ? AND subpath = ''
                GROUP BY session_id
                ORDER BY last_seen DESC
                """,
                (project_key,),
            ).fetchall()
        result: list[SessionStoreListEntry] = []
        for row in rows:
            ts = row[1]
            try:
                dt = datetime.fromisoformat(ts)
                mtime = int(dt.timestamp() * 1000)
            except (ValueError, OSError):
                mtime = 0
            result.append({"session_id": row[0], "mtime": mtime})
        return result

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        """List subagent transcript keys under a session."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT subpath FROM session_transcripts
                WHERE project_key = ? AND session_id = ? AND subpath != ''
                """,
                (key["project_key"], key["session_id"]),
            ).fetchall()
        return [row[0] for row in rows]

"""Read-only Workspace registry facade backed by the v2 control plane.

The legacy registry persists ``workspaces.json`` and creates a seed workspace
when initialized.  A v2 process must be able to serve terminal and file
lookups without performing either of those writes, so this deliberately small
adapter exposes just the read shape used by those consumers.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ainrf.db import connect, run_pending
from ainrf.workspaces.models import WorkspaceRecord
from ainrf.workspaces.service import WorkspaceNotFoundError


def _datetime(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _workspace_prompt(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    prompt = payload.get("workspace_prompt")
    return prompt if isinstance(prompt, str) else ""


class PersistentWorkspaceFacade:
    """Adapt durable Workspace rows to legacy read-only consumers.

    ``WorkspaceRecord.project_id`` is a legacy compatibility field.  It is
    populated only from the imported immutable ``legacy_project_id`` and is
    never inferred from an arbitrary active Project link.
    """

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def initialize(self) -> None:
        """Retain the legacy registry lifecycle interface without side effects."""

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ? AND status = 'active'",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        return self._record(row)

    def list_workspaces(
        self,
        project_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[WorkspaceRecord]:
        clauses = ["workspace.status = 'active'"]
        params: list[object] = []
        if owner_user_id is not None:
            clauses.append("workspace.owner_user_id = ?")
            params.append(owner_user_id)
        join = ""
        if project_id is not None:
            join = (
                " JOIN project_workspace_links AS link"
                " ON link.workspace_id = workspace.workspace_id"
            )
            clauses.append("link.project_id = ? AND link.status = 'active'")
            params.append(project_id)
        where = " AND ".join(clauses)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT workspace.* FROM workspaces AS workspace{join} "
                f"WHERE {where} ORDER BY workspace.updated_at DESC, workspace.workspace_id",
                params,
            ).fetchall()
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: sqlite3.Row) -> WorkspaceRecord:
        legacy_project_id = row["legacy_project_id"]
        return WorkspaceRecord(
            workspace_id=str(row["workspace_id"]),
            project_id=str(legacy_project_id) if legacy_project_id is not None else "",
            label=str(row["label"]),
            description=str(row["description"]) if row["description"] is not None else None,
            default_workdir=str(row["canonical_path"]),
            workspace_prompt=_workspace_prompt(row["context_metadata_json"]),
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            owner_user_id=str(row["owner_user_id"]),
        )

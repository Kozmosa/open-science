"""Read-only persistent Environment facade for runtime consumers.

The legacy Environment registry is process-local.  Runtime consumers such as
the terminal, file browser, and monitor need a small compatibility object, but
their source of truth in v2 must be the control-plane SQLite database.  This
facade deliberately does not probe or write detection state while listing an
Environment; detection remains an independent observation concern.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from ainrf.db import connect, run_pending
from ainrf.environments.models import EnvironmentAuthKind, EnvironmentRegistryEntry
from ainrf.environments.service import EnvironmentNotFoundError


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _connection_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): item for key, item in parsed.items()}


def _port(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1 <= value <= 65535 else 22
    if not isinstance(value, str):
        return 22
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 22
    return port if 1 <= port <= 65535 else 22


class PersistentEnvironmentFacade:
    """Adapt durable v2 Environment rows to the existing runtime entry shape."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_environments(
        self, *, include_disabled: bool = False
    ) -> list[EnvironmentRegistryEntry]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM environments
                WHERE ? OR status = 'active'
                ORDER BY alias, environment_id
                """,
                (int(include_disabled),),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def get_environment(self, environment_id: str) -> EnvironmentRegistryEntry:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
        if row is None:
            raise EnvironmentNotFoundError(environment_id)
        return self._entry_from_row(row)

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> EnvironmentRegistryEntry:
        connection = _connection_object(row["connection_json"])
        raw_auth_kind = connection.get("auth_kind", EnvironmentAuthKind.SSH_KEY.value)
        try:
            auth_kind = EnvironmentAuthKind(str(raw_auth_kind))
        except ValueError:
            auth_kind = EnvironmentAuthKind.SSH_KEY
        tags_value = connection.get("tags", [])
        tags = [str(tag) for tag in tags_value] if isinstance(tags_value, list) else []
        ssh_options_value = connection.get("ssh_options", {})
        ssh_options = (
            {str(key): str(value) for key, value in ssh_options_value.items()}
            if isinstance(ssh_options_value, dict)
            else {}
        )
        return EnvironmentRegistryEntry(
            id=str(row["environment_id"]),
            alias=str(row["alias"]),
            display_name=str(row["display_name"]),
            description=_optional_text(row["description"]),
            is_seed=bool(row["is_seed"]),
            tags=tags,
            host=str(connection.get("host", "")),
            port=_port(connection.get("port", 22)),
            user=str(connection.get("user", "root")),
            auth_kind=auth_kind,
            identity_file=_optional_text(connection.get("identity_file")),
            proxy_jump=_optional_text(connection.get("proxy_jump")),
            proxy_command=_optional_text(connection.get("proxy_command")),
            ssh_options=ssh_options,
            default_workdir=_optional_text(connection.get("default_workdir")),
            preferred_python=_optional_text(connection.get("preferred_python")),
            preferred_env_manager=_optional_text(connection.get("preferred_env_manager")),
            preferred_runtime_notes=_optional_text(connection.get("preferred_runtime_notes")),
            task_harness_profile=_optional_text(connection.get("task_harness_profile")),
            created_at=_optional_datetime(row["created_at"]),
            updated_at=_optional_datetime(row["updated_at"]),
        )

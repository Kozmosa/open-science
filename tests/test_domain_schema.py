"""Domain v2 additive schema and database-constraint tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect, run_pending

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _domain_db(tmp_path: Path):
    database = connect(tmp_path / "domain.sqlite3")
    run_pending(database, "agentic_researcher")
    return database


def test_domain_schema_has_core_control_tables(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "projects",
        "environments",
        "workspaces",
        "project_workspace_links",
        "domain_cutover_state",
    } <= tables


def test_domain_schema_enforces_one_active_primary(tmp_path: Path) -> None:
    with closing(_domain_db(tmp_path)) as conn:
        conn.execute(
            "INSERT INTO projects VALUES ('p', 'u', 'P', NULL, 'active', 0, NULL, NULL, 't', 't')"
        )
        conn.execute(
            "INSERT INTO environments VALUES ('e', 'env', NULL, 'Env', NULL, '{}', NULL, 0, 'active', 't', 't')"
        )
        for workspace_id in ("w1", "w2"):
            conn.execute(
                "INSERT INTO workspaces VALUES (?, 'u', 'e', ?, ?, NULL, '{}', 'active', NULL, 't', 't')",
                (workspace_id, f"/tmp/{workspace_id}", workspace_id),
            )
        conn.execute(
            "INSERT INTO project_workspace_links VALUES ('p', 'w1', 'active', 1, 'u', 't', 't')"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO project_workspace_links VALUES ('p', 'w2', 'active', 1, 'u', 't', 't')"
            )

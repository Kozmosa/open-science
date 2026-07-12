"""Shadow importer and reconciliation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.domain_migration import DomainImporter

pytestmark = [pytest.mark.unit]


def _write_json(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"items": items}), encoding="utf-8")


def test_importer_is_idempotent_and_reports_unmapped_owner(state_root: Path) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    runtime = state_root / "runtime"
    _write_json(
        runtime / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": user.id}],
    )
    _write_json(
        runtime / "workspaces.json",
        [
            {
                "workspace_id": "w1",
                "project_id": "p1",
                "owner_user_id": user.id,
                "default_workdir": "/tmp/domain-import-w1",
            }
        ],
    )

    importer = DomainImporter(state_root)
    first = importer.run()
    second = importer.run()

    assert first.status == "completed"
    assert first.imported_count >= 3
    assert second.run_id == first.run_id
    assert not first.cutover_allowed


def test_importer_marks_unmapped_owner_blocking(state_root: Path) -> None:
    runtime = state_root / "runtime"
    _write_json(
        runtime / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": "missing"}],
    )

    report = DomainImporter(state_root).run()

    assert report.blocking_issue_count == 1
    assert report.attention_needed_count == 1


def test_reconciliation_refuses_cutover_when_constraints_or_default_are_missing(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    user = auth.register(username="alice", display_name="Alice", password="secret-password")
    _write_json(
        state_root / "runtime" / "projects.json",
        [{"project_id": "p1", "name": "Project", "owner_user_id": user.id}],
    )

    importer = DomainImporter(state_root)
    run = importer.run()
    reconciliation = importer.reconcile(run.run_id)

    assert not reconciliation.cutover_allowed
    assert "default_project_missing" in reconciliation.blocking_issues
    assert "constraints_not_ready" in reconciliation.blocking_issues

"""Control-plane-only overview snapshot tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.agentic_researcher import AgenticResearcherService, HarnessEngineType, vanilla
from ainrf.domain import DomainService, OverviewSnapshotService

pytestmark = [pytest.mark.unit]


def test_overview_snapshot_reads_only_persisted_control_plane(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    project = DomainService(state_root).create_project(owner, name="Project")
    tasks = AgenticResearcherService(state_root)
    tasks.initialize()
    tasks.create_task(
        str(project["project_id"]),
        "workspace",
        "environment",
        vanilla(HarnessEngineType.CLAUDE_CODE),
        "prompt",
        "owner",
    )

    snapshots = OverviewSnapshotService(state_root)
    refreshed = snapshots.refresh("owner")

    assert refreshed["source"] == "control_plane_only"
    assert refreshed["tasks_by_status"] == {"queued": 1}
    assert snapshots.latest("owner") == refreshed

"""Control-plane-only overview snapshot tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ainrf.domain import OverviewSnapshotService

pytestmark = [pytest.mark.unit]


def test_overview_snapshot_reads_only_persisted_control_plane(
    state_root: Path, committed_v2_state: str
) -> None:
    snapshots = OverviewSnapshotService(state_root, artifact_sha=committed_v2_state)
    refreshed_job = snapshots.request_refresh(
        "owner-ready", now=datetime(2026, 7, 12, 1, tzinfo=UTC)
    )
    result = snapshots.run_job(
        str(refreshed_job["job_id"]),
        "overview-snapshot-test",
        now=datetime(2026, 7, 12, 1, tzinfo=UTC),
    )

    assert result.outcome == "partial"
    refreshed = snapshots.latest("owner-ready")
    assert refreshed is not None
    assert refreshed["source"] == "control_plane_only"
    assert refreshed["projects_active"] == 1
    assert refreshed["tasks_by_status"] == {}
    display_cards = refreshed["display_cards"]
    assert isinstance(display_cards, list)
    display_payloads = [cast(dict[str, object], card) for card in display_cards]
    assert [card["id"] for card in display_payloads] == [
        "attention",
        "progress",
        "literature",
        "continue",
        "resources",
    ]
    assert refreshed["next_scheduled_at"] == "2026-07-12T22:00:00+00:00"
    assert snapshots.latest("owner-ready") == refreshed

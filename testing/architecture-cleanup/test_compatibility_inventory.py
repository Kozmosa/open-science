"""Local-only completeness checks for the compatibility and evidence inventory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.architecture_cleanup]

_INVENTORY_PATH = Path(__file__).with_name("compatibility_inventory.json")
_EVIDENCE_PATH = Path(__file__).with_name("release_evidence.json")


def test_compatibility_inventory_covers_every_required_surface() -> None:
    payload = json.loads(_INVENTORY_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["final_state"] == "delete"
    categories = {item["category"] for item in payload["items"]}
    assert categories == {"writer", "reader", "adapter", "field", "fixture", "config"}
    for item in payload["items"]:
        assert item["id"]
        assert item["surface"]
        assert item["owner"] in {"P1", "P4", "P5", "P6"}
        assert item["replacement"]
        assert item["removal_phase"] in {"P1", "P4", "P5", "P6"}
        assert item["deadline"]
        assert item["evidence"]


def test_release_evidence_has_auditable_sources_and_freshness() -> None:
    payload = json.loads(_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["release_commit"]
    assert payload["observations"]
    dimensions = {item["dimension"] for item in payload["observations"]}
    assert dimensions == {"domain_mode", "deprecated_traffic", "client_prefix"}
    for item in payload["observations"]:
        assert item["status"] in {"verified", "budgeted"}
        assert item["evidence_type"] in {"runtime", "release-config", "telemetry-budget"}
        assert item["observed_at"]
        assert item["evidence"]
        assert item["owner"]

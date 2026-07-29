"""Local-only completeness checks for the compatibility and evidence inventory."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from support.architecture import deprecated_contract_surfaces, openapi_inventory

pytestmark = [pytest.mark.architecture_cleanup]

_INVENTORY_PATH = Path(__file__).with_name("compatibility_inventory.json")
_EVIDENCE_PATH = Path(__file__).with_name("release_evidence.json")
_DELETION_CANDIDATES_PATH = Path(__file__).with_name("deletion_candidates.json")
_DEPRECATED_SURFACE_PATH = Path(__file__).with_name("deprecated_contract_allowlist.json")
_COMPATIBILITY_FIELDS_PATH = Path(__file__).with_name("compatibility_fields.json")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


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


def test_deprecated_contract_surface_does_not_expand() -> None:
    payload = json.loads(_DEPRECATED_SURFACE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["owner"] == "P4"
    assert payload["removal_phase"] == "P4"
    assert payload["final_state"] == "delete"
    for item in payload["items"]:
        assert item["owner"] == "P4"
        assert item["replacement"]
        assert item["expires_when"]
    assert deprecated_contract_surfaces(_REPO_ROOT) == [
        {"source": item["source"], "surface": item["surface"]} for item in payload["items"]
    ], "deprecated contract allowlist is monotonic; remove entries instead of adding surfaces"


def test_compatibility_fields_are_individually_inventoried() -> None:
    payload = json.loads(_COMPATIBILITY_FIELDS_PATH.read_text(encoding="utf-8"))
    schema, _routes = openapi_inventory()
    components = _mapping(schema["components"])
    schemas = _mapping(components["schemas"])
    assert payload["owner"] == "P4"
    assert payload["removal_phase"] == "P4"
    assert payload["final_state"] == "delete"
    assert payload["common_replacement"]
    observed: set[tuple[str, str]] = set()
    for item in payload["items"]:
        schema_name = item["schema"]
        field_name = item["field"]
        assert item["kind"] in {"request_field", "response_field", "response_flat_projection"}
        schema_item = _mapping(schemas[schema_name])
        properties = _mapping(schema_item.get("properties", {}))
        assert field_name in properties
        observed.add((schema_name, field_name))
    actual_idempotency_fields: set[tuple[str, str]] = set()
    for schema_name, schema_value in schemas.items():
        schema_item = _mapping(schema_value)
        properties = _mapping(schema_item.get("properties", {}))
        if "idempotency_key" in properties:
            actual_idempotency_fields.add((schema_name, "idempotency_key"))
    assert actual_idempotency_fields <= observed


def test_release_evidence_has_auditable_sources_and_freshness() -> None:
    payload = json.loads(_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["baseline_commit"]
    assert payload["runtime_target"] == "production loopback nginx"
    assert payload["observations"]
    dimensions = {item["dimension"] for item in payload["observations"]}
    assert dimensions == {"domain_mode", "deprecated_traffic", "client_prefix"}
    for item in payload["observations"]:
        assert item["status"] in {"verified", "observed_gap"}
        assert item["evidence_type"] in {"runtime", "release-config", "telemetry-budget"}
        assert item["observed_at"]
        assert item["result"]
        assert item["evidence"]
        assert item["owner"]


def test_direct_deletion_candidates_remain_unused_and_bounded() -> None:
    payload = json.loads(_DELETION_CANDIDATES_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["phase"] == "P0"
    assert payload["final_state"] == "delete"
    for item in payload["items"]:
        candidate_path = _REPO_ROOT / item["path"]
        assert candidate_path.is_file()
        assert item["owner"] == "P2"
        assert item["removal_phase"] == "P2"
        assert item["reason"]
        assert item["replacement"]
        assert item["delete_when"]
        for symbol in item["symbols"]:
            callers = []
            for root_name in ("src", "scripts"):
                for path in (_REPO_ROOT / root_name).rglob("*.py"):
                    if path == candidate_path:
                        continue
                    if symbol in path.read_text(encoding="utf-8"):
                        callers.append(path.relative_to(_REPO_ROOT).as_posix())
            assert not callers, f"deletion candidate {symbol} gained callers: {callers}"


def test_grafana_dashboard_exposes_route_and_field_call_volume() -> None:
    dashboard_path = _REPO_ROOT / "deploy/config/grafana/dashboards/ainrf/ainrf-overview.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    targets = [
        target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", [])
    ]
    assert any("ainrf_deprecated_contract_calls_total" in expression for expression in targets)
    assert any("ainrf_deprecated_route_calls_total" in expression for expression in targets)

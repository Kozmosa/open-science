"""Local-only OpenAPI snapshot and canonical route inventory guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support.architecture import openapi_inventory, stable_digest

pytestmark = [pytest.mark.architecture_cleanup]

_SNAPSHOT_PATH = Path(__file__).with_name("transport_snapshot.json")


def test_openapi_and_route_inventory_match_reviewed_snapshot() -> None:
    expected = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    schema, routes = openapi_inventory()
    paths = schema["paths"]
    assert isinstance(paths, dict)
    assert expected["schema_version"] == 1
    assert expected["owner"] == "P4"
    assert expected["removal_phase"] == "P6"
    assert expected["final_state"] == "delete"
    assert expected["openapi"] == {
        "version": schema["openapi"],
        "path_count": len(paths),
        "operation_count": len(routes),
        "sha256": stable_digest(schema),
    }
    canonical_routes = [route for route in routes if route["path"].startswith("/api/")]
    root_routes = [
        route
        for route in routes
        if not route["path"].startswith("/api/") and not route["path"].startswith("/v1/")
    ]
    v1_routes = [route for route in routes if route["path"].startswith("/v1/")]
    assert expected["routes"] == {
        "all_count": len(routes),
        "all_sha256": stable_digest(routes),
        "canonical_api_count": len(canonical_routes),
        "canonical_api_sha256": stable_digest(canonical_routes),
        "root_alias_count": len(root_routes),
        "v1_alias_count": len(v1_routes),
        "deprecated_operations": {
            "count": len([route for route in routes if route["deprecated"]]),
            "sha256": stable_digest([route for route in routes if route["deprecated"]]),
        },
    }


def test_canonical_prefix_inventory_is_explicit() -> None:
    expected = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    prefixes = expected["client_prefix_inventory"]
    assert prefixes["canonical"] == "/api"
    assert prefixes["aliases"] == ["/", "/v1"]
    assert prefixes["owner"] == "P4"
    assert prefixes["removal_phase"] == "P5"
    assert prefixes["evidence"]

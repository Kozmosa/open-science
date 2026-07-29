"""Local-only architecture graph and public Interface snapshot guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support.architecture import (
    forbidden_backend_imports,
    import_cycles,
    python_import_edges,
    python_public_interface,
    stable_digest,
)

pytestmark = [pytest.mark.architecture_cleanup]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASELINE_PATH = Path(__file__).with_name("architecture_baseline.json")
_ALLOWLIST_PATH = Path(__file__).with_name("backend_api_import_allowlist.json")


def test_python_import_graph_and_public_interface_match_reviewed_baseline() -> None:
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    edges = python_import_edges(_REPO_ROOT)
    interface = python_public_interface(_REPO_ROOT)

    assert baseline["schema_version"] == 1
    assert baseline["owner"] == "architecture-cleanup P0-P3"
    assert baseline["removal_phase"] == "P6"
    assert baseline["final_state"] == "delete"
    assert baseline["python_import_graph"] == {
        "edge_count": len(edges),
        "sha256": stable_digest(edges),
        "cycles": import_cycles(edges),
    }
    assert baseline["python_public_interface"] == {
        "item_count": len(interface),
        "sha256": stable_digest(interface),
    }


def test_non_api_to_api_imports_do_not_expand() -> None:
    payload = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    actual = forbidden_backend_imports(python_import_edges(_REPO_ROOT))

    assert payload["schema_version"] == 1
    assert payload["policy"] == "non-api modules must not import ainrf.api"
    assert payload["owner"] == "P2"
    assert payload["removal_phase"] == "P2"
    assert payload["final_state"] == "delete"
    allowed = payload["items"]
    for item in allowed:
        assert item["source"]
        assert item["target"].startswith("ainrf.api")
        assert item["owner"] == "P2"
        assert item["reason"]
        assert item["replacement"]
        assert item["expires_when"]
    assert actual == [{"source": item["source"], "target": item["target"]} for item in allowed], (
        "non-api -> api allowlist is monotonic; remove resolved entries instead of rebasing it"
    )


def test_p2_backend_dependency_direction_is_closed() -> None:
    edges = python_import_edges(_REPO_ROOT)

    assert forbidden_backend_imports(edges) == []
    assert import_cycles(edges) == []
    worker_targets = {edge["target"] for edge in edges if edge["source"] == "ainrf.domain.worker"}
    assert "ainrf.harness_engine.base" in worker_targets
    assert not any(target.startswith("ainrf.harness_engine.engines") for target in worker_targets)
    assert "ainrf.auth.service" not in worker_targets


def test_p2_neutral_modules_own_shared_runtime_capabilities() -> None:
    assert (_REPO_ROOT / "src/ainrf/telemetry/metrics.py").is_file()
    assert (_REPO_ROOT / "src/ainrf/telemetry/sla.py").is_file()
    assert (_REPO_ROOT / "src/ainrf/runtime/tenant_identity.py").is_file()
    assert (_REPO_ROOT / "src/ainrf/runtime/product_config.py").is_file()

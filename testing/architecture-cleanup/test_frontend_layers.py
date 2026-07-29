"""Local-only frontend dependency direction guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support.architecture import frontend_layer_violations

pytestmark = [pytest.mark.architecture_cleanup]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWLIST_PATH = Path(__file__).with_name("frontend_layer_allowlist.json")


def test_frontend_layer_violations_do_not_expand() -> None:
    payload = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["owner"] == "P5"
    assert payload["removal_phase"] == "P5"
    assert payload["final_state"] == "delete"
    for item in payload["items"]:
        assert item["owner"] == "P5"
        assert item["reason"]
        assert item["replacement"]
        assert item["expires_when"]
    assert frontend_layer_violations(_REPO_ROOT) == [
        {"source": item["source"], "target": item["target"], "rule": item["rule"]}
        for item in payload["items"]
    ], "frontend layer allowlist is monotonic; remove resolved entries instead of rebasing it"

"""Local-only monotonic guards for the temporary Release E debt ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

pytestmark = [pytest.mark.architecture_cleanup]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = Path(__file__).with_name("release_e_debt.json")
_COMPATIBILITY_BUDGET_PATH = Path(__file__).with_name("release_e_compatibility_budget.json")
_REQUIRED_ITEM_FIELDS = {
    "id",
    "category",
    "owner",
    "removal_phase",
    "status",
    "replacement",
    "evidence_paths",
    "rules",
}


class ScanRule(TypedDict):
    needle: str
    roots: list[str]
    suffixes: list[str]
    max_occurrences: int
    allowed_files: list[str]


class DebtItem(TypedDict):
    id: str
    category: str
    owner: str
    removal_phase: str
    status: str
    replacement: str
    evidence_paths: list[str]
    rules: list[ScanRule]


class DebtManifest(TypedDict):
    schema_version: int
    phase: str
    final_state: str
    items: list[DebtItem]


def _load_manifest() -> DebtManifest:
    payload = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(DebtManifest, payload)


def _matching_files(rule: ScanRule) -> dict[str, int]:
    matches: dict[str, int] = {}
    suffixes = frozenset(rule["suffixes"])
    for root_name in rule["roots"]:
        root = _REPO_ROOT / root_name
        assert root.exists(), f"scan root does not exist: {root_name}"
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix not in suffixes:
                continue
            count = path.read_text(encoding="utf-8").count(rule["needle"])
            if count:
                matches[path.relative_to(_REPO_ROOT).as_posix()] = count
    return matches


def test_release_e_debt_ledger_has_explicit_lifecycle() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == 1
    assert manifest["phase"] == "P1-D"
    assert manifest["final_state"] == "delete"
    ids: set[str] = set()
    categories: set[str] = set()
    for item in manifest["items"]:
        assert _REQUIRED_ITEM_FIELDS <= item.keys()
        assert item["id"] not in ids
        ids.add(item["id"])
        categories.add(item["category"])
        assert item["owner"]
        assert item["removal_phase"] == "P1-D"
        assert item["status"] == "closed"
        assert item["replacement"]

    assert categories == {
        "authority_mode",
        "config_deploy",
        "domain_modules",
        "http_contract",
        "persistence",
        "tests_docs",
        "worker_runtime",
    }


def test_closed_debt_evidence_is_present() -> None:
    for item in _load_manifest()["items"]:
        assert item["evidence_paths"], f"closed debt item lacks evidence: {item['id']}"
        missing = [path for path in item["evidence_paths"] if not (_REPO_ROOT / path).exists()]
        assert not missing, f"update debt evidence for {item['id']}: missing {missing}"


def test_retained_compatibility_has_bounded_followup_ownership() -> None:
    payload = json.loads(_COMPATIBILITY_BUDGET_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["recorded_phase"] == "P1-D"
    assert payload["decision"] == (
        "retained protocol adapters do not own or read legacy domain authority"
    )
    items = payload["items"]
    assert items
    for item in items:
        assert item["surface"]
        assert item["owner"] in {"P4", "P5"}
        assert item["replacement"]
        assert item["earliest_removal_phase"] in {"P4", "P5"}
        assert item["deadline"]
        assert item["reason"]


def test_legacy_surface_does_not_expand() -> None:
    for item in _load_manifest()["items"]:
        for rule in item["rules"]:
            matches = _matching_files(rule)
            unexpected_files = sorted(set(matches) - set(rule["allowed_files"]))
            assert not unexpected_files, (
                f"legacy surface expanded for {item['id']} / {rule['needle']!r}: "
                f"new files {unexpected_files}"
            )
            occurrence_count = sum(matches.values())
            assert occurrence_count <= rule["max_occurrences"], (
                f"legacy surface expanded for {item['id']} / {rule['needle']!r}: "
                f"{occurrence_count} > {rule['max_occurrences']}"
            )

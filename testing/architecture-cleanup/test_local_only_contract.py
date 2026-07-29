"""Prove the temporary cleanup suite remains disconnected from normal gates."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.architecture_cleanup]

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cleanup_suite_is_not_wired_into_repository_gates() -> None:
    forbidden_references: list[str] = []
    candidates = [
        _REPO_ROOT / "pyproject.toml",
        _REPO_ROOT / "scripts" / "ci.sh",
        _REPO_ROOT / "scripts" / "test.sh",
        *sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")),
        *sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yaml")),
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if "architecture-cleanup" in text or "architecture_cleanup" in text:
            forbidden_references.append(path.relative_to(_REPO_ROOT).as_posix())
    assert not forbidden_references, (
        "cleanup-only guards must not enter normal pytest, L0/L1, or workflows: "
        f"{forbidden_references}"
    )


def test_every_cleanup_test_declares_only_the_private_marker() -> None:
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        assert "pytestmark = [pytest.mark.architecture_cleanup]" in text, path.name
        for marker_name in ("api", "unit", "integration"):
            forbidden_marker = f"pytest.mark.{marker_name}"
            assert forbidden_marker not in text, (
                f"{path.name} uses normal marker {forbidden_marker}"
            )

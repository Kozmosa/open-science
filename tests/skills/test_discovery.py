from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainrf.skills.discovery import SkillsDiscoveryService
from ainrf.skills.models import InjectMode, SkillDefinition, SkillItem

pytestmark = [pytest.mark.unit]


def _make_skill_dir(parent: Path, skill_id: str, label: str, inject_mode: str = "auto") -> Path:
    """Create a valid skill directory with skill.json and SKILL.md."""
    skill_dir = parent / skill_id
    skill_dir.mkdir()
    skill_data = {
        "skill_id": skill_id,
        "label": label,
        "inject_mode": inject_mode,
    }
    (skill_dir / "skill.json").write_text(json.dumps(skill_data))
    (skill_dir / "SKILL.md").write_text(f"# {label}\n\nDescription here.\n")
    return skill_dir


def test_discover_full_returns_definitions(tmp_path: Path) -> None:
    """discover_full() returns full SkillDefinition objects from scan roots."""
    root = tmp_path / "skills"
    root.mkdir()

    _make_skill_dir(root, "skill-one", "Skill One", "auto")
    _make_skill_dir(root, "skill-two", "Skill Two", "prompt_only")

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover_full()

    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, SkillDefinition) for r in results)

    by_id = {r.skill_id: r for r in results}
    assert "skill-one" in by_id
    assert "skill-two" in by_id
    assert by_id["skill-one"].label == "Skill One"
    assert by_id["skill-one"].inject_mode == InjectMode.AUTO
    assert by_id["skill-two"].label == "Skill Two"
    assert by_id["skill-two"].inject_mode == InjectMode.PROMPT_ONLY


def test_discover_returns_items_from_physical_skills(tmp_path: Path) -> None:
    """discover() returns SkillItem objects for the same physical skills."""
    root = tmp_path / "skills"
    root.mkdir()

    _make_skill_dir(root, "skill-one", "Skill One")
    _make_skill_dir(root, "skill-two", "Skill Two")

    service = SkillsDiscoveryService(scan_roots=[root])
    items = service.discover()
    full = service.discover_full()

    assert all(isinstance(item, SkillItem) for item in items)
    assert {item.skill_id for item in items} == {skill.skill_id for skill in full}
    assert {item.skill_id for item in items} == {"skill-one", "skill-two"}


def test_discover_and_discover_full_use_same_scan_rules(tmp_path: Path) -> None:
    """Both methods discover the same set of skills from scan roots."""
    root = tmp_path / "skills-root"
    root.mkdir()
    subdir = root / "skills"
    subdir.mkdir()

    _make_skill_dir(root, "root-skill", "Root Skill")
    _make_skill_dir(subdir, "subdir-skill", "Subdir Skill")

    service = SkillsDiscoveryService(scan_roots=[root])
    item_ids = {item.skill_id for item in service.discover()}
    full_ids = {skill.skill_id for skill in service.discover_full()}

    assert item_ids == full_ids
    assert item_ids == {"root-skill", "subdir-skill"}


def test_discover_full_deduplicates(tmp_path: Path) -> None:
    """When two scan roots have overlapping skill IDs, first root wins."""
    root1 = tmp_path / "skills1"
    root1.mkdir()
    root2 = tmp_path / "skills2"
    root2.mkdir()

    _make_skill_dir(root1, "shared-skill", "Shared From Root1", "auto")
    _make_skill_dir(root2, "shared-skill", "Shared From Root2", "prompt_only")

    service = SkillsDiscoveryService(scan_roots=[root1, root2])
    results = service.discover_full()

    assert len(results) == 1
    assert results[0].skill_id == "shared-skill"
    assert results[0].label == "Shared From Root1"
    assert results[0].inject_mode == InjectMode.AUTO


def test_discover_full_empty_roots() -> None:
    """discover_full() with no scan roots returns empty list."""
    service = SkillsDiscoveryService(scan_roots=[])
    assert service.discover_full() == []
    assert service.discover() == []


def test_discover_full_skips_invalid(tmp_path: Path) -> None:
    """discover_full() skips invalid directories (missing SKILL.md)."""
    root = tmp_path / "skills"
    root.mkdir()

    _make_skill_dir(root, "valid-skill", "Valid Skill")

    # Invalid skill — missing SKILL.md
    invalid_dir = root / "invalid-skill"
    invalid_dir.mkdir()
    (invalid_dir / "skill.json").write_text(
        json.dumps({"skill_id": "invalid-skill", "label": "Invalid"})
    )

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover_full()

    assert len(results) == 1
    assert results[0].skill_id == "valid-skill"


def test_discover_full_reads_package(tmp_path: Path) -> None:
    """discover_full() reads package field from skill.json."""
    root = tmp_path / "skills"
    root.mkdir()

    skill_dir = root / "packaged-skill"
    skill_dir.mkdir()
    skill_data = {
        "skill_id": "packaged-skill",
        "label": "Packaged Skill",
        "inject_mode": "auto",
        "package": "aris",
    }
    (skill_dir / "skill.json").write_text(json.dumps(skill_data))
    (skill_dir / "SKILL.md").write_text("# Packaged Skill\n\nDescription.\n")

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover_full()

    assert len(results) == 1
    assert results[0].skill_id == "packaged-skill"
    assert results[0].package == "aris"


def test_discover_no_virtual_skills(tmp_path: Path) -> None:
    """discover() no longer returns virtual built-in skills when scan roots are empty."""
    service = SkillsDiscoveryService(scan_roots=[tmp_path / "empty"])
    results = service.discover()
    assert results == []

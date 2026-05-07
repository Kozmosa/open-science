from __future__ import annotations

import json
from pathlib import Path


from ainrf.skills.discovery import SkillsDiscoveryService
from ainrf.skills.models import InjectMode, SkillDefinition


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
    results = service.discover_full()
    assert results == []


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


def test_discover_full_returns_builtin_and_scanned(tmp_path: Path) -> None:
    """discover_full() does NOT include builtins; discover() does."""
    root = tmp_path / "skills-root"
    root.mkdir()
    # discover_full scans immediate subdirectories of root
    _make_skill_dir(root, "scanned-skill", "Scanned Skill")
    # discover scans skills/ subdirectory under root
    skills_subdir = root / "skills"
    skills_subdir.mkdir()
    _make_skill_dir(skills_subdir, "scanned-skill", "Scanned Skill")

    service = SkillsDiscoveryService(scan_roots=[root])

    full_results = service.discover_full()
    discover_results = service.discover()

    # discover_full should only have the scanned skill (no builtins)
    full_ids = {s.skill_id for s in full_results}
    assert "scanned-skill" in full_ids
    assert "web-search" not in full_ids
    assert "code-analysis" not in full_ids

    # discover should have builtins + scanned skill
    discover_ids = {s.skill_id for s in discover_results}
    assert "scanned-skill" in discover_ids
    assert "web-search" in discover_ids
    assert "code-analysis" in discover_ids


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


def test_discover_reads_package_from_skills_json(tmp_path: Path) -> None:
    """discover() reads package field from skills.json files."""
    root = tmp_path / "skills-root"
    root.mkdir()
    skills_subdir = root / "skills"
    skills_subdir.mkdir()

    skills_json = skills_subdir / "skills.json"
    skills_json.write_text(
        json.dumps([
            {"skill_id": "json-skill", "label": "JSON Skill", "package": "my-pkg"}
        ])
    )

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover()

    by_id = {s.skill_id: s for s in results}
    assert "json-skill" in by_id
    assert by_id["json-skill"].package == "my-pkg"

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ainrf.skills.mount import (
    SkillSelectionError,
    cleanup_workspace_skills,
    prepare_workspace_skills,
    resolve_workspace_skills,
)

pytestmark = [pytest.mark.unit]


def _make_skill(
    root: Path,
    skill_id: str,
    *,
    dependencies: list[str] | None = None,
    inject_mode: str = "auto",
) -> Path:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    manifest: dict[str, object] = {
        "skill_id": skill_id,
        "label": skill_id,
        "dependencies": dependencies or [],
        "inject_mode": inject_mode,
    }
    (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
    return skill_dir


def test_resolve_workspace_skills_returns_dependency_first_deduplicated_order(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "skills"
    _make_skill(registry, "shared")
    _make_skill(registry, "analysis", dependencies=["shared"])
    _make_skill(registry, "writing", dependencies=["shared"])

    assert resolve_workspace_skills(registry, ["analysis", "writing", "analysis"]) == [
        "shared",
        "analysis",
        "writing",
    ]


@pytest.mark.parametrize("requested", [["../escape"], ["missing"]])
def test_resolve_workspace_skills_rejects_unsafe_or_missing_selection(
    tmp_path: Path,
    requested: list[str],
) -> None:
    registry = tmp_path / "skills"
    registry.mkdir()

    with pytest.raises(SkillSelectionError):
        resolve_workspace_skills(registry, requested)


def test_resolve_workspace_skills_rejects_disabled_dependency(tmp_path: Path) -> None:
    registry = tmp_path / "skills"
    _make_skill(registry, "disabled", inject_mode="disabled")
    _make_skill(registry, "analysis", dependencies=["disabled"])

    with pytest.raises(SkillSelectionError, match="disabled"):
        resolve_workspace_skills(registry, ["analysis"])


def test_resolve_workspace_skills_rejects_corrupt_cycle_and_escaping_source(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "skills"
    first = _make_skill(registry, "first", dependencies=["second"])
    _make_skill(registry, "second", dependencies=["first"])
    with pytest.raises(SkillSelectionError, match="cycle"):
        resolve_workspace_skills(registry, ["first"])

    (first / "skill.json").write_text("{", encoding="utf-8")
    with pytest.raises(SkillSelectionError, match="manifest is invalid"):
        resolve_workspace_skills(registry, ["first"])

    external = tmp_path / "external"
    _make_skill(external, "escaped")
    (registry / "escaped").symlink_to(external / "escaped", target_is_directory=True)
    with pytest.raises(SkillSelectionError, match="escapes"):
        resolve_workspace_skills(registry, ["escaped"])


def test_prepare_workspace_skills_rejects_real_path_shadow(tmp_path: Path) -> None:
    registry = tmp_path / "skills"
    _make_skill(registry, "analysis")
    workspace_skill = tmp_path / "workspace" / ".claude" / "skills" / "analysis"
    workspace_skill.mkdir(parents=True)

    with pytest.raises(SkillSelectionError, match="shadows"):
        prepare_workspace_skills(
            str(tmp_path / "workspace"),
            str(registry),
            ["analysis"],
        )


def test_prepare_workspace_skills_preserves_correct_registry_symlink(tmp_path: Path) -> None:
    registry = tmp_path / "skills"
    source = _make_skill(registry, "analysis").resolve()
    workspace_skill = tmp_path / "workspace" / ".claude" / "skills" / "analysis"
    workspace_skill.parent.mkdir(parents=True)
    workspace_skill.symlink_to(source, target_is_directory=True)

    cleanup = prepare_workspace_skills(
        str(tmp_path / "workspace"),
        str(registry),
        ["analysis"],
    )

    assert cleanup == []
    assert workspace_skill.resolve() == source


def test_prepare_workspace_skills_fails_closed_on_tenant_mkdir_failure(tmp_path: Path) -> None:
    registry = tmp_path / "skills"
    _make_skill(registry, "analysis")
    results = [
        subprocess.CompletedProcess([], 0, stdout="missing", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr="permission denied"),
    ]

    with (
        patch("ainrf.skills.mount.subprocess.run", side_effect=results),
        pytest.raises(SkillSelectionError, match="directory creation"),
    ):
        prepare_workspace_skills(
            str(tmp_path / "tenant-workspace"),
            str(registry),
            ["analysis"],
            tenant_user="ainrf_tenant",
        )


def test_prepare_workspace_skills_fails_closed_on_tenant_unlink_failure(tmp_path: Path) -> None:
    registry = tmp_path / "skills"
    _make_skill(registry, "analysis")
    results = [
        subprocess.CompletedProcess([], 0, stdout="symlink", stderr=""),
        subprocess.CompletedProcess([], 0, stdout=str(tmp_path / "stale"), stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr="permission denied"),
    ]

    with (
        patch("ainrf.skills.mount.subprocess.run", side_effect=results),
        pytest.raises(SkillSelectionError, match="symlink removal"),
    ):
        prepare_workspace_skills(
            str(tmp_path / "tenant-workspace"),
            str(registry),
            ["analysis"],
            tenant_user="ainrf_tenant",
        )


def test_cleanup_workspace_skills_uses_tenant_authority_and_verifies_removal(
    tmp_path: Path,
) -> None:
    mounted_path = tmp_path / "tenant-workspace" / ".claude" / "skills" / "analysis"
    results = [
        subprocess.CompletedProcess([], 0, stdout="symlink", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="missing", stderr=""),
    ]

    with patch("ainrf.skills.mount.subprocess.run", side_effect=results) as run:
        cleanup_workspace_skills([mounted_path], tenant_user="ainrf_tenant")

    assert run.call_count == 3
    assert run.call_args_list[1].args[0][:5] == [
        "sudo",
        "-n",
        "-u",
        "ainrf_tenant",
        "rm",
    ]

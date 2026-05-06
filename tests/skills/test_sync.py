from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.skills.sync import sync_ainrf_to_claude, write_managed_marker


def test_sync_creates_symlink(tmp_path: Path) -> None:
    """When claude_skills doesn't exist, a symlink is created pointing to ainrf_skills."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    ainrf_skills.mkdir(parents=True)
    (ainrf_skills / "skill.json").write_text("{}")

    claude_skills = tmp_path / ".claude" / "skills"

    sync_ainrf_to_claude(ainrf_skills, claude_skills)

    assert claude_skills.is_symlink()
    assert claude_skills.resolve() == ainrf_skills.resolve()


def test_sync_symlink_already_correct(tmp_path: Path) -> None:
    """When claude_skills is already a symlink to ainrf_skills, do nothing (idempotent)."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    ainrf_skills.mkdir(parents=True)
    (ainrf_skills / "skill.json").write_text("{}")

    claude_skills = tmp_path / ".claude" / "skills"
    claude_skills.parent.mkdir(parents=True)
    claude_skills.symlink_to(ainrf_skills)

    sync_ainrf_to_claude(ainrf_skills, claude_skills)

    assert claude_skills.is_symlink()
    assert claude_skills.resolve() == ainrf_skills.resolve()


def test_sync_replaces_wrong_symlink(tmp_path: Path) -> None:
    """When claude_skills is a symlink pointing elsewhere, replace it."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    ainrf_skills.mkdir(parents=True)
    (ainrf_skills / "skill.json").write_text("{}")

    other_dir = tmp_path / "other" / "skills"
    other_dir.mkdir(parents=True)
    (other_dir / "other.json").write_text("{}")

    claude_skills = tmp_path / ".claude" / "skills"
    claude_skills.parent.mkdir(parents=True)
    claude_skills.symlink_to(other_dir)

    sync_ainrf_to_claude(ainrf_skills, claude_skills)

    assert claude_skills.is_symlink()
    assert claude_skills.resolve() == ainrf_skills.resolve()
    assert not claude_skills.resolve() == other_dir.resolve()


def test_sync_copy_fallback_when_directory_exists(tmp_path: Path) -> None:
    """When claude_skills exists as a real directory with files, back it up and copy."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    ainrf_skills.mkdir(parents=True)
    (ainrf_skills / "skill.json").write_text('{"id": "ainrf"}')

    claude_skills = tmp_path / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "old.json").write_text('{"id": "old"}')

    sync_ainrf_to_claude(ainrf_skills, claude_skills)

    # Should be a real directory now, not a symlink
    assert claude_skills.is_dir()
    assert not claude_skills.is_symlink()

    # Content should be copied from ainrf_skills
    assert (claude_skills / "skill.json").exists()
    assert (claude_skills / "skill.json").read_text() == '{"id": "ainrf"}'

    # Backup should exist
    backups = list((tmp_path / ".claude").glob("skills.bak.*"))
    assert len(backups) == 1
    assert (backups[0] / "old.json").exists()


def test_sync_writes_managed_marker(tmp_path: Path) -> None:
    """After any sync, .ainrf-managed marker file exists in the parent directory."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    ainrf_skills.mkdir(parents=True)
    (ainrf_skills / "skill.json").write_text("{}")

    claude_skills = tmp_path / ".claude" / "skills"

    sync_ainrf_to_claude(ainrf_skills, claude_skills)

    marker = claude_skills.parent / ".ainrf-managed"
    assert marker.exists()
    assert marker.read_text().strip() == "managed by ainrf"


def test_sync_raises_when_ainrf_missing(tmp_path: Path) -> None:
    """If ainrf_skills doesn't exist, raise FileNotFoundError."""
    ainrf_skills = tmp_path / ".ainrf" / "skills"
    claude_skills = tmp_path / ".claude" / "skills"

    with pytest.raises(FileNotFoundError):
        sync_ainrf_to_claude(ainrf_skills, claude_skills)


def test_write_managed_marker(tmp_path: Path) -> None:
    """write_managed_marker creates the marker file with correct content."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    write_managed_marker(claude_dir)

    marker = claude_dir / ".ainrf-managed"
    assert marker.exists()
    assert marker.read_text().strip() == "managed by ainrf"

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path


_MARKER_CONTENT = "managed by ainrf\n"


def write_managed_marker(claude_dir: Path | str) -> None:
    """Write `.ainrf-managed` marker file in the Claude directory."""
    claude_dir = Path(claude_dir)
    marker = claude_dir / ".ainrf-managed"
    marker.write_text(_MARKER_CONTENT, encoding="utf-8")


def sync_ainrf_to_claude(ainrf_skills: Path | str, claude_skills: Path | str) -> None:
    """Sync the AINRF skills directory to the Claude skills directory.

    Strategy (in order):
    1. **Symlink** (preferred): If `claude_skills` doesn't exist or is a symlink
       pointing elsewhere, remove it and create a symlink:
       `claude_skills -> ainrf_skills`
    2. **Copy fallback**: If symlink fails (e.g., `claude_skills` already exists
       as a real directory with content), back it up as
       `claude_skills.bak.<timestamp>` then copy `ainrf_skills` tree into
       `claude_skills`.
    3. After sync, write a marker file at `claude_skills.parent / ".ainrf-managed"`
       containing a single line: `"managed by ainrf"`

    Args:
        ainrf_skills: Path to `.ainrf/skills/` directory
        claude_skills: Path to `.claude/skills/` (will be created/modified)
    """
    ainrf_skills = Path(ainrf_skills)
    claude_skills = Path(claude_skills)

    if not ainrf_skills.exists():
        raise FileNotFoundError(f"AINRF skills directory not found: {ainrf_skills}")

    # If already a symlink pointing to the correct target, do nothing
    if claude_skills.is_symlink() and claude_skills.resolve() == ainrf_skills.resolve():
        write_managed_marker(claude_skills.parent)
        return

    # Remove existing symlink if it points elsewhere (or is broken)
    if claude_skills.is_symlink():
        claude_skills.unlink()

    # Try symlink first
    try:
        claude_skills.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(ainrf_skills, claude_skills)
        write_managed_marker(claude_skills.parent)
        return
    except FileExistsError:
        # claude_skills exists as a real directory; fall through to copy fallback
        pass

    # Copy fallback: backup existing directory and copy tree
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = claude_skills.parent / f"{claude_skills.name}.bak.{timestamp}"
    shutil.move(str(claude_skills), str(backup_path))
    shutil.copytree(ainrf_skills, claude_skills)
    write_managed_marker(claude_skills.parent)

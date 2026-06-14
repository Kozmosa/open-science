from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_workspace_skills(
    working_directory: str,
    skill_load_dir: str,
    requested_skills: list[str],
    tenant_user: str | None = None,
) -> list[Path]:
    """Symlink requested skill directories into ``<workdir>/.claude/skills/``.

    Both Claude Code and the Claude Agent SDK discover skills by scanning
    ``.claude/skills/<name>/SKILL.md`` in the project directory.  This helper
    creates one symlink per requested skill that exists in the registry load
    directory, allowing any engine to inject the ARIS skill set into any
    workspace without copying files.

    When *tenant_user* is provided the mkdir and symlink operations are
    performed via ``sudo -u <tenant_user>`` so that the resulting
    directories and symlinks are owned by the tenant user (ainrf cannot
    write to tenant-owned workspace paths).

    Returns a list of symlink paths created (for cleanup).
    """
    workdir = Path(working_directory)
    claude_skills_dir = workdir / ".claude" / "skills"
    load_dir = Path(skill_load_dir)
    cleanup: list[Path] = []

    def _mkdir(p: Path) -> None:
        if p.exists():
            return
        if tenant_user:
            subprocess.run(
                ["sudo", "-u", tenant_user, "mkdir", "-p", str(p)],
                check=False,
                capture_output=True,
            )
        else:
            p.mkdir(parents=True, exist_ok=True)

    def _symlink(src: Path, dst: Path) -> None:
        if tenant_user:
            subprocess.run(
                ["sudo", "-u", tenant_user, "ln", "-sfn", str(src), str(dst)],
                check=False,
                capture_output=True,
            )
        else:
            os.symlink(str(src), str(dst))

    def _unlink(p: Path) -> None:
        if tenant_user:
            subprocess.run(
                ["sudo", "-u", tenant_user, "rm", "-f", str(p)],
                check=False,
                capture_output=True,
            )
        else:
            p.unlink(missing_ok=True)

    for skill_id in requested_skills:
        source = load_dir / skill_id
        if not source.is_dir():
            logger.debug("skill %s not found in load dir %s, skipping", skill_id, load_dir)
            continue

        dest = claude_skills_dir / skill_id
        # Skip if a non-symlink (user-owned) directory already exists.
        if dest.exists() and not dest.is_symlink():
            logger.debug("skill %s already exists as real dir, skipping", skill_id)
            continue
        # Remove stale symlink pointing to a different target.
        if dest.is_symlink():
            try:
                current_target = dest.resolve()
                if current_target == source.resolve():
                    continue
                _unlink(dest)
            except OSError:
                continue

        _mkdir(claude_skills_dir)
        try:
            _symlink(source, dest)
            if dest.exists() or dest.is_symlink():
                cleanup.append(dest)
                logger.debug("linked skill %s -> %s", dest, source)
        except OSError as exc:
            logger.warning("failed to symlink skill %s: %s", skill_id, exc)

    return cleanup

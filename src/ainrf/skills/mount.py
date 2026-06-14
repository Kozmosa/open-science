from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_skill_dependencies(load_dir: Path, requested: list[str]) -> list[str]:
    """Expand requested skills to include their declared dependencies.

    Reads ``skill.json`` from the load directory for each requested skill and
    recursively adds dependency skill IDs. Circular dependencies are broken by
    tracking visited skills. Missing dependencies are logged and skipped.

    Returns a topologically-ish ordered list with each dependency appearing
    before the skill that depends on it.
    """
    resolved: list[str] = []
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(skill_id: str) -> None:
        if skill_id in visited:
            return
        if skill_id in stack:
            logger.warning("circular dependency detected involving skill %s", skill_id)
            return

        stack.add(skill_id)
        skill_dir = load_dir / skill_id
        skill_json = skill_dir / "skill.json"
        deps: list[str] = []
        if skill_json.is_file():
            try:
                data = json.loads(skill_json.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    raw_deps = data.get("dependencies", [])
                    if isinstance(raw_deps, list):
                        deps = [str(d) for d in raw_deps if isinstance(d, str)]
            except (json.JSONDecodeError, OSError):
                pass

        for dep in deps:
            dep_dir = load_dir / dep
            if dep_dir.is_dir():
                visit(dep)
            else:
                logger.warning(
                    "dependency %s of skill %s not found in load dir %s, skipping",
                    dep,
                    skill_id,
                    load_dir,
                )

        stack.remove(skill_id)
        if skill_id not in visited:
            visited.add(skill_id)
            resolved.append(skill_id)

    for skill_id in requested:
        skill_dir = load_dir / skill_id
        if skill_dir.is_dir():
            visit(skill_id)
        else:
            logger.warning(
                "requested skill %s not found in load dir %s, skipping",
                skill_id,
                load_dir,
            )

    return resolved


def prepare_workspace_skills(
    working_directory: str,
    skill_load_dir: str,
    requested_skills: list[str],
    tenant_user: str | None = None,
) -> list[Path]:
    """Symlink requested skill directories (and their dependencies) into ``<workdir>/.claude/skills/``.

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

    skills_to_mount = _resolve_skill_dependencies(load_dir, requested_skills)

    for skill_id in skills_to_mount:
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

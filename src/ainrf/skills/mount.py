from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ainrf.skills.loader import SkillLoader
from ainrf.skills.models import InjectMode, SkillDefinition

logger = logging.getLogger(__name__)


class SkillSelectionError(RuntimeError):
    """A requested runtime skill set cannot be resolved or mounted safely."""


def _safe_skill_id(skill_id: str) -> bool:
    candidate = Path(skill_id)
    return (
        bool(skill_id)
        and "\x00" not in skill_id
        and not candidate.is_absolute()
        and candidate.parts == (skill_id,)
        and skill_id not in {".", ".."}
    )


def _resolve_load_dir(skill_load_dir: str | Path) -> Path:
    try:
        load_dir = Path(skill_load_dir).expanduser().resolve(strict=True)
    except OSError as exc:
        raise SkillSelectionError("Skill registry load directory is unavailable") from exc
    if not load_dir.is_dir():
        raise SkillSelectionError("Skill registry load directory is not a directory")
    return load_dir


def _load_skill(load_dir: Path, skill_id: str) -> tuple[Path, SkillDefinition]:
    if not _safe_skill_id(skill_id):
        raise SkillSelectionError(f"Skill ID {skill_id!r} is not a safe path component")

    source = load_dir / skill_id
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise SkillSelectionError(f"Skill {skill_id!r} is unavailable") from exc
    if not resolved_source.is_dir() or resolved_source.parent != load_dir:
        raise SkillSelectionError(f"Skill {skill_id!r} escapes the registry load directory")

    for required_name in ("skill.json", "SKILL.md"):
        required_path = source / required_name
        try:
            resolved_required = required_path.resolve(strict=True)
        except OSError as exc:
            raise SkillSelectionError(
                f"Skill {skill_id!r} is missing required file {required_name}"
            ) from exc
        if not resolved_required.is_file() or not resolved_required.is_relative_to(resolved_source):
            raise SkillSelectionError(
                f"Skill {skill_id!r} required file {required_name} escapes its directory"
            )

    try:
        skill = SkillLoader.load_from_directory(source)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise SkillSelectionError(f"Skill {skill_id!r} manifest is invalid") from exc
    if not isinstance(skill.dependencies, list) or not all(
        isinstance(dependency, str) for dependency in skill.dependencies
    ):
        raise SkillSelectionError(f"Skill {skill_id!r} dependencies must be a list of IDs")
    return resolved_source, skill


def resolve_workspace_skills(
    skill_load_dir: str | Path,
    requested_skills: Sequence[str],
) -> list[str]:
    """Resolve a requested skill set into strict dependency-first runtime order.

    Runtime selection is fail-closed: every requested skill and dependency must
    be a safe registry child with a valid manifest and ``SKILL.md``. Disabled,
    missing, corrupt, cyclic, or path-escaping selections raise
    :class:`SkillSelectionError` instead of silently reducing the grant.
    """

    if not requested_skills:
        return []
    load_dir = _resolve_load_dir(skill_load_dir)
    loaded: dict[str, SkillDefinition] = {}
    resolved: list[str] = []
    visited: set[str] = set()
    stack: list[str] = []

    def load(skill_id: str) -> SkillDefinition:
        if skill_id not in loaded:
            _, skill = _load_skill(load_dir, skill_id)
            loaded[skill_id] = skill
        return loaded[skill_id]

    def visit(skill_id: str) -> None:
        if skill_id in visited:
            return
        if skill_id in stack:
            cycle_start = stack.index(skill_id)
            cycle = [*stack[cycle_start:], skill_id]
            raise SkillSelectionError(f"Skill dependency cycle detected: {' -> '.join(cycle)}")

        skill = load(skill_id)
        if skill.inject_mode is InjectMode.DISABLED:
            raise SkillSelectionError(f"Skill {skill_id!r} is disabled")

        stack.append(skill_id)
        for dependency in skill.dependencies:
            if not _safe_skill_id(dependency):
                raise SkillSelectionError(
                    f"Skill {skill_id!r} dependency {dependency!r} is not a safe path component"
                )
            visit(dependency)
        stack.pop()
        visited.add(skill_id)
        resolved.append(skill_id)

    for requested_skill in requested_skills:
        if not isinstance(requested_skill, str):
            raise SkillSelectionError("Requested skills must be identified by strings")
        visit(requested_skill)
    return resolved


def _run_tenant_command(tenant_user: str, operation: str, command: list[str]) -> str:
    result = subprocess.run(
        ["sudo", "-n", "-u", tenant_user, *command],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SkillSelectionError(f"Tenant skill mount {operation} failed")
    return result.stdout.strip()


def _tenant_path_kind(tenant_user: str, path: Path) -> str:
    return _run_tenant_command(
        tenant_user,
        "inspection",
        [
            "sh",
            "-c",
            'if [ -L "$1" ]; then printf symlink; '
            'elif [ -e "$1" ]; then printf existing; else printf missing; fi',
            "skill-path-kind",
            str(path),
        ],
    )


def _tenant_resolve(tenant_user: str, path: Path) -> Path:
    resolved = _run_tenant_command(
        tenant_user,
        "path resolution",
        ["readlink", "-f", "--", str(path)],
    )
    if not resolved:
        raise SkillSelectionError("Tenant skill mount path resolution returned no path")
    return Path(resolved)


def prepare_workspace_skills(
    working_directory: str,
    skill_load_dir: str,
    requested_skills: list[str],
    tenant_user: str | None = None,
) -> list[Path]:
    """Mount a strict runtime skill selection under ``.claude/skills``.

    The returned paths are only the symlinks created by this call and may be
    removed by the runtime Adapter after execution. Existing symlinks already
    pointing at the canonical registry source are preserved and are not added
    to the cleanup list. Any real-file shadow, failed tenant operation, or
    registry inconsistency raises :class:`SkillSelectionError`.
    """

    skills_to_mount = resolve_workspace_skills(skill_load_dir, requested_skills)
    if not skills_to_mount:
        return []

    load_dir = _resolve_load_dir(skill_load_dir)
    sources = {skill_id: _load_skill(load_dir, skill_id)[0] for skill_id in skills_to_mount}
    workdir = Path(working_directory).expanduser()
    claude_skills_dir = workdir / ".claude" / "skills"
    cleanup: list[Path] = []

    def mkdir(path: Path) -> None:
        if tenant_user:
            _run_tenant_command(tenant_user, "directory creation", ["mkdir", "-p", "--", str(path)])
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SkillSelectionError("Workspace skill directory creation failed") from exc

    def unlink(path: Path) -> None:
        if tenant_user:
            _run_tenant_command(tenant_user, "symlink removal", ["rm", "-f", "--", str(path)])
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise SkillSelectionError("Workspace skill symlink removal failed") from exc

    def symlink(source: Path, destination: Path) -> None:
        if tenant_user:
            _run_tenant_command(
                tenant_user,
                "symlink creation",
                ["ln", "-s", "--", str(source), str(destination)],
            )
            return
        try:
            os.symlink(str(source), str(destination))
        except OSError as exc:
            raise SkillSelectionError("Workspace skill symlink creation failed") from exc

    pending: list[tuple[Path, Path, bool]] = []
    for skill_id in skills_to_mount:
        source = sources[skill_id]
        destination = claude_skills_dir / skill_id
        if tenant_user:
            destination_kind = _tenant_path_kind(tenant_user, destination)
            if destination_kind == "symlink":
                if _tenant_resolve(tenant_user, destination) == source:
                    continue
                pending.append((source, destination, True))
            elif destination_kind == "missing":
                pending.append((source, destination, False))
            else:
                raise SkillSelectionError(
                    f"Workspace path for skill {skill_id!r} shadows the registry selection"
                )
            continue

        if destination.is_symlink():
            try:
                current_target = destination.resolve(strict=True)
            except OSError:
                pending.append((source, destination, True))
            else:
                if current_target == source:
                    continue
                pending.append((source, destination, True))
        elif destination.exists():
            raise SkillSelectionError(
                f"Workspace path for skill {skill_id!r} shadows the registry selection"
            )
        else:
            pending.append((source, destination, False))

    try:
        if pending:
            mkdir(claude_skills_dir)
        for source, destination, replace_existing in pending:
            if replace_existing:
                unlink(destination)
            symlink(source, destination)
            cleanup.append(destination)
            logger.debug("linked skill %s -> %s", destination, source)
    except SkillSelectionError:
        for destination in reversed(cleanup):
            try:
                unlink(destination)
            except SkillSelectionError:
                logger.warning("failed to roll back workspace skill symlink %s", destination)
        raise

    return cleanup


def cleanup_workspace_skills(
    mounted_paths: Sequence[Path],
    *,
    tenant_user: str | None = None,
) -> None:
    """Remove symlinks created by :func:`prepare_workspace_skills`.

    Tenant-owned workspace paths are inspected and removed as the tenant user.
    A path that has changed into a real file or directory is never deleted.
    """

    for mounted_path in mounted_paths:
        if tenant_user:
            path_kind = _tenant_path_kind(tenant_user, mounted_path)
            if path_kind == "missing":
                continue
            if path_kind != "symlink":
                raise SkillSelectionError("Workspace skill cleanup path is no longer a symlink")
            _run_tenant_command(
                tenant_user,
                "symlink cleanup",
                ["rm", "-f", "--", str(mounted_path)],
            )
            if _tenant_path_kind(tenant_user, mounted_path) != "missing":
                raise SkillSelectionError("Tenant skill symlink cleanup could not be verified")
            continue

        if mounted_path.is_symlink():
            try:
                mounted_path.unlink()
            except OSError as exc:
                raise SkillSelectionError("Workspace skill symlink cleanup failed") from exc
        elif mounted_path.exists():
            raise SkillSelectionError("Workspace skill cleanup path is no longer a symlink")


def preflight_workspace_skills(
    working_directory: str,
    skill_load_dir: str,
    requested_skills: list[str],
    *,
    tenant_user: str | None = None,
) -> None:
    """Prove that a skill selection can be mounted and cleaned before delivery."""

    mounted_paths = prepare_workspace_skills(
        working_directory,
        skill_load_dir,
        requested_skills,
        tenant_user=tenant_user,
    )
    cleanup_workspace_skills(mounted_paths, tenant_user=tenant_user)

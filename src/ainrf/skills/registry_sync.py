"""Skill registry sync service: manages git workspace and syncs skills to load directory."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ainrf.skills.json_generator import generate_skill_json, parse_skill_md_frontmatter
from ainrf.skills.registry_models import SkillRegistryConfig, SkillRegistryStatus


_YAML_DELIM_RE = re.compile(r"^---\s*$", re.MULTILINE)


class DirtyWorktreeError(Exception):
    """Raised when the git workspace has uncommitted changes."""

    def __init__(self, files: list[str]) -> None:
        self.files = files
        super().__init__(f"Git worktree is dirty: {', '.join(files)}")


class SkillSyncError(RuntimeError):
    """Raised when skill validation or sync fails before any changes are made."""


class SkillRegistrySyncService:
    """Manages git clone/pull and one-way sync to the skills load directory."""

    def __init__(
        self,
        registry: SkillRegistryConfig,
        workspace_dir: Path,
        load_dir: Path,
    ) -> None:
        self.registry = registry
        self.workspace_dir = workspace_dir
        self.load_dir = load_dir
        self.git_workspace = workspace_dir / f"{registry.registry_id}-git-sync"

    def _managed_marker(self) -> Path:
        """Path to the registry-managed marker file in the load directory."""
        return self.load_dir / ".ainrf-registry"

    def _manifest_path(self) -> Path:
        """Path to the sync manifest file tracking skills installed by this registry."""
        return self.load_dir / ".ainrf-registry-manifest.json"

    def _backup_dir_for(self, skill_name: str, timestamp: str) -> Path:
        return self.load_dir / f"{skill_name}.bak.{timestamp}"

    def is_installed(self) -> bool:
        """Check if this registry has been installed in the load directory."""
        marker = self._managed_marker()
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip() == self.registry.registry_id
        return False

    def install(self) -> tuple[SkillRegistryStatus, list[str], list[str]]:
        """First-time install: clone repo and sync all skills.

        Returns:
            Tuple of (status, added_skill_names, removed_skill_names).
        """
        if self.git_workspace.exists():
            shutil.rmtree(self.git_workspace)

        try:
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    self.registry.git_ref,
                    self.registry.git_url,
                    str(self.git_workspace),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"git clone timed out after {exc.timeout}s") from exc
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr}")

        added, removed = self._sync_all()
        return self._build_status(), added, removed

    def check_update(self, bundled_source: Path | None = None) -> SkillRegistryStatus:
        """Check if remote has newer commits. Does not modify anything.

        Args:
            bundled_source: Optional bundled repo path (Docker).  When
                provided, the returned status includes the source's skill
                fingerprint.
        """
        if not self.git_workspace.exists():
            return self._build_status(bundled_source=bundled_source)

        remote_commit = self._git_ls_remote()
        local_commit = self._git_rev_parse()
        is_dirty = self._git_is_dirty()

        status = self._build_status(bundled_source=bundled_source)
        status.remote_commit = remote_commit
        status.local_commit = local_commit
        status.has_update = remote_commit is not None and remote_commit != local_commit
        status.is_dirty = is_dirty
        return status

    def update(self, force: bool = False) -> tuple[SkillRegistryStatus, list[str], list[str]]:
        """Pull latest and sync. Raises DirtyWorktreeError if dirty and not forced.

        If the git workspace is missing (e.g. was manually deleted), re-clones
        the repository before syncing.

        Returns:
            Tuple of (status, added_skill_names, removed_skill_names).
        """
        if not self.git_workspace.exists():
            # Git workspace missing but registry may still be "installed" in load_dir.
            # Re-clone and re-sync to restore consistency.
            return self.install()

        status = self.check_update()
        if status.is_dirty and not force:
            dirty_files = self._git_dirty_files()
            raise DirtyWorktreeError(dirty_files)

        if status.is_dirty and force:
            self._git_run(["reset", "--hard", "HEAD"])
            self._git_run(["clean", "-fd"])

        pull_result = self._git_run(["pull", "origin", self.registry.git_ref])
        if pull_result.returncode != 0:
            raise RuntimeError(f"git pull failed: {pull_result.stderr}")

        added, removed = self._sync_all()
        return self._build_status(), added, removed

    def rollback(self) -> tuple[list[str], list[str]]:
        """Rollback the most recent sync by restoring per-skill backups.

        Returns:
            Tuple of (restored_skill_names, backup_names_removed).
        """
        if not self.is_installed():
            raise RuntimeError("Registry is not installed; nothing to rollback")

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        restored: list[str] = []
        removed_backups: list[str] = []

        for backup in sorted(self.load_dir.glob("*.bak.*")):
            # Backup filename format: <skill_name>.bak.<timestamp>
            parts = backup.name.split(".bak.")
            if len(parts) != 2:
                continue
            skill_name = parts[0]
            target = self.load_dir / skill_name

            # Move current (failed) version aside and restore backup.
            failed_dir = self.load_dir / f"{skill_name}.failed.{timestamp}"
            if target.exists():
                shutil.move(str(target), str(failed_dir))
            shutil.move(str(backup), str(target))
            restored.append(skill_name)
            removed_backups.append(backup.name)

        return restored, removed_backups

    def _sync_all(self) -> tuple[list[str], list[str]]:
        """Sync all skills from git workspace to load directory atomically per skill.

        Each skill is written to a temporary directory, then the old skill
        directory is renamed to a timestamped backup and the temp directory is
        renamed into place. This keeps symlinks to unchanged skills valid during
        the sync and allows rollback if something goes wrong.

        Returns:
            Tuple of (added_skill_names, removed_skill_names).
        """
        source_root = self.git_workspace / self.registry.source_skills_path
        if not source_root.exists():
            raise RuntimeError(f"Source skills path not found: {source_root}")
        if not source_root.is_dir():
            raise RuntimeError(f"Source skills path is not a directory: {source_root}")

        self.load_dir.mkdir(parents=True, exist_ok=True)

        # Validate all source skills before touching the load directory.
        skill_dirs = self._find_skill_dirs(source_root)
        self._validate_source_skills(source_root, skill_dirs)

        # Read previous manifest to detect removed skills
        old_manifest = self._read_manifest()
        old_skills = set(old_manifest.get("skills", []))

        current_skills: list[str] = []
        core_set = set(self.registry.core_skill_ids)
        seen_basenames: set[str] = set()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        for rel_path in skill_dirs:
            source = source_root / rel_path
            basename = Path(rel_path).name
            if basename in seen_basenames:
                continue
            seen_basenames.add(basename)
            is_core = basename in core_set
            self._sync_skill_dir(source, self.load_dir, basename, is_core, timestamp)
            current_skills.append(basename)

        current_set = set(current_skills)

        # Remove skills that were previously synced but no longer exist in source
        removed = old_skills - current_set
        for orphaned in removed:
            orphaned_dir = self.load_dir / orphaned
            if orphaned_dir.exists():
                backup = self._backup_dir_for(orphaned, timestamp)
                shutil.move(str(orphaned_dir), str(backup))

        # Write manifest and marker
        manifest = {
            "registry_id": self.registry.registry_id,
            "skills": current_skills,
            "core_skill_ids": self.registry.core_skill_ids,
            "synced_at": datetime.now().isoformat(),
        }
        self._manifest_path().write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._managed_marker().write_text(self.registry.registry_id, encoding="utf-8")

        added = current_set - old_skills
        return (sorted(added), sorted(removed))

    def _validate_source_skills(self, source_root: Path, skill_dirs: list[str]) -> None:
        """Validate that every source skill has a readable SKILL.md.

        Raises SkillSyncError if any skill is missing required files or has
        invalid frontmatter. Validation happens before the load directory is
        modified so a bad source never leaves the install in a half-written state.
        """

        errors: list[str] = []
        for rel_path in skill_dirs:
            source = source_root / rel_path
            skill_md_path = source / "SKILL.md"
            if not skill_md_path.is_file():
                errors.append(f"{rel_path}: missing SKILL.md")
                continue
            try:
                content = skill_md_path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{rel_path}: cannot read SKILL.md: {exc}")
                continue

            # Replicate frontmatter parsing to surface YAML errors.
            if content.startswith("---"):
                end_match = _YAML_DELIM_RE.search(content, 3)
                if end_match:
                    yaml_block = content[3 : end_match.start()]
                    if yaml_block.strip():
                        try:
                            yaml.safe_load(yaml_block)
                        except yaml.YAMLError as exc:
                            errors.append(f"{rel_path}: invalid SKILL.md frontmatter: {exc}")

        if errors:
            raise SkillSyncError("Skill validation failed:\n" + "\n".join(errors))

    def source_skill_fingerprint(self, source_dir: Path | None = None) -> str:
        """Compute a fingerprint of available skills in a source directory.

        The fingerprint is the sorted, comma-joined list of skill directory
        names that contain a ``SKILL.md``.  Used to detect when a bundled
        repo has changed across Docker image rebuilds.

        Args:
            source_dir: Directory to scan.  Defaults to the git workspace.
        """
        root = source_dir or self.git_workspace
        source_skills = root / self.registry.source_skills_path
        if not source_skills.is_dir():
            return ""
        names = sorted(Path(rel).name for rel in self._find_skill_dirs(source_skills))
        return ",".join(names)

    def needs_resync(self, source_dir: Path) -> bool:
        """Check whether installed skills differ from a source directory.

        Compares the installed manifest's skill list against the skills
        available in *source_dir*.  Returns ``True`` when:
        - the registry is not installed, or
        - the installed skill set differs from the source skill set.
        """
        if not self.is_installed():
            return True
        manifest = self._read_manifest()
        installed = set(manifest.get("skills", []))
        source_fingerprint = self.source_skill_fingerprint(source_dir)
        source_set = set(source_fingerprint.split(",")) if source_fingerprint else set()
        return installed != source_set

    def resync_from_source(self, source_dir: Path) -> tuple[list[str], list[str]]:
        """Re-sync skills from an arbitrary source directory.

        Unlike ``install()`` and ``update()``, this does not require a git
        workspace.  It copies *source_dir* into the expected git-sync
        location and runs ``_sync_all()``.  Used by the Docker entrypoint
        to update skills when the bundled ARIS repo changes across image
        rebuilds.

        Returns:
            Tuple of (added_skill_names, removed_skill_names).
        """
        import shutil

        git_sync_dir = self.git_workspace
        if git_sync_dir.exists():
            shutil.rmtree(git_sync_dir)
        shutil.copytree(
            source_dir,
            git_sync_dir,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git"),
        )
        return self._sync_all()

    def _find_skill_dirs(self, root: Path) -> list[str]:
        """Recursively find all subdirectories under root that contain SKILL.md.

        Returns relative paths from root (e.g. 'skill-name' or 'nested/skill-name').
        """
        result: list[str] = []
        if not root.exists():
            return result
        for subdir in sorted(root.rglob("SKILL.md")):
            rel = subdir.parent.relative_to(root).as_posix()
            result.append(rel)
        return result

    def _sync_skill_dir(
        self,
        source: Path,
        dest_root: Path,
        skill_name: str,
        is_core: bool,
        timestamp: str,
    ) -> None:
        """Atomically sync a single skill: generate skill.json and copy SKILL.md."""
        dest = dest_root / skill_name
        tmp_dest = dest_root / f"{skill_name}.tmp.{timestamp}"

        if tmp_dest.exists():
            shutil.rmtree(tmp_dest)
        tmp_dest.mkdir(parents=True)

        skill_md_path = source / "SKILL.md"
        skill_md_content = skill_md_path.read_text(encoding="utf-8")
        frontmatter = parse_skill_md_frontmatter(skill_md_content)

        skill_json = generate_skill_json(skill_name, frontmatter, is_core)
        (tmp_dest / "skill.json").write_text(
            json.dumps(skill_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        shutil.copy2(skill_md_path, tmp_dest / "SKILL.md")

        # Backup existing directory if present, then atomically swap in tmp.
        if dest.exists():
            backup = self._backup_dir_for(skill_name, timestamp)
            if backup.exists():
                shutil.rmtree(backup)
            shutil.move(str(dest), str(backup))
        shutil.move(str(tmp_dest), str(dest))

    def _read_manifest(self) -> dict[str, Any]:
        """Read the sync manifest if it exists."""
        path = self._manifest_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _build_status(self, bundled_source: Path | None = None) -> SkillRegistryStatus:
        """Build current status from filesystem.

        Args:
            bundled_source: Optional path to a bundled repo (e.g. in Docker).
                When provided, includes the source's skill fingerprint in the
                status so the API can report whether a re-sync is needed.
        """
        manifest = self._read_manifest()
        # Only trust the manifest if it belongs to this registry
        if manifest.get("registry_id") == self.registry.registry_id:
            installed_count = len(manifest.get("skills", []))
        else:
            installed_count = 0

        last_sync_at = None
        marker = self._managed_marker()
        if marker.exists():
            try:
                mtime = marker.stat().st_mtime
                last_sync_at = datetime.fromtimestamp(mtime)
            except OSError:
                pass

        bundled_fp: str | None = None
        if bundled_source is not None and bundled_source.is_dir():
            bundled_fp = self.source_skill_fingerprint(bundled_source)

        backup_available = any(self.load_dir.glob("*.bak.*"))

        return SkillRegistryStatus(
            registry_id=self.registry.registry_id,
            installed=self.is_installed(),
            installed_count=installed_count,
            last_sync_at=last_sync_at,
            bundled_skill_fingerprint=bundled_fp,
            backup_available=backup_available,
        )

    def _git_run(self, args: list[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self.git_workspace), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"git command timed out after {exc.timeout}s: {' '.join(args)}"
            ) from exc

    def _git_ls_remote(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "ls-remote", self.registry.git_url, self.registry.git_ref],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0 or not result.stdout:
            return None
        # Output format: "<commit>\t<ref>\n"
        return result.stdout.split()[0] if result.stdout.split() else None

    def _git_rev_parse(self) -> str | None:
        result = self._git_run(["rev-parse", "HEAD"], timeout=10)
        return result.stdout.strip() if result.returncode == 0 else None

    def _git_is_dirty(self) -> bool:
        result = self._git_run(["status", "--porcelain"], timeout=10)
        return result.returncode == 0 and bool(result.stdout.strip())

    def _git_dirty_files(self) -> list[str]:
        result = self._git_run(["status", "--porcelain"], timeout=10)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

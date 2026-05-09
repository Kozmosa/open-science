"""Skill registry sync service: manages git workspace and syncs skills to load directory."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ainrf.skills.json_generator import generate_skill_json, parse_skill_md_frontmatter
from ainrf.skills.registry_models import SkillRegistryConfig, SkillRegistryStatus


class DirtyWorktreeError(Exception):
    """Raised when the git workspace has uncommitted changes."""

    def __init__(self, files: list[str]) -> None:
        self.files = files
        super().__init__(f"Git worktree is dirty: {', '.join(files)}")


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

    def check_update(self) -> SkillRegistryStatus:
        """Check if remote has newer commits. Does not modify anything."""
        if not self.git_workspace.exists():
            return self._build_status()

        remote_commit = self._git_ls_remote()
        local_commit = self._git_rev_parse()
        is_dirty = self._git_is_dirty()

        status = self._build_status()
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

    def _sync_all(self) -> tuple[list[str], list[str]]:
        """Sync all skills from git workspace to load directory.

        Returns:
            Tuple of (added_skill_names, removed_skill_names).
        """
        source_root = self.git_workspace / self.registry.source_skills_path
        if not source_root.exists():
            raise RuntimeError(f"Source skills path not found: {source_root}")
        if not source_root.is_dir():
            raise RuntimeError(f"Source skills path is not a directory: {source_root}")

        self.load_dir.mkdir(parents=True, exist_ok=True)

        # Read previous manifest to detect removed skills
        old_manifest = self._read_manifest()
        old_skills = set(old_manifest.get("skills", []))

        current_skills: list[str] = []
        core_set = set(self.registry.core_skill_ids)
        seen_basenames: set[str] = set()

        for rel_path in self._find_skill_dirs(source_root):
            source = source_root / rel_path
            basename = Path(rel_path).name
            if basename in seen_basenames:
                continue
            seen_basenames.add(basename)
            is_core = basename in core_set
            self._sync_skill_dir(source, self.load_dir, is_core)
            current_skills.append(basename)

        current_set = set(current_skills)

        # Remove skills that were previously synced but no longer exist in source
        removed = old_skills - current_set
        for orphaned in removed:
            orphaned_dir = self.load_dir / orphaned
            if orphaned_dir.exists():
                shutil.rmtree(orphaned_dir)

        # Write manifest and marker
        manifest = {
            "registry_id": self.registry.registry_id,
            "skills": current_skills,
            "synced_at": datetime.now().isoformat(),
        }
        self._manifest_path().write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._managed_marker().write_text(self.registry.registry_id, encoding="utf-8")

        added = current_set - old_skills
        return (sorted(added), sorted(removed))

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

    def _sync_skill_dir(self, source: Path, dest_root: Path, is_core: bool) -> None:
        """Sync a single skill: generate skill.json and copy SKILL.md."""
        skill_name = source.name
        dest = dest_root / skill_name
        dest.mkdir(parents=True, exist_ok=True)

        skill_md_path = source / "SKILL.md"
        skill_md_content = skill_md_path.read_text(encoding="utf-8")
        frontmatter = parse_skill_md_frontmatter(skill_md_content)

        skill_json = generate_skill_json(skill_name, frontmatter, is_core)
        (dest / "skill.json").write_text(
            json.dumps(skill_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        shutil.copy2(skill_md_path, dest / "SKILL.md")

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

    def _build_status(self) -> SkillRegistryStatus:
        """Build current status from filesystem."""
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

        return SkillRegistryStatus(
            registry_id=self.registry.registry_id,
            installed=self.is_installed(),
            installed_count=installed_count,
            last_sync_at=last_sync_at,
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

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ainrf.skills.registry_models import SkillRegistryConfig
from ainrf.skills.registry_sync import (
    DirtyWorktreeError,
    SkillRegistrySyncService,
)


class TestSkillRegistrySyncService:
    @pytest.fixture
    def registry(self):
        return SkillRegistryConfig(
            registry_id="test-registry",
            display_name="Test Registry",
            git_url="https://example.com/test.git",
            git_ref="main",
            source_skills_path="skills",
            core_skill_ids=["core-skill"],
        )

    @pytest.fixture
    def service(self, tmp_path: Path, registry):
        return SkillRegistrySyncService(
            registry=registry,
            workspace_dir=tmp_path,
            load_dir=tmp_path / "skills",
        )

    def test_git_workspace_path(self, service: SkillRegistrySyncService, tmp_path: Path):
        assert service.git_workspace == tmp_path / "test-registry-git-sync"

    def test_find_skill_dirs_finds_direct_children(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        skills_root = tmp_path / "skills"
        (skills_root / "skill-a").mkdir(parents=True)
        (skills_root / "skill-a" / "SKILL.md").write_text("# Skill A")
        (skills_root / "skill-b").mkdir(parents=True)
        (skills_root / "skill-b" / "SKILL.md").write_text("# Skill B")
        (skills_root / "not-a-skill.txt").write_text("nope")

        dirs = list(service._find_skill_dirs(skills_root))
        assert sorted(dirs) == ["skill-a", "skill-b"]

    def test_find_skill_dirs_skips_dirs_without_skill_md(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        skills_root = tmp_path / "skills"
        (skills_root / "empty-dir").mkdir(parents=True)
        (skills_root / "valid").mkdir(parents=True)
        (skills_root / "valid" / "SKILL.md").write_text("# Valid")

        dirs = list(service._find_skill_dirs(skills_root))
        assert dirs == ["valid"]

    def test_sync_skill_generates_skill_json(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        source = tmp_path / "source" / "my-skill"
        source.mkdir(parents=True)
        source.joinpath("SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\n\n# My Skill"
        )

        service._sync_skill_dir(source, tmp_path / "skills", is_core=False)

        skill_json_path = tmp_path / "skills" / "my-skill" / "skill.json"
        assert skill_json_path.exists()
        data = json.loads(skill_json_path.read_text())
        assert data["skill_id"] == "my-skill"
        assert data["inject_mode"] == "disabled"

    def test_sync_skill_core_uses_auto(self, service: SkillRegistrySyncService, tmp_path: Path):
        source = tmp_path / "source" / "core-skill"
        source.mkdir(parents=True)
        source.joinpath("SKILL.md").write_text("---\nname: core-skill\n---\n\n# Core")

        service._sync_skill_dir(source, tmp_path / "skills", is_core=True)

        data = json.loads((tmp_path / "skills" / "core-skill" / "skill.json").read_text())
        assert data["inject_mode"] == "auto"

    def test_sync_skill_copies_skill_md(self, service: SkillRegistrySyncService, tmp_path: Path):
        source = tmp_path / "source" / "my-skill"
        source.mkdir(parents=True)
        source.joinpath("SKILL.md").write_text("# Content")

        service._sync_skill_dir(source, tmp_path / "skills", is_core=False)

        md_path = tmp_path / "skills" / "my-skill" / "SKILL.md"
        assert md_path.exists()
        assert md_path.read_text() == "# Content"

    def test_is_installed_checks_marker_file(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        assert not service.is_installed()

        # Marker file with matching registry_id
        marker = tmp_path / "skills" / ".ainrf-registry"
        marker.parent.mkdir(parents=True)
        marker.write_text("test-registry", encoding="utf-8")

        assert service.is_installed()

    def test_is_installed_false_for_other_registry(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        marker = tmp_path / "skills" / ".ainrf-registry"
        marker.parent.mkdir(parents=True)
        marker.write_text("other-registry", encoding="utf-8")

        assert not service.is_installed()

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_check_update_detects_available_update(
        self, mock_run, service: SkillRegistrySyncService, tmp_path: Path
    ):
        service.git_workspace.mkdir(parents=True)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\trefs/heads/main\n"),
            MagicMock(returncode=0, stdout="def456\n"),
            MagicMock(returncode=0, stdout=""),
        ]

        status = service.check_update()

        assert status.has_update is True
        assert status.remote_commit == "abc123"
        assert status.local_commit == "def456"
        assert status.is_dirty is False

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_check_update_detects_dirty(
        self, mock_run, service: SkillRegistrySyncService, tmp_path: Path
    ):
        service.git_workspace.mkdir(parents=True)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\trefs/heads/main\n"),
            MagicMock(returncode=0, stdout="abc123\n"),
            MagicMock(returncode=0, stdout="M  skills/test/SKILL.md\n"),
        ]

        status = service.check_update()

        assert status.has_update is False
        assert status.is_dirty is True

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_update_raises_when_dirty_and_not_forced(
        self, mock_run, service: SkillRegistrySyncService, tmp_path: Path
    ):
        service.git_workspace.mkdir(parents=True)
        (tmp_path / "skills" / "x").mkdir(parents=True)
        (tmp_path / "skills" / "x" / "SKILL.md").write_text("# X")

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="remote\trefs/heads/main\n"),
            MagicMock(returncode=0, stdout="local\n"),
            MagicMock(returncode=0, stdout="M  file\n"),
            MagicMock(returncode=0, stdout="M  file\n"),
        ]

        with pytest.raises(DirtyWorktreeError):
            service.update(force=False)

    def test_sync_all_writes_manifest(self, service: SkillRegistrySyncService, tmp_path: Path):
        source_root = tmp_path / "source" / "skills"
        (source_root / "skill-a").mkdir(parents=True)
        (source_root / "skill-a" / "SKILL.md").write_text("# A")
        (source_root / "skill-b").mkdir(parents=True)
        (source_root / "skill-b" / "SKILL.md").write_text("# B")

        # Fake a git workspace
        service.git_workspace.mkdir(parents=True)
        import shutil

        shutil.copytree(source_root, service.git_workspace / "skills")

        added, removed = service._sync_all()

        assert added == ["skill-a", "skill-b"]
        assert removed == []

        manifest_path = tmp_path / "skills" / ".ainrf-registry-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["registry_id"] == "test-registry"
        assert sorted(manifest["skills"]) == ["skill-a", "skill-b"]
        assert "synced_at" in manifest

    def test_sync_all_removes_orphaned_skills(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        load_dir = tmp_path / "skills"
        load_dir.mkdir(parents=True)

        # Write old manifest with skill that no longer exists in source
        old_manifest = {
            "registry_id": "test-registry",
            "skills": ["old-skill", "keep-skill"],
            "synced_at": "2024-01-01T00:00:00",
        }
        (load_dir / ".ainrf-registry-manifest.json").write_text(
            json.dumps(old_manifest), encoding="utf-8"
        )
        (load_dir / ".ainrf-registry").write_text("test-registry", encoding="utf-8")

        # Create both skills in load dir
        (load_dir / "old-skill").mkdir()
        (load_dir / "old-skill" / "SKILL.md").write_text("# Old")
        (load_dir / "keep-skill").mkdir()
        (load_dir / "keep-skill" / "SKILL.md").write_text("# Keep")

        # Source only has keep-skill
        source_root = tmp_path / "source" / "skills"
        (source_root / "keep-skill").mkdir(parents=True)
        (source_root / "keep-skill" / "SKILL.md").write_text("# Keep")

        service.git_workspace.mkdir(parents=True)
        import shutil

        shutil.copytree(source_root, service.git_workspace / "skills")

        added, removed = service._sync_all()

        assert not (load_dir / "old-skill").exists()
        assert (load_dir / "keep-skill").exists()
        assert added == []  # keep-skill was already in manifest
        assert removed == ["old-skill"]

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_update_falls_back_to_install_when_git_workspace_missing(
        self, mock_run, service: SkillRegistrySyncService, tmp_path: Path
    ):
        """If git workspace is deleted but marker exists, update() re-clones."""
        load_dir = tmp_path / "skills"
        load_dir.mkdir(parents=True)
        (load_dir / ".ainrf-registry").write_text("test-registry", encoding="utf-8")

        def mock_clone(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "git" and "clone" in cmd:
                dest = Path(cmd[-1])
                (dest / "skills" / "test-skill").mkdir(parents=True)
                (dest / "skills" / "test-skill" / "SKILL.md").write_text("# Test")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_clone

        status, added, removed = service.update(force=False)

        assert status.installed is True
        assert "test-skill" in added

    def test_build_status_uses_manifest_for_count(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        load_dir = tmp_path / "skills"
        load_dir.mkdir(parents=True)

        # Write manifest with 2 skills
        manifest = {
            "registry_id": "test-registry",
            "skills": ["a", "b"],
            "synced_at": "2024-01-01T00:00:00",
        }
        (load_dir / ".ainrf-registry-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (load_dir / ".ainrf-registry").write_text("test-registry", encoding="utf-8")

        # Add a manually imported skill (not in manifest)
        (load_dir / "manual").mkdir()
        (load_dir / "manual" / "SKILL.md").write_text("# Manual")

        status = service._build_status()
        assert status.installed_count == 2
        assert status.installed is True

    def test_build_status_sets_last_sync_at_from_marker(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        load_dir = tmp_path / "skills"
        load_dir.mkdir(parents=True)
        (load_dir / ".ainrf-registry").write_text("test-registry", encoding="utf-8")

        status = service._build_status()
        assert status.last_sync_at is not None
        assert status.installed is True

    def test_build_status_ignores_manifest_for_other_registry(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        load_dir = tmp_path / "skills"
        load_dir.mkdir(parents=True)
        (load_dir / ".ainrf-registry").write_text("test-registry", encoding="utf-8")

        # Write manifest for a DIFFERENT registry
        other_manifest = {
            "registry_id": "other-registry",
            "skills": ["a", "b", "c"],
            "synced_at": "2024-01-01T00:00:00",
        }
        (load_dir / ".ainrf-registry-manifest.json").write_text(
            json.dumps(other_manifest), encoding="utf-8"
        )

        status = service._build_status()
        # Count should be 0 because manifest belongs to other registry
        assert status.installed_count == 0
        assert status.installed is True  # marker still matches

    def test_sync_all_rejects_file_as_source_path(
        self, service: SkillRegistrySyncService, tmp_path: Path
    ):
        service.git_workspace.mkdir(parents=True)
        # Create a file instead of directory at source_skills_path
        (service.git_workspace / "skills").write_text("not a directory")

        with pytest.raises(RuntimeError, match="is not a directory"):
            service._sync_all()

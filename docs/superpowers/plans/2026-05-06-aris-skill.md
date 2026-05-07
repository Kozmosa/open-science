# ARIS Skill Registry Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add default skill library integration for ARIS with install/update buttons in the UI, git workspace isolation, and dynamic skill.json generation from SKILL.md frontmatter.

**Architecture:** A configuration-driven registry framework (currently ARIS-only) with a dedicated git workspace (`aris-git-sync/`) that syncs one-way to the skills load directory. SKILL.md frontmatter is parsed to generate skill.json files during sync. Core skills are enabled by default; the rest are disabled.

**Tech Stack:** Python 3.13+, FastAPI, PyYAML, React/TypeScript, TanStack Query

---

## File Map

| File | Responsibility |
|------|---------------|
| `src/ainrf/skills/json_generator.py` | Parse SKILL.md YAML frontmatter and generate skill.json dict |
| `src/ainrf/skills/registry_models.py` | Dataclasses for SkillRegistryConfig and SkillRegistryStatus |
| `src/ainrf/skills/registry_sync.py` | Manage git workspace, detect updates, sync skills to load directory |
| `src/ainrf/api/schemas.py` | Pydantic request/response models for registry API |
| `src/ainrf/api/routes/skill_registries.py` | FastAPI routes: list, install, update, status |
| `src/ainrf/api/app.py` | Register the new router |
| `frontend/src/types/index.ts` | TypeScript types for registry API |
| `frontend/src/api/endpoints.ts` | API client functions for registry endpoints |
| `frontend/src/pages/SettingsPage.tsx` | Add install/update ARIS buttons |
| `tests/skills/test_json_generator.py` | Unit tests for frontmatter parsing and skill.json generation |
| `tests/skills/test_registry_sync.py` | Unit tests for sync service (with mocked git) |
| `tests/api/test_skill_registries.py` | Integration tests for API routes |

---

## Task 1: SkillJsonGenerator — Parse SKILL.md frontmatter

**Files:**
- Create: `src/ainrf/skills/json_generator.py`
- Test: `tests/skills/test_json_generator.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from pathlib import Path
from ainrf.skills.json_generator import generate_skill_json, parse_skill_md_frontmatter


class TestParseSkillMdFrontmatter:
    def test_parses_valid_frontmatter(self):
        content = """---
name: idea-discovery
description: "Workflow 1: Full idea discovery pipeline."
argument-hint: [research-direction]
allowed-tools: Bash(*), Read
---

# Workflow 1: Idea Discovery Pipeline

Research topic: $ARGUMENTS
"""
        result = parse_skill_md_frontmatter(content)
        assert result == {
            "name": "idea-discovery",
            "description": "Workflow 1: Full idea discovery pipeline.",
            "argument-hint": "[research-direction]",
            "allowed-tools": "Bash(*), Read",
        }

    def test_returns_empty_dict_when_no_frontmatter(self):
        content = "# Just a heading\n\nSome content."
        result = parse_skill_md_frontmatter(content)
        assert result == {}

    def test_returns_empty_dict_when_empty_frontmatter(self):
        content = "---\n---\n\n# Heading"
        result = parse_skill_md_frontmatter(content)
        assert result == {}


class TestGenerateSkillJson:
    def test_generates_skill_json_with_defaults(self):
        frontmatter = {
            "name": "idea-discovery",
            "description": "A description.",
        }
        result = generate_skill_json("idea-discovery", frontmatter, is_core=False)
        assert result == {
            "skill_id": "idea-discovery",
            "label": "idea-discovery",
            "description": "A description.",
            "version": "0.0.0",
            "author": "ARIS",
            "inject_mode": "disabled",
            "dependencies": [],
            "settings_fragment": {},
            "mcp_servers": [],
            "hooks": [],
            "allowed_agents": [],
        }

    def test_core_skill_uses_auto_inject_mode(self):
        frontmatter = {"name": "research-lit"}
        result = generate_skill_json("research-lit", frontmatter, is_core=True)
        assert result["inject_mode"] == "auto"

    def test_uses_directory_name_when_no_name_in_frontmatter(self):
        frontmatter = {"description": "Just a description."}
        result = generate_skill_json("my-skill", frontmatter, is_core=False)
        assert result["skill_id"] == "my-skill"
        assert result["label"] == "my-skill"

    def test_description_defaults_to_empty_string(self):
        frontmatter = {"name": "test"}
        result = generate_skill_json("test", frontmatter, is_core=False)
        assert result["description"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/skills/test_json_generator.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ainrf.skills.json_generator'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Generate skill.json from SKILL.md frontmatter."""

from __future__ import annotations

import re
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


_YAML_DELIM_RE = re.compile(r"^-{3,}\s*$", re.MULTILINE)


def parse_skill_md_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from SKILL.md content.

    Returns empty dict if no frontmatter found or yaml is not installed.
    """
    if yaml is None:
        return {}

    # Find the first --- delimiter
    match = _YAML_DELIM_RE.search(content)
    if not match:
        return {}

    start = match.end()
    # Find the closing --- after the opening one
    end_match = _YAML_DELIM_RE.search(content, start)
    if not end_match:
        return {}

    yaml_block = content[start:end_match.start()]
    if not yaml_block.strip():
        return {}

    try:
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except yaml.YAMLError:
        return {}


def generate_skill_json(
    skill_dir_name: str,
    frontmatter: dict[str, Any],
    is_core: bool = False,
) -> dict[str, Any]:
    """Generate a skill.json dict from parsed frontmatter.

    Args:
        skill_dir_name: The directory basename (used as fallback for skill_id/label).
        frontmatter: Parsed YAML frontmatter from SKILL.md.
        is_core: Whether this skill is in the core subset (enables inject_mode=auto).

    Returns:
        A dict matching the AINRF skill.json schema.
    """
    skill_id = frontmatter.get("name", skill_dir_name)
    label = frontmatter.get("name", skill_dir_name)
    description = frontmatter.get("description", "")
    inject_mode = "auto" if is_core else "disabled"

    return {
        "skill_id": skill_id,
        "label": label,
        "description": description,
        "version": "0.0.0",
        "author": "ARIS",
        "inject_mode": inject_mode,
        "dependencies": [],
        "settings_fragment": {},
        "mcp_servers": [],
        "hooks": [],
        "allowed_agents": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/skills/test_json_generator.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/skills/json_generator.py tests/skills/test_json_generator.py
git commit -m "feat: parse SKILL.md frontmatter and generate skill.json

Add SkillJsonGenerator that parses YAML frontmatter from ARIS-style
SKILL.md files and produces AINRF-compatible skill.json dicts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Registry Models — Dataclasses for Config and Status

**Files:**
- Create: `src/ainrf/skills/registry_models.py`

- [ ] **Step 1: Write the model file**

```python
"""Data models for skill registry configuration and status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SkillRegistryConfig:
    """Configuration for a recommended skill registry."""

    registry_id: str
    display_name: str
    git_url: str
    git_ref: str = "main"
    source_skills_path: str = "skills"
    core_skill_ids: list[str] = field(default_factory=list)
    install_mode: str = "copy"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "display_name": self.display_name,
            "git_url": self.git_url,
            "git_ref": self.git_ref,
            "source_skills_path": self.source_skills_path,
            "core_skill_ids": self.core_skill_ids,
            "install_mode": self.install_mode,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRegistryConfig:
        return cls(
            registry_id=data["registry_id"],
            display_name=data["display_name"],
            git_url=data["git_url"],
            git_ref=data.get("git_ref", "main"),
            source_skills_path=data.get("source_skills_path", "skills"),
            core_skill_ids=data.get("core_skill_ids", []),
            install_mode=data.get("install_mode", "copy"),
            enabled=data.get("enabled", True),
        )


# Pre-configured default registries (currently ARIS only)
DEFAULT_REGISTRIES: list[SkillRegistryConfig] = [
    SkillRegistryConfig(
        registry_id="aris",
        display_name="ARIS",
        git_url="https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git",
        git_ref="main",
        source_skills_path="skills",
        core_skill_ids=[
            "research-lit",
            "arxiv",
            "semantic-scholar",
            "deepxiv",
            "openalex",
            "exa-search",
            "gemini-search",
        ],
        install_mode="copy",
        enabled=True,
    )
]


@dataclass
class SkillRegistryStatus:
    """Runtime status of an installed skill registry."""

    registry_id: str
    installed: bool = False
    installed_count: int = 0
    last_sync_at: datetime | None = None
    remote_commit: str | None = None
    local_commit: str | None = None
    has_update: bool = False
    is_dirty: bool = False
    sync_in_progress: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "installed": self.installed,
            "installed_count": self.installed_count,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "remote_commit": self.remote_commit,
            "local_commit": self.local_commit,
            "has_update": self.has_update,
            "is_dirty": self.is_dirty,
            "sync_in_progress": self.sync_in_progress,
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/ainrf/skills/registry_models.py
git commit -m "feat: add skill registry config and status models

Add SkillRegistryConfig and SkillRegistryStatus dataclasses with
pre-configured ARIS registry. Core subset includes research-lit
and its related data-source skills.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: RegistrySyncService — Git Management and Skill Sync

**Files:**
- Create: `src/ainrf/skills/registry_sync.py`
- Test: `tests/skills/test_registry_sync.py`

- [ ] **Step 1: Write the failing test**

```python
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
    def service(self, tmp_path, registry):
        return SkillRegistrySyncService(
            registry=registry,
            workspace_dir=tmp_path,
            load_dir=tmp_path / "skills",
        )

    def test_git_workspace_path(self, service, tmp_path):
        assert service.git_workspace == tmp_path / "test-registry-git-sync"

    def test_find_skill_dirs_finds_direct_children(self, service, tmp_path):
        skills_root = tmp_path / "skills"
        (skills_root / "skill-a").mkdir(parents=True)
        (skills_root / "skill-a" / "SKILL.md").write_text("# Skill A")
        (skills_root / "skill-b").mkdir(parents=True)
        (skills_root / "skill-b" / "SKILL.md").write_text("# Skill B")
        (skills_root / "not-a-skill.txt").write_text("nope")

        dirs = list(service._find_skill_dirs(skills_root))
        assert sorted(dirs) == ["skill-a", "skill-b"]

    def test_find_skill_dirs_skips_dirs_without_skill_md(self, service, tmp_path):
        skills_root = tmp_path / "skills"
        (skills_root / "empty-dir").mkdir(parents=True)
        (skills_root / "valid").mkdir(parents=True)
        (skills_root / "valid" / "SKILL.md").write_text("# Valid")

        dirs = list(service._find_skill_dirs(skills_root))
        assert dirs == ["valid"]

    def test_sync_skill_generates_skill_json(self, service, tmp_path):
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

    def test_sync_skill_core_uses_auto(self, service, tmp_path):
        source = tmp_path / "source" / "core-skill"
        source.mkdir(parents=True)
        source.joinpath("SKILL.md").write_text(
            "---\nname: core-skill\n---\n\n# Core"
        )

        service._sync_skill_dir(source, tmp_path / "skills", is_core=True)

        data = json.loads((tmp_path / "skills" / "core-skill" / "skill.json").read_text())
        assert data["inject_mode"] == "auto"

    def test_sync_skill_copies_skill_md(self, service, tmp_path):
        source = tmp_path / "source" / "my-skill"
        source.mkdir(parents=True)
        source.joinpath("SKILL.md").write_text("# Content")

        service._sync_skill_dir(source, tmp_path / "skills", is_core=False)

        md_path = tmp_path / "skills" / "my-skill" / "SKILL.md"
        assert md_path.exists()
        assert md_path.read_text() == "# Content"

    def test_is_installed_checks_load_dir(self, service, tmp_path):
        assert not service.is_installed()

        (tmp_path / "skills" / "some-skill").mkdir(parents=True)
        (tmp_path / "skills" / "some-skill" / "SKILL.md").write_text("# X")

        assert service.is_installed()

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_check_update_detects_available_update(self, mock_run, service):
        # Mock git ls-remote
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
    def test_check_update_detects_dirty(self, mock_run, service):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\trefs/heads/main\n"),
            MagicMock(returncode=0, stdout="abc123\n"),
            MagicMock(returncode=0, stdout="M  skills/test/SKILL.md\n"),
        ]

        status = service.check_update()

        assert status.has_update is False
        assert status.is_dirty is True

    @patch("ainrf.skills.registry_sync.subprocess.run")
    def test_update_raises_when_dirty_and_not_forced(self, mock_run, service, tmp_path):
        # Make it look installed
        (tmp_path / "skills" / "x").mkdir(parents=True)
        (tmp_path / "skills" / "x" / "SKILL.md").write_text("# X")

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="remote\trefs/heads/main\n"),
            MagicMock(returncode=0, stdout="local\n"),
            MagicMock(returncode=0, stdout="M  file\n"),  # dirty
        ]

        with pytest.raises(DirtyWorktreeError):
            service.update(force=False)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/skills/test_registry_sync.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ainrf.skills.registry_sync'`

- [ ] **Step 3: Write the implementation**

```python
"""Skill registry sync service: manages git workspace and syncs skills to load directory."""

from __future__ import annotations

import json
import shutil
import subprocess
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

    def is_installed(self) -> bool:
        """Check if any skills from this registry are present in the load directory."""
        if not self.load_dir.exists():
            return False
        for subdir in self.load_dir.iterdir():
            if subdir.is_dir() and (subdir / "SKILL.md").exists():
                return True
        return False

    def install(self) -> SkillRegistryStatus:
        """First-time install: clone repo and sync all skills."""
        if self.git_workspace.exists():
            shutil.rmtree(self.git_workspace)

        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", self.registry.git_ref,
             self.registry.git_url, str(self.git_workspace)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr}")

        self._sync_all()
        return self._build_status()

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

    def update(self, force: bool = False) -> SkillRegistryStatus:
        """Pull latest and sync. Raises DirtyWorktreeError if dirty and not forced."""
        if not self.git_workspace.exists():
            raise RuntimeError("Registry not installed. Call install() first.")

        status = self.check_update()
        if status.is_dirty and not force:
            dirty_files = self._git_dirty_files()
            raise DirtyWorktreeError(dirty_files)

        if status.is_dirty and force:
            self._git_run(["reset", "--hard", "HEAD"])

        pull_result = self._git_run(["pull", "origin", self.registry.git_ref])
        if pull_result.returncode != 0:
            raise RuntimeError(f"git pull failed: {pull_result.stderr}")

        self._sync_all()
        return self._build_status()

    def _sync_all(self) -> None:
        """Sync all skills from git workspace to load directory."""
        source_root = self.git_workspace / self.registry.source_skills_path
        if not source_root.exists():
            raise RuntimeError(f"Source skills path not found: {source_root}")

        self.load_dir.mkdir(parents=True, exist_ok=True)
        core_set = set(self.registry.core_skill_ids)

        for skill_name in self._find_skill_dirs(source_root):
            source = source_root / skill_name
            is_core = skill_name in core_set
            self._sync_skill_dir(source, self.load_dir, is_core)

    def _find_skill_dirs(self, root: Path) -> list[str]:
        """Find all subdirectories under root that contain SKILL.md."""
        result: list[str] = []
        if not root.exists():
            return result
        for subdir in sorted(root.iterdir()):
            if subdir.is_dir() and (subdir / "SKILL.md").is_file():
                result.append(subdir.name)
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

    def _build_status(self) -> SkillRegistryStatus:
        """Build current status from filesystem."""
        installed_count = 0
        if self.load_dir.exists():
            installed_count = sum(
                1 for d in self.load_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            )

        return SkillRegistryStatus(
            registry_id=self.registry.registry_id,
            installed=self.is_installed(),
            installed_count=installed_count,
        )

    def _git_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.git_workspace), *args],
            capture_output=True,
            text=True,
        )

    def _git_ls_remote(self) -> str | None:
        result = subprocess.run(
            ["git", "ls-remote", self.registry.git_url, self.registry.git_ref],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        # Output format: "<commit>\t<ref>\n"
        return result.stdout.split()[0] if result.stdout.split() else None

    def _git_rev_parse(self) -> str | None:
        result = self._git_run(["rev-parse", "HEAD"])
        return result.stdout.strip() if result.returncode == 0 else None

    def _git_is_dirty(self) -> bool:
        result = self._git_run(["status", "--porcelain"])
        return result.returncode == 0 and bool(result.stdout.strip())

    def _git_dirty_files(self) -> list[str]:
        result = self._git_run(["status", "--porcelain"])
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/skills/test_registry_sync.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/skills/registry_sync.py tests/skills/test_registry_sync.py
git commit -m "feat: add SkillRegistrySyncService for git workspace management

Add service that clones ARIS repo, manages git workspace isolation,
detects updates, handles dirty worktree with force option, and syncs
skills one-way to the load directory with skill.json generation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: API Schemas — Request/Response Models

**Files:**
- Modify: `src/ainrf/api/schemas.py`

- [ ] **Step 1: Add registry schemas at the end of schemas.py**

```python
# --- Skill Registry Schemas ---

class SkillRegistryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    display_name: str
    git_url: str
    installed: bool = False
    installed_count: int = 0
    has_update: bool = False
    is_dirty: bool = False
    last_sync_at: str | None = None


class SkillRegistryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SkillRegistryItemResponse]


class SkillRegistryStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    installed: bool
    installed_count: int
    last_sync_at: str | None = None
    remote_commit: str | None = None
    local_commit: str | None = None
    has_update: bool
    is_dirty: bool
    sync_in_progress: bool


class SkillRegistryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class SkillRegistryInstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    installed_count: int
    skills: list[str]


class SkillRegistryUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    updated_count: int
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Verify no syntax errors**

```bash
uv run python -c "from ainrf.api.schemas import SkillRegistryItemResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/api/schemas.py
git commit -m "feat: add skill registry API schemas

Add Pydantic request/response models for skill registry endpoints:
list, install, update, status.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: API Routes — Skill Registry Endpoints

**Files:**
- Create: `src/ainrf/api/routes/skill_registries.py`
- Modify: `src/ainrf/api/app.py`
- Test: `tests/api/test_skill_registries.py`

- [ ] **Step 1: Write the route file**

```python
"""API routes for skill registry management."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    SkillRegistryInstallResponse,
    SkillRegistryListResponse,
    SkillRegistryItemResponse,
    SkillRegistryStatusResponse,
    SkillRegistryUpdateRequest,
    SkillRegistryUpdateResponse,
)
from ainrf.skills.registry_models import DEFAULT_REGISTRIES
from ainrf.skills.registry_sync import DirtyWorktreeError, SkillRegistrySyncService

router = APIRouter(prefix="/skill-registries", tags=["skill-registries"])


def _get_default_workspace_dir(request: Request) -> Path:
    """Get the default workspace directory from the app state."""
    scan_roots = getattr(request.app.state.skills_discovery_service, "_scan_roots", [])
    if scan_roots:
        return scan_roots[0]
    raise HTTPException(status_code=500, detail="No workspace directory configured")


@router.get("", response_model=SkillRegistryListResponse)
async def list_registries(request: Request) -> SkillRegistryListResponse:
    """List all configured skill registries with their installation status."""
    workspace_dir = _get_default_workspace_dir(request)
    load_dir = workspace_dir / "skills"

    items: list[SkillRegistryItemResponse] = []
    for config in DEFAULT_REGISTRIES:
        service = SkillRegistrySyncService(
            registry=config,
            workspace_dir=workspace_dir,
            load_dir=load_dir,
        )
        status = service.check_update()
        items.append(
            SkillRegistryItemResponse(
                registry_id=config.registry_id,
                display_name=config.display_name,
                git_url=config.git_url,
                installed=status.installed,
                installed_count=status.installed_count,
                has_update=status.has_update,
                is_dirty=status.is_dirty,
                last_sync_at=status.last_sync_at.isoformat() if status.last_sync_at else None,
            )
        )

    return SkillRegistryListResponse(items=items)


@router.get("/{registry_id}/status", response_model=SkillRegistryStatusResponse)
async def get_registry_status(request: Request, registry_id: str) -> SkillRegistryStatusResponse:
    """Get detailed status of a specific skill registry."""
    config = next((r for r in DEFAULT_REGISTRIES if r.registry_id == registry_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Registry '{registry_id}' not found")

    workspace_dir = _get_default_workspace_dir(request)
    service = SkillRegistrySyncService(
        registry=config,
        workspace_dir=workspace_dir,
        load_dir=workspace_dir / "skills",
    )
    status = service.check_update()

    return SkillRegistryStatusResponse(
        registry_id=status.registry_id,
        installed=status.installed,
        installed_count=status.installed_count,
        last_sync_at=status.last_sync_at.isoformat() if status.last_sync_at else None,
        remote_commit=status.remote_commit,
        local_commit=status.local_commit,
        has_update=status.has_update,
        is_dirty=status.is_dirty,
        sync_in_progress=status.sync_in_progress,
    )


@router.post("/{registry_id}/install", response_model=SkillRegistryInstallResponse)
async def install_registry(request: Request, registry_id: str) -> SkillRegistryInstallResponse:
    """Install a skill registry for the first time."""
    config = next((r for r in DEFAULT_REGISTRIES if r.registry_id == registry_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Registry '{registry_id}' not found")

    workspace_dir = _get_default_workspace_dir(request)
    load_dir = workspace_dir / "skills"
    service = SkillRegistrySyncService(
        registry=config,
        workspace_dir=workspace_dir,
        load_dir=load_dir,
    )

    if service.is_installed():
        raise HTTPException(status_code=400, detail=f"Registry '{registry_id}' is already installed")

    try:
        status = service.install()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkillRegistryInstallResponse(
        registry_id=config.registry_id,
        installed_count=status.installed_count,
        skills=[],
    )


@router.post("/{registry_id}/update", response_model=SkillRegistryUpdateResponse)
async def update_registry(
    request: Request,
    registry_id: str,
    payload: SkillRegistryUpdateRequest,
) -> SkillRegistryUpdateResponse:
    """Update an installed skill registry to the latest version."""
    config = next((r for r in DEFAULT_REGISTRIES if r.registry_id == registry_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Registry '{registry_id}' not found")

    workspace_dir = _get_default_workspace_dir(request)
    service = SkillRegistrySyncService(
        registry=config,
        workspace_dir=workspace_dir,
        load_dir=workspace_dir / "skills",
    )

    if not service.is_installed():
        raise HTTPException(status_code=400, detail=f"Registry '{registry_id}' is not installed")

    try:
        service.update(force=payload.force)
    except DirtyWorktreeError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Git worktree has uncommitted changes",
                "files": exc.files,
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkillRegistryUpdateResponse(
        registry_id=config.registry_id,
        updated_count=0,
    )
```

- [ ] **Step 2: Modify app.py to register the router**

Add import near the top:

```python
from ainrf.api.routes.skill_registries import router as skill_registries_router
```

Add to `ROUTERS` tuple (after skills_router):

```python
ROUTERS: tuple[APIRouter, ...] = (
    health_router,
    environments_router,
    files_router,
    projects_router,
    skills_router,
    skill_registries_router,  # ADD THIS LINE
    workspaces_router,
    terminal_router,
    tasks_router,
    code_router,
)
```

- [ ] **Step 3: Write integration test**

```python
from fastapi.testclient import TestClient


class TestSkillRegistryAPI:
    def test_list_registries(self, client: TestClient):
        response = client.get("/skill-registries")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        aris = next((r for r in data["items"] if r["registry_id"] == "aris"), None)
        assert aris is not None
        assert aris["display_name"] == "ARIS"

    def test_get_status_not_installed(self, client: TestClient):
        response = client.get("/skill-registries/aris/status")
        assert response.status_code == 200
        data = response.json()
        assert data["registry_id"] == "aris"
        assert data["installed"] is False

    def test_get_nonexistent_registry_returns_404(self, client: TestClient):
        response = client.get("/skill-registries/nonexistent/status")
        assert response.status_code == 404
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/test_skill_registries.py -v
```

Expected: Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/api/routes/skill_registries.py src/ainrf/api/app.py tests/api/test_skill_registries.py
git commit -m "feat: add skill registry API routes

Add /skill-registries endpoints for listing, installing, updating,
and checking status of configured skill registries. Integrates with
SkillRegistrySyncService.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Frontend Types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add registry types**

```typescript
export interface SkillRegistryItem {
  registry_id: string;
  display_name: string;
  git_url: string;
  installed: boolean;
  installed_count: number;
  has_update: boolean;
  is_dirty: boolean;
  last_sync_at: string | null;
}

export interface SkillRegistryListResponse {
  items: SkillRegistryItem[];
}

export interface SkillRegistryStatus {
  registry_id: string;
  installed: boolean;
  installed_count: number;
  last_sync_at: string | null;
  remote_commit: string | null;
  local_commit: string | null;
  has_update: boolean;
  is_dirty: boolean;
  sync_in_progress: boolean;
}

export interface SkillRegistryUpdateRequest {
  force: boolean;
}

export interface SkillRegistryInstallResponse {
  registry_id: string;
  installed_count: number;
  skills: string[];
}

export interface SkillRegistryUpdateResponse {
  registry_id: string;
  updated_count: number;
  added: string[];
  removed: string[];
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && node_modules/.bin/tsc -b --noEmit 2>&1 | head -20
```

Expected: No errors related to new types.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add skill registry TypeScript types

Add types for skill registry API: list, status, install, update.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Frontend API Client

**Files:**
- Modify: `frontend/src/api/endpoints.ts`

- [ ] **Step 1: Add imports**

```typescript
import type {
  // ... existing imports ...
  SkillRegistryListResponse,
  SkillRegistryStatus,
  SkillRegistryInstallResponse,
  SkillRegistryUpdateRequest,
  SkillRegistryUpdateResponse,
} from '../types';
```

- [ ] **Step 2: Add API functions**

```typescript
export const getSkillRegistries = (): Promise<SkillRegistryListResponse> =>
  USE_MOCK
    ? Promise.resolve({ items: [] })
    : api.get<SkillRegistryListResponse>('/skill-registries');

export const getSkillRegistryStatus = (registryId: string): Promise<SkillRegistryStatus> =>
  USE_MOCK
    ? Promise.resolve({
        registry_id: registryId,
        installed: false,
        installed_count: 0,
        last_sync_at: null,
        remote_commit: null,
        local_commit: null,
        has_update: false,
        is_dirty: false,
        sync_in_progress: false,
      })
    : api.get<SkillRegistryStatus>(`/skill-registries/${registryId}/status`);

export const installSkillRegistry = (registryId: string): Promise<SkillRegistryInstallResponse> =>
  USE_MOCK
    ? Promise.resolve({ registry_id: registryId, installed_count: 0, skills: [] })
    : api.post<SkillRegistryInstallResponse>(`/skill-registries/${registryId}/install`);

export const updateSkillRegistry = (
  registryId: string,
  payload: SkillRegistryUpdateRequest
): Promise<SkillRegistryUpdateResponse> =>
  USE_MOCK
    ? Promise.resolve({ registry_id: registryId, updated_count: 0, added: [], removed: [] })
    : api.post<SkillRegistryUpdateResponse>(`/skill-registries/${registryId}/update`, payload);
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && node_modules/.bin/tsc -b --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/endpoints.ts
git commit -m "feat: add skill registry API client functions

Add frontend API client for skill registry install/update/status.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Frontend UI — SettingsPage ARIS Buttons

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Add imports**

```typescript
import {
  getSkillRegistries,
  installSkillRegistry,
  updateSkillRegistry,
} from '../api/endpoints';
import type { SkillRegistryItem } from '../types';
```

- [ ] **Step 2: Add state, queries, and mutations**

Inside `SkillRepositorySection`, add after existing state:

```typescript
const [showDirtyConfirm, setShowDirtyConfirm] = useState(false);
const [pendingRegistryId, setPendingRegistryId] = useState<string | null>(null);

const registriesQuery = useQuery<SkillRegistryListResponse>({
  queryKey: ['skillRegistries'],
  queryFn: getSkillRegistries,
});

const installRegistryMutation = useMutation({
  mutationFn: installSkillRegistry,
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['skillRegistries'] });
    queryClient.invalidateQueries({ queryKey: ['skills'] });
  },
  onError: (err: Error) => {
    alert(err.message);
  },
});

const updateRegistryMutation = useMutation({
  mutationFn: ({ id, force }: { id: string; force: boolean }) =>
    updateSkillRegistry(id, { force }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['skillRegistries'] });
    queryClient.invalidateQueries({ queryKey: ['skills'] });
    setShowDirtyConfirm(false);
    setPendingRegistryId(null);
  },
  onError: (err: any) => {
    if (err.status === 409) {
      setShowDirtyConfirm(true);
    } else {
      alert(err.message || 'Update failed');
      setShowDirtyConfirm(false);
      setPendingRegistryId(null);
    }
  },
});
```

- [ ] **Step 3: Add registry buttons in header area**

Replace the button area:

```typescript
<div className="flex flex-wrap items-center justify-between gap-3">
  <Button onClick={() => setShowImport((current) => !current)}>
    {t('pages.settings.skillRepository.importSkill')}
  </Button>
  {registriesQuery.data?.items.map((registry: SkillRegistryItem) => (
    <div key={registry.registry_id} className="flex items-center gap-2">
      {!registry.installed ? (
        <Button
          onClick={() => installRegistryMutation.mutate(registry.registry_id)}
          disabled={installRegistryMutation.isPending}
        >
          {installRegistryMutation.isPending
            ? 'Installing...'
            : `Install ${registry.display_name}`}
        </Button>
      ) : registry.has_update ? (
        <Button
          onClick={() => {
            setPendingRegistryId(registry.registry_id);
            updateRegistryMutation.mutate({ id: registry.registry_id, force: false });
          }}
          disabled={updateRegistryMutation.isPending}
        >
          {updateRegistryMutation.isPending
            ? 'Updating...'
            : `Update ${registry.display_name}`}
        </Button>
      ) : (
        <Button disabled>
          {registry.display_name} Installed
        </Button>
      )}
    </div>
  ))}
</div>
```

- [ ] **Step 4: Add dirty confirmation dialog**

Add after import form section:

```typescript
{showDirtyConfirm && pendingRegistryId && (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
    <div className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-6 shadow-lg">
      <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">
        Update {pendingRegistryId.toUpperCase()}
      </h3>
      <p className="mb-4 text-sm text-[var(--text-secondary)]">
        The local git workspace has uncommitted changes. Continuing will discard
        these changes and pull the latest code from remote.
      </p>
      <div className="flex justify-end gap-3">
        <Button variant="secondary" onClick={() => setShowDirtyConfirm(false)}>
          Cancel
        </Button>
        <Button
          onClick={() => {
            if (pendingRegistryId) {
              updateRegistryMutation.mutate({ id: pendingRegistryId, force: true });
            }
          }}
        >
          Force Update
        </Button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 5: Verify TypeScript**

```bash
cd frontend && node_modules/.bin/tsc -b --noEmit 2>&1 | head -30
```

Expected: No type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add ARIS install/update buttons to skill repository UI

Add install/update buttons next to Import Skill in SettingsPage.
Shows Install ARIS when not installed, Update ARIS when update
available, and disabled Installed state otherwise. Includes dirty
worktree confirmation dialog for force updates.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Final Verification

- [ ] **Step 1: Run all backend tests**

```bash
uv run pytest tests/skills/test_json_generator.py tests/skills/test_registry_sync.py tests/api/test_skill_registries.py -v
```

Expected: All tests PASS.

- [ ] **Step 2: Run linting**

```bash
uv run ruff check src/ainrf/skills/json_generator.py src/ainrf/skills/registry_models.py src/ainrf/skills/registry_sync.py src/ainrf/api/routes/skill_registries.py
```

```bash
uv run ruff check --fix src/ainrf/skills/ src/ainrf/api/routes/skill_registries.py tests/
```

- [ ] **Step 3: Frontend type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 4: Format code**

```bash
uv run ruff format src/ainrf/skills/ src/ainrf/api/routes/skill_registries.py tests/
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "style: format code after ARIS skill registry implementation"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Plan Task |
|-------------|-----------|
| SkillRegistryConfig model | Task 2 |
| SkillRegistryStatus model | Task 2 |
| skill.json generation | Task 1 |
| Git workspace isolation | Task 3 |
| Install flow | Task 3, 5 |
| Update detection | Task 3, 5 |
| Dirty worktree handling | Task 3, 5, 8 |
| Backend API | Task 4, 5 |
| Frontend types | Task 6 |
| Frontend API client | Task 7 |
| Frontend UI | Task 8 |

**No gaps.**

### Placeholder Scan

- [x] No TBD/TODO in steps
- [x] All code is complete and runnable
- [x] No "similar to Task N" references

### Type Consistency

- [x] Models match across backend/frontend
- [x] API schemas align with service return types
- [x] React Query types match API client functions

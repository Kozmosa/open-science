from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.skills import SkillsDiscoveryService


def _make_app(tmp_path: Path, scan_roots: list[Path] | None = None) -> tuple:
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config)
    if scan_roots is not None:
        app.state.skills_discovery_service = SkillsDiscoveryService(scan_roots=scan_roots)
    return app


def make_client(tmp_path: Path, scan_roots: list[Path] | None = None) -> httpx.AsyncClient:
    app = _make_app(tmp_path, scan_roots=scan_roots)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": "secret-key"},
    )


def _create_skill_dir(parent: Path, skill_id: str, skill_json: dict, skill_md_content: str) -> Path:
    skill_dir = parent / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(json.dumps(skill_json), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    return skill_dir


git_available = shutil.which("git") is not None


@pytest.mark.anyio
async def test_get_skill_detail_success(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_id = "test-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Test Skill",
        "description": "A test skill",
        "version": "1.2.3",
        "author": "tester",
        "dependencies": ["dep-a", "dep-b"],
        "inject_mode": "prompt_only",
        "settings_fragment": {"foo": {"bar": 1}},
        "mcp_servers": ["server1"],
        "hooks": ["hook1"],
        "allowed_agents": ["claude-code", "custom-agent"],
    }
    skill_md = "# Test Skill\n\nThis is the SKILL.md content.\n"
    _create_skill_dir(skills_root, skill_id, skill_json, skill_md)

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.get(f"/skills/{skill_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == skill_id
    assert payload["label"] == "Test Skill"
    assert payload["description"] == "A test skill"
    assert payload["version"] == "1.2.3"
    assert payload["author"] == "tester"
    assert payload["dependencies"] == ["dep-a", "dep-b"]
    assert payload["inject_mode"] == "prompt_only"
    assert payload["settings_fragment"] == {"foo": {"bar": 1}}
    assert payload["mcp_servers"] == ["server1"]
    assert payload["hooks"] == ["hook1"]
    assert payload["allowed_agents"] == ["claude-code", "custom-agent"]
    assert payload["skill_md"] == skill_md
    assert payload["package"] is None


@pytest.mark.anyio
async def test_get_skill_detail_with_package(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_id = "packaged-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Packaged Skill",
        "description": "A skill with package",
        "version": "1.0.0",
        "author": "tester",
        "inject_mode": "auto",
        "package": "aris",
    }
    skill_md = "# Packaged Skill\n\nContent.\n"
    _create_skill_dir(skills_root, skill_id, skill_json, skill_md)

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.get(f"/skills/{skill_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["package"] == "aris"


@pytest.mark.anyio
async def test_get_skill_detail_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path, scan_roots=[]) as client:
        response = await client.get("/skills/nonexistent")

    assert response.status_code == 404
    assert response.json()["detail"] == "Skill not found"


@pytest.mark.anyio
async def test_preview_skill_settings_success(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_id = "preview-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Preview Skill",
        "settings_fragment": {"permissionMode": "restricted", "extra": {"nested": True}},
    }
    _create_skill_dir(skills_root, skill_id, skill_json, "# Preview\n")

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.get(f"/skills/{skill_id}/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == skill_id
    assert payload["label"] == "Preview Skill"
    assert payload["settings_fragment"] == {
        "permissionMode": "restricted",
        "extra": {"nested": True},
    }
    # merged_preview = deep_merge({"permissionMode": "bypassPermissions"}, settings_fragment)
    assert payload["merged_preview"]["permissionMode"] == "restricted"
    assert payload["merged_preview"]["extra"] == {"nested": True}


@pytest.mark.anyio
async def test_preview_skill_settings_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path, scan_roots=[]) as client:
        response = await client.get("/skills/nonexistent/preview")

    assert response.status_code == 404
    assert response.json()["detail"] == "Skill not found"


@pytest.mark.anyio
async def test_import_skill_local_success(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    source_dir = tmp_path / "source-skill"
    skill_id = "importable-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Importable Skill",
        "description": "A skill to import",
        "version": "1.0.0",
        "author": "tester",
        "inject_mode": "auto",
    }
    _create_skill_dir(source_dir, skill_id, skill_json, "# Importable\n")

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.post(
            "/skills/import",
            json={"source": "local", "local_path": str(source_dir / skill_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == skill_id
    assert payload["label"] == "Importable Skill"
    assert payload["path"].endswith(skill_id)
    assert (skills_root / skill_id / "skill.json").is_file()
    assert (skills_root / skill_id / "SKILL.md").is_file()


@pytest.mark.anyio
async def test_import_skill_local_not_found(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.post(
            "/skills/import",
            json={"source": "local", "local_path": "/nonexistent/path"},
        )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


@pytest.mark.anyio
async def test_import_skill_local_missing_manifest(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    bad_dir = tmp_path / "bad-skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("# Bad\n", encoding="utf-8")

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.post(
            "/skills/import",
            json={"source": "local", "local_path": str(bad_dir)},
        )

    assert response.status_code == 400
    assert "missing skill.json or SKILL.md" in response.json()["detail"]


@pytest.mark.anyio
async def test_import_skill_with_override(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    source_dir = tmp_path / "original-skill"
    original_id = "original"
    skill_json = {
        "skill_id": original_id,
        "label": "Original Skill",
        "version": "1.0.0",
        "author": "tester",
        "inject_mode": "auto",
    }
    _create_skill_dir(source_dir, original_id, skill_json, "# Original\n")

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.post(
            "/skills/import",
            json={
                "source": "local",
                "local_path": str(source_dir / original_id),
                "skill_id": "overridden",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == "overridden"
    assert payload["label"] == "Original Skill"
    assert payload["path"].endswith("overridden")

    # Directory should be renamed
    assert not (skills_root / original_id).exists()
    assert (skills_root / "overridden").is_dir()

    # skill.json should be updated
    imported_json = json.loads(
        (skills_root / "overridden" / "skill.json").read_text(encoding="utf-8")
    )
    assert imported_json["skill_id"] == "overridden"


@pytest.mark.anyio
@pytest.mark.skipif(not git_available, reason="git not installed")
async def test_import_skill_git_success(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    repo_dir = tmp_path / "source-repo"
    repo_dir.mkdir()
    skill_id = "git-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Git Skill",
        "version": "1.0.0",
        "author": "tester",
        "inject_mode": "auto",
    }
    (repo_dir / "skill.json").write_text(json.dumps(skill_json), encoding="utf-8")
    (repo_dir / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.post(
            "/skills/import",
            json={"source": "git", "url": f"file://{repo_dir}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == skill_id
    assert payload["label"] == "Git Skill"
    assert (skills_root / skill_id / "skill.json").is_file()
    assert (skills_root / skill_id / "SKILL.md").is_file()

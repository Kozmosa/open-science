from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    SkillDetailResponse,
    SkillImportRequest,
    SkillImportResponse,
    SkillItemResponse,
    SkillListResponse,
    SkillPreviewResponse,
)
from ainrf.skills import SkillsDiscoveryService
from ainrf.skills.merge import deep_merge_settings

router = APIRouter(prefix="/skills", tags=["skills"])


def _get_skills_discovery_service(request: Request) -> SkillsDiscoveryService:
    service = getattr(request.app.state, "skills_discovery_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="skills discovery service not initialized")
    return service


@router.get("", response_model=SkillListResponse)
async def list_skills(request: Request) -> SkillListResponse:
    service = _get_skills_discovery_service(request)
    skills = service.discover_full()
    return SkillListResponse(
        items=[
            SkillItemResponse(
                skill_id=s.skill_id,
                label=s.label,
                description=s.description,
                inject_mode=s.inject_mode.value,
                dependencies=list(s.dependencies),
            )
            for s in skills
        ]
    )


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill_detail(request: Request, skill_id: str) -> SkillDetailResponse:
    """Return full skill metadata plus SKILL.md content."""
    service = _get_skills_discovery_service(request)
    skills = service.discover_full()
    skill = next((s for s in skills if s.skill_id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill_md = None
    for root in service._scan_roots:
        md_path = root / skill_id / "SKILL.md"
        if md_path.is_file():
            skill_md = md_path.read_text(encoding="utf-8")
            break

    return SkillDetailResponse(
        skill_id=skill.skill_id,
        label=skill.label,
        description=skill.description,
        version=skill.version,
        author=skill.author,
        dependencies=list(skill.dependencies),
        inject_mode=skill.inject_mode.value,
        settings_fragment=dict(skill.settings_fragment),
        mcp_servers=list(skill.mcp_servers),
        hooks=list(skill.hooks),
        allowed_agents=list(skill.allowed_agents),
        skill_md=skill_md,
    )


@router.get("/{skill_id}/preview", response_model=SkillPreviewResponse)
async def preview_skill_settings(request: Request, skill_id: str) -> SkillPreviewResponse:
    """Return the skill's settings fragment and a merged preview."""
    service = _get_skills_discovery_service(request)
    skills = service.discover_full()
    skill = next((s for s in skills if s.skill_id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    merged_preview = deep_merge_settings(
        {"permissionMode": "bypassPermissions"},
        skill.settings_fragment,
    )

    return SkillPreviewResponse(
        skill_id=skill.skill_id,
        label=skill.label,
        settings_fragment=dict(skill.settings_fragment),
        merged_preview=merged_preview,
    )


@router.post("/import", response_model=SkillImportResponse)
async def import_skill(
    request: Request,
    payload: SkillImportRequest,
) -> SkillImportResponse:
    """Import a skill from git or local filesystem.

    Git: clones the repo, validates skill.json + SKILL.md exist.
    Local: copies the directory, validates skill.json + SKILL.md exist.

    If skill_id override is provided, renames the directory and updates skill.json.
    Imported skills are placed in the first scan root of the discovery service.
    """
    service = _get_skills_discovery_service(request)
    if not service._scan_roots:
        raise HTTPException(status_code=500, detail="No skill scan roots configured")
    dest_root = service._scan_roots[0]
    dest_root.mkdir(parents=True, exist_ok=True)

    # Validate payload
    if payload.source == "git":
        if not payload.url:
            raise HTTPException(status_code=400, detail="url is required when source=git")
        tmp_clone = tempfile.mkdtemp(prefix="skill-import-")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", payload.url, tmp_clone],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Git clone failed: {result.stderr}",
                )
            src_dir = Path(tmp_clone)
        except HTTPException:
            shutil.rmtree(tmp_clone, ignore_errors=True)
            raise
    else:  # local
        if not payload.local_path:
            raise HTTPException(status_code=400, detail="local_path is required when source=local")
        src_dir = Path(payload.local_path)
        if not src_dir.exists():
            raise HTTPException(status_code=400, detail="Local path does not exist")

    # Determine target skill_id
    manifest_path = src_dir / "skill.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            original_skill_id = manifest_data.get("skill_id")
            original_label = manifest_data.get("label", original_skill_id or "")
        except (json.JSONDecodeError, OSError):
            original_skill_id = None
            original_label = ""
    else:
        original_skill_id = None
        original_label = ""

    target_skill_id = payload.skill_id or original_skill_id or src_dir.name
    target_dir = dest_root / target_skill_id

    # Copy to destination
    try:
        if payload.source == "git":
            shutil.copytree(src_dir, target_dir, dirs_exist_ok=True)
            shutil.rmtree(tmp_clone, ignore_errors=True)
        else:
            shutil.copytree(src_dir, target_dir, dirs_exist_ok=True)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        if payload.source == "git":
            shutil.rmtree(tmp_clone, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to copy skill: {exc}")

    # Validate required files
    if not (target_dir / "skill.json").exists() or not (target_dir / "SKILL.md").exists():
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="Imported directory is missing skill.json or SKILL.md",
        )

    # Update skill.json if skill_id override was provided
    if payload.skill_id is not None:
        target_manifest = target_dir / "skill.json"
        try:
            data = json.loads(target_manifest.read_text(encoding="utf-8"))
            data["skill_id"] = payload.skill_id
            target_manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
            original_label = data.get("label", original_label)
        except (json.JSONDecodeError, OSError):
            pass

    return SkillImportResponse(
        skill_id=target_skill_id,
        label=original_label or target_skill_id,
        path=str(target_dir),
    )

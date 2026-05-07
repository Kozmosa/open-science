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
    skills_discovery = getattr(request.app.state, "skills_discovery_service", None)
    if skills_discovery is None:
        raise HTTPException(status_code=500, detail="Skills discovery service not initialized")
    scan_roots = getattr(skills_discovery, "_scan_roots", [])
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
        raise HTTPException(
            status_code=400, detail=f"Registry '{registry_id}' is already installed"
        )

    try:
        status, added, _removed = service.install()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkillRegistryInstallResponse(
        registry_id=config.registry_id,
        installed_count=status.installed_count,
        skills=added,
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
        _status, added, removed = service.update(force=payload.force)
    except DirtyWorktreeError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Git worktree has uncommitted changes: {', '.join(exc.files)}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkillRegistryUpdateResponse(
        registry_id=config.registry_id,
        updated_count=len(added) + len(removed),
        added=added,
        removed=removed,
    )

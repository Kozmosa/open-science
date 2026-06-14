"""API routes for skill registry management."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ainrf.auth.permissions import get_current_user, require_admin
from ainrf.api.schemas import (
    SkillRegistryCreateRequest,
    SkillRegistryInstallResponse,
    SkillRegistryItemResponse,
    SkillRegistryListResponse,
    SkillRegistryStatusResponse,
    SkillRegistryUpdateConfigRequest,
    SkillRegistryUpdateRequest,
    SkillRegistryUpdateResponse,
)
from ainrf.skills.registry_config_service import (
    SkillRegistryConfigService,
    SkillRegistryNotFoundError,
)
from ainrf.skills.registry_models import SkillRegistryConfig
from ainrf.skills.registry_sync import DirtyWorktreeError, SkillRegistrySyncService

logger = logging.getLogger(__name__)

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


def _get_registry_config_service(request: Request) -> SkillRegistryConfigService:
    service = getattr(request.app.state, "skill_registry_config_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Skill registry config service not initialized")
    return service


def _build_sync_service(request: Request, config: SkillRegistryConfig) -> SkillRegistrySyncService:
    workspace_dir = _get_default_workspace_dir(request)
    return SkillRegistrySyncService(
        registry=config,
        workspace_dir=workspace_dir,
        load_dir=workspace_dir / "skills",
    )


@router.get("", response_model=SkillRegistryListResponse)
async def list_registries(request: Request) -> SkillRegistryListResponse:
    """List all configured skill registries with their installation status."""
    from pathlib import Path as _Path

    config_service = _get_registry_config_service(request)
    workspace_dir = _get_default_workspace_dir(request)
    load_dir = workspace_dir / "skills"
    bundled_source = (
        _Path("/opt/ainrf/aris-repo") if _Path("/opt/ainrf/aris-repo").is_dir() else None
    )

    items: list[SkillRegistryItemResponse] = []
    for config in config_service.list_registries():
        service = SkillRegistrySyncService(
            registry=config,
            workspace_dir=workspace_dir,
            load_dir=load_dir,
        )
        status = service.check_update(bundled_source=bundled_source)
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
                bundled_skill_fingerprint=status.bundled_skill_fingerprint,
            )
        )

    return SkillRegistryListResponse(items=items)


@router.get("/{registry_id}/status", response_model=SkillRegistryStatusResponse)
async def get_registry_status(request: Request, registry_id: str) -> SkillRegistryStatusResponse:
    """Get detailed status of a specific skill registry."""
    from pathlib import Path as _Path

    config_service = _get_registry_config_service(request)
    try:
        config = config_service.get_registry(registry_id)
    except SkillRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    workspace_dir = _get_default_workspace_dir(request)
    bundled_source = (
        _Path("/opt/ainrf/aris-repo") if _Path("/opt/ainrf/aris-repo").is_dir() else None
    )
    service = SkillRegistrySyncService(
        registry=config,
        workspace_dir=workspace_dir,
        load_dir=workspace_dir / "skills",
    )
    status = service.check_update(bundled_source=bundled_source)

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
        bundled_skill_fingerprint=status.bundled_skill_fingerprint,
    )


@router.post("", response_model=SkillRegistryItemResponse)
async def create_registry(
    request: Request,
    payload: SkillRegistryCreateRequest,
) -> SkillRegistryItemResponse:
    """Add a new skill registry configuration.

    Requires admin privileges.
    """
    user = get_current_user(request)
    require_admin(user)

    config_service = _get_registry_config_service(request)
    config = SkillRegistryConfig(
        registry_id=payload.registry_id,
        display_name=payload.display_name,
        git_url=payload.git_url,
        git_ref=payload.git_ref,
        source_skills_path=payload.source_skills_path,
        core_skill_ids=payload.core_skill_ids,
        install_mode=payload.install_mode,
        enabled=payload.enabled,
    )
    try:
        config_service.add_registry(config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SkillRegistryItemResponse(
        registry_id=config.registry_id,
        display_name=config.display_name,
        git_url=config.git_url,
    )


@router.put("/{registry_id}", response_model=SkillRegistryItemResponse)
async def update_registry_config(
    request: Request,
    registry_id: str,
    payload: SkillRegistryUpdateConfigRequest,
) -> SkillRegistryItemResponse:
    """Update an existing skill registry configuration.

    Requires admin privileges. Built-in registries may be edited but not deleted.
    """
    user = get_current_user(request)
    require_admin(user)

    config_service = _get_registry_config_service(request)
    try:
        config = config_service.update_registry(
            registry_id=registry_id,
            display_name=payload.display_name,
            git_url=payload.git_url,
            git_ref=payload.git_ref,
            source_skills_path=payload.source_skills_path,
            core_skill_ids=payload.core_skill_ids,
            install_mode=payload.install_mode,
            enabled=payload.enabled,
        )
    except SkillRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SkillRegistryItemResponse(
        registry_id=config.registry_id,
        display_name=config.display_name,
        git_url=config.git_url,
    )


@router.delete("/{registry_id}")
async def delete_registry(request: Request, registry_id: str) -> dict[str, str]:
    """Delete a custom skill registry configuration.

    Requires admin privileges. Built-in registries cannot be deleted.
    """
    user = get_current_user(request)
    require_admin(user)

    config_service = _get_registry_config_service(request)
    try:
        config_service.delete_registry(registry_id)
    except SkillRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return {"registry_id": registry_id, "status": "deleted"}


@router.post("/{registry_id}/install", response_model=SkillRegistryInstallResponse)
async def install_registry(request: Request, registry_id: str) -> SkillRegistryInstallResponse:
    """Install a skill registry for the first time.

    Requires admin privileges.
    """
    user = get_current_user(request)
    require_admin(user)

    config_service = _get_registry_config_service(request)
    try:
        config = config_service.get_registry(registry_id)
    except SkillRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not config.enabled:
        raise HTTPException(status_code=400, detail=f"Registry '{registry_id}' is disabled")

    service = _build_sync_service(request, config)

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
    """Update an installed skill registry to the latest version.

    Requires admin privileges.
    """
    user = get_current_user(request)
    require_admin(user)

    config_service = _get_registry_config_service(request)
    try:
        config = config_service.get_registry(registry_id)
    except SkillRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not config.enabled:
        raise HTTPException(status_code=400, detail=f"Registry '{registry_id}' is disabled")

    service = _build_sync_service(request, config)

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

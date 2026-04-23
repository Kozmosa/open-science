from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import WorkspaceListResponse, WorkspaceResponse
from ainrf.workspaces import WorkspaceNotFoundError, WorkspaceRegistryService
from ainrf.workspaces.models import WorkspaceRecord

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _get_workspace_service(request: Request) -> WorkspaceRegistryService:
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="workspace service not initialized")
    return service


def _translate_workspace_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=404, detail="Workspace not found")
    return HTTPException(status_code=500, detail="Unexpected workspace error")


def _serialize_workspace(workspace: WorkspaceRecord) -> WorkspaceResponse:
    payload = asdict(workspace)
    payload["created_at"] = workspace.created_at
    payload["updated_at"] = workspace.updated_at
    return WorkspaceResponse.model_validate(payload)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(request: Request) -> WorkspaceListResponse:
    service = _get_workspace_service(request)
    try:
        items = [_serialize_workspace(workspace) for workspace in service.list_workspaces()]
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    return WorkspaceListResponse(items=items)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def read_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    service = _get_workspace_service(request)
    try:
        return _serialize_workspace(service.get_workspace(workspace_id))
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc

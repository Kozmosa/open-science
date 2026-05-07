from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ainrf.api.schemas import WorkspaceListResponse, WorkspaceResponse
from ainrf.workspaces import (
    WorkspaceDeletionError,
    WorkspaceDirectoryError,
    WorkspaceNotFoundError,
    WorkspaceRegistryService,
)
from ainrf.workspaces.models import WorkspaceRecord

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    project_id: str = Field(default="default", min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str = Field(min_length=1)


class WorkspaceUpdateRequest(BaseModel):
    project_id: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, min_length=1)
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str | None = Field(default=None, min_length=1)


def _get_workspace_service(request: Request) -> WorkspaceRegistryService:
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="workspace service not initialized")
    return service


def _translate_workspace_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(exc, WorkspaceDirectoryError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, WorkspaceDeletionError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected workspace error")


def _serialize_workspace(workspace: WorkspaceRecord) -> WorkspaceResponse:
    payload = asdict(workspace)
    payload["created_at"] = workspace.created_at
    payload["updated_at"] = workspace.updated_at
    return WorkspaceResponse.model_validate(payload)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    request: Request,
    project_id: str | None = None,
) -> WorkspaceListResponse:
    service = _get_workspace_service(request)
    try:
        items = [
            _serialize_workspace(workspace)
            for workspace in service.list_workspaces(project_id=project_id)
        ]
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    return WorkspaceListResponse(items=items)


@router.post("", response_model=WorkspaceResponse)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    request: Request,
) -> WorkspaceResponse:
    service = _get_workspace_service(request)
    try:
        workspace = service.create_workspace(
            project_id=payload.project_id,
            label=payload.label,
            description=payload.description,
            default_workdir=payload.default_workdir,
            workspace_prompt=payload.workspace_prompt,
        )
        return _serialize_workspace(workspace)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def read_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    service = _get_workspace_service(request)
    try:
        return _serialize_workspace(service.get_workspace(workspace_id))
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    request: Request,
) -> WorkspaceResponse:
    service = _get_workspace_service(request)
    try:
        workspace = service.update_workspace(
            workspace_id,
            project_id=payload.project_id,
            label=payload.label,
            description=payload.description,
            default_workdir=payload.default_workdir,
            workspace_prompt=payload.workspace_prompt,
        )
        return _serialize_workspace(workspace)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, request: Request) -> Response:
    service = _get_workspace_service(request)
    try:
        service.delete_workspace(workspace_id)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    return Response(status_code=204)

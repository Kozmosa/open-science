from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ainrf.api.deprecation import mark_deprecated
from ainrf.api.idempotency import require_idempotency_key
from ainrf.auth.permissions import check_resource_ownership, get_current_user, is_admin
from ainrf.api.schemas import WorkspaceListResponse, WorkspaceResponse
from ainrf.domain import DomainPermissionError, DomainService
from ainrf.domain_control import DomainModelMode, MaintenanceModeError
from ainrf.workspaces import (
    WorkspaceDeletionError,
    WorkspaceDirectoryError,
    WorkspaceNotFoundError,
    WorkspaceRegistryService,
)
from ainrf.workspaces.models import WorkspaceRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    project_id: str = Field(default="default", min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)


class WorkspaceUpdateRequest(BaseModel):
    project_id: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, min_length=1)
    description: str | None = None
    default_workdir: str | None = None
    workspace_prompt: str | None = Field(default=None, min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)


class _WorkspaceUpdateKwargs(TypedDict):
    """Typed sparse arguments forwarded to the durable Workspace service."""

    label: NotRequired[str | None]
    description: NotRequired[str | None]
    canonical_path: NotRequired[str]
    workspace_prompt: NotRequired[str | None]


def _get_workspace_service(request: Request) -> WorkspaceRegistryService:
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="workspace service not initialized")
    return service


def _v2_domain_service(request: Request) -> DomainService | None:
    service = getattr(request.app.state, "domain_service", None)
    config = getattr(request.app.state, "api_config", None)
    if config is None or config.domain_model_mode is not DomainModelMode.V2:
        return None
    if not isinstance(service, DomainService) or not service.v2_ready():
        raise HTTPException(status_code=503, detail="Domain v2 cutover is not ready")
    return service


def _mark_v2_compatibility_route(
    request: Request,
    response: Response,
    route_name: str,
    replacement: str,
) -> None:
    _ = request
    mark_deprecated(response, route=route_name, replacement=replacement)


def _workspace_prompt(workspace: dict[str, object]) -> str:
    value = workspace.get("workspace_context")
    if isinstance(value, str):
        return value
    raw_metadata = workspace.get("context_metadata_json")
    if isinstance(raw_metadata, str):
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, dict):
            prompt = metadata.get("workspace_prompt")
            if isinstance(prompt, str):
                return prompt
    return ""


def _serialize_domain_workspace(workspace: dict[str, object]) -> WorkspaceResponse:
    """Map v2 Workspace state to the legacy one-Project response shape."""

    return WorkspaceResponse.model_validate(
        {
            "workspace_id": str(workspace["workspace_id"]),
            # ``legacy_project_id`` is import-time compatibility data.  Do
            # not infer it from one of potentially many current links.
            "project_id": str(workspace.get("legacy_project_id") or ""),
            "label": str(workspace["label"]),
            "description": workspace.get("description"),
            "default_workdir": workspace.get("canonical_path"),
            "workspace_prompt": _workspace_prompt(workspace),
            "created_at": workspace.get("created_at"),
            "updated_at": workspace.get("updated_at"),
            "owner_user_id": workspace.get("owner_user_id"),
        }
    )


def _primary_environment_id(domain: DomainService, project_id: str, user: dict[str, object]) -> str:
    for link in domain.workspace_links(project_id, user):
        if link.get("status") == "active" and link.get("is_primary") is True:
            environment_id = link.get("environment_id")
            if isinstance(environment_id, str) and environment_id:
                return environment_id
    raise ValueError("Workspace creation requires an active Primary Workspace")


def _compatibility_workspace_path(
    domain: DomainService,
    environment_id: str,
    user: dict[str, object],
) -> str:
    environment = domain.environment(environment_id, user)
    raw_connection = environment.get("connection_json")
    try:
        connection = json.loads(raw_connection) if isinstance(raw_connection, str) else {}
    except json.JSONDecodeError:
        connection = {}
    default_workdir = connection.get("default_workdir") if isinstance(connection, dict) else None
    base = (
        Path(default_workdir) if isinstance(default_workdir, str) and default_workdir else Path("/")
    )
    return str(base / "openscience-workspaces" / f"compat-{uuid4().hex[:12]}")


def _translate_workspace_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(exc, WorkspaceDirectoryError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, WorkspaceDeletionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(exc, ValueError):
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
    response: Response,
    project_id: str | None = None,
) -> WorkspaceListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "workspaces.list", "/domain/capabilities")
        try:
            workspaces = domain.list_workspaces(user, project_id=project_id)
            return WorkspaceListResponse(
                items=[_serialize_domain_workspace(workspace) for workspace in workspaces]
            )
        except Exception as exc:
            raise _translate_workspace_error(exc) from exc
    service = _get_workspace_service(request)
    try:
        if is_admin(user):
            workspaces = service.list_workspaces(project_id=project_id)
        else:
            workspaces = service.list_workspaces(project_id=project_id, owner_user_id=user["id"])
        items = [_serialize_workspace(workspace) for workspace in workspaces]
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    return WorkspaceListResponse(items=items)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    request: Request,
    response: Response,
) -> WorkspaceResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "workspaces.update", "/domain/capabilities")
        try:
            current = domain.workspace(workspace_id, user)
            if current.get("status") != "active":
                raise LookupError(workspace_id)
            fields_set = payload.model_fields_set
            idempotency_key = require_idempotency_key(request, payload.idempotency_key)
            metadata_fields = fields_set.difference({"project_id", "idempotency_key"})
            if "project_id" in fields_set and metadata_fields:
                raise ValueError(
                    "Workspace attachment and metadata must be updated by separate requests"
                )
            if "project_id" not in fields_set and not metadata_fields:
                raise ValueError("Workspace update requires at least one mutable field")
            if "project_id" in fields_set and isinstance(payload.project_id, str):
                domain.attach_workspace(
                    payload.project_id,
                    workspace_id,
                    user,
                    idempotency_key=idempotency_key,
                )
                return _serialize_domain_workspace(current)
            kwargs: _WorkspaceUpdateKwargs = {}
            if "label" in fields_set:
                kwargs["label"] = payload.label
            if "description" in fields_set:
                kwargs["description"] = payload.description
            if "default_workdir" in fields_set and payload.default_workdir is not None:
                kwargs["canonical_path"] = payload.default_workdir
            if "workspace_prompt" in fields_set:
                kwargs["workspace_prompt"] = payload.workspace_prompt
            workspace = domain.update_workspace(
                workspace_id,
                user,
                idempotency_key=idempotency_key,
                **kwargs,
            )
            return _serialize_domain_workspace(workspace)
        except Exception as exc:
            raise _translate_workspace_error(exc) from exc
    service = _get_workspace_service(request)
    try:
        workspace = service.get_workspace(workspace_id)
        check_resource_ownership(user, workspace.owner_user_id)
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


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def read_workspace(
    workspace_id: str,
    request: Request,
    response: Response,
) -> WorkspaceResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "workspaces.read", "/domain/capabilities")
        try:
            workspace = domain.workspace(workspace_id, user)
            if workspace.get("status") != "active":
                raise LookupError(workspace_id)
            return _serialize_domain_workspace(workspace)
        except Exception as exc:
            raise _translate_workspace_error(exc) from exc
    service = _get_workspace_service(request)
    try:
        workspace = service.get_workspace(workspace_id)
        check_resource_ownership(user, workspace.owner_user_id)
        return _serialize_workspace(workspace)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc


@router.post("", response_model=WorkspaceResponse)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    request: Request,
    response: Response,
) -> WorkspaceResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "workspaces.create", "/domain/capabilities")
        try:
            environment_id = _primary_environment_id(domain, payload.project_id, user)
            canonical_path = payload.default_workdir or _compatibility_workspace_path(
                domain, environment_id, user
            )
            workspace = domain.create_workspace_and_attach(
                project_id=payload.project_id,
                user=user,
                environment_id=environment_id,
                canonical_path=canonical_path,
                label=payload.label,
                description=payload.description,
                workspace_prompt=payload.workspace_prompt,
                idempotency_key=require_idempotency_key(request, payload.idempotency_key),
            )
            return _serialize_domain_workspace(workspace)
        except Exception as exc:
            raise _translate_workspace_error(exc) from exc
    service = _get_workspace_service(request)
    try:
        workspace = service.create_workspace(
            project_id=payload.project_id,
            label=payload.label,
            description=payload.description,
            default_workdir=payload.default_workdir,
            workspace_prompt=payload.workspace_prompt,
            owner_user_id=user["id"],
        )
        return _serialize_workspace(workspace)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc


@router.post("/{workspace_id}/unregister", status_code=204)
async def unregister_workspace(workspace_id: str, request: Request) -> Response:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Workspace unregister is unavailable")
    try:
        domain.unregister_workspace(
            workspace_id,
            user,
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    response = Response(status_code=204)
    _mark_v2_compatibility_route(request, response, "workspaces.unregister", "/domain/capabilities")
    return response


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, request: Request) -> Response:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            # v2 DELETE is a compatibility alias: it unregisters only the
            # registry record and deliberately never removes tenant files.
            domain.unregister_workspace(
                workspace_id,
                user,
                idempotency_key=require_idempotency_key(request),
            )
        except Exception as exc:
            raise _translate_workspace_error(exc) from exc
        response = Response(status_code=204)
        _mark_v2_compatibility_route(
            request, response, "workspaces.delete", "/workspaces/{workspace_id}/unregister"
        )
        return response
    service = _get_workspace_service(request)
    try:
        workspace = service.get_workspace(workspace_id)
        check_resource_ownership(user, workspace.owner_user_id)
        service.delete_workspace(workspace_id)
    except Exception as exc:
        raise _translate_workspace_error(exc) from exc
    return Response(status_code=204)

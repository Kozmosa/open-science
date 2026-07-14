from __future__ import annotations

import json as json_mod
import logging
from dataclasses import asdict
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.api.deprecation import deprecation_headers, mark_deprecated
from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.schemas import (
    CollaboratorListResponse,
    CollaboratorRequest,
    CollaboratorResponse,
    ProjectCostSummaryResponse,
    ProjectCreateRequest,
    ProjectEnvironmentReferenceCreateRequest,
    ProjectEnvironmentReferenceListResponse,
    ProjectEnvironmentReferenceResponse,
    ProjectEnvironmentReferenceUpdateRequest,
    ProjectListResponse,
    ProjectMemberListResponse,
    ProjectMemberRequest,
    ProjectMemberResponse,
    ProjectOwnerTransferRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
    TaskListResponse,
)
from ainrf.api.routes.tasks import _task_to_response
from ainrf.auth.permissions import get_current_user, is_admin
from ainrf.domain import DomainPermissionError, DomainService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import DomainModelMode, MaintenanceModeError
from ainrf.environments import (
    EnvironmentNotFoundError,
    InMemoryEnvironmentService,
    ProjectEnvironmentReference,
    ProjectReferenceConflictError,
    ProjectReferenceNotFoundError,
)
from ainrf.projects import ProjectNotFoundError, ProjectRegistryService, TaskEdgeNotFoundError
from ainrf.projects.models import ProjectRecord, TaskEdgeRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])
task_edges_router = APIRouter(prefix="/task-edges", tags=["projects"])


def _get_project_service(request: Request) -> ProjectRegistryService:
    service = getattr(request.app.state, "project_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="project service not initialized")
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
    response: Response,
    *,
    route_name: str,
    replacement: str,
) -> None:
    mark_deprecated(response, route=route_name, replacement=replacement)


def _primary_link(
    domain: DomainService,
    project_id: str,
    user: dict[str, object],
) -> dict[str, object] | None:
    for link in domain.workspace_links(project_id, user):
        if link.get("status") == "active" and link.get("is_primary") is True:
            return link
    return None


def _serialize_domain_project(
    domain: DomainService,
    project: dict[str, object],
    user: dict[str, object],
) -> ProjectResponse:
    project_id = str(project["project_id"])
    primary = _primary_link(domain, project_id, user)
    return ProjectResponse.model_validate(
        {
            "project_id": project_id,
            "name": str(project["name"]),
            "description": project.get("description"),
            "default_workspace_id": primary.get("workspace_id") if primary else None,
            "default_environment_id": primary.get("environment_id") if primary else None,
            "created_at": str(project["created_at"]),
            "updated_at": str(project["updated_at"]),
            "owner_user_id": project.get("owner_user_id"),
        }
    )


def _active_domain_project(
    domain: DomainService,
    project_id: str,
    user: dict[str, object],
) -> dict[str, object]:
    project = domain.project(project_id, user)
    if project.get("status") != "active":
        raise DomainNotFoundError(project_id)
    return project


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _get_session_service(request: Request):
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="session service not initialized")
    return service


def _get_auth_service(request: Request):
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


def _check_project_visible(
    user: dict,
    project: ProjectRecord,
    auth_svc,
    *,
    require_owner: bool = False,
) -> None:
    """Verify the current user is authorized to access *project*.

    Admins bypass all checks. Owners have full access.
    Collaborators have read-only access unless *require_owner* is set
    (used for write operations such as update / delete / add-collaborator).
    """
    # Admin bypasses all checks.
    if is_admin(user):
        return

    # Owner has full access.
    if project.owner_user_id == user["id"]:
        return

    # Collaborator has read-only access (unless require_owner is set).
    if not require_owner and auth_svc is not None:
        collab_ids = auth_svc.get_user_project_ids(user["id"])
        if project.project_id in collab_ids:
            return

    raise HTTPException(status_code=403, detail="无权访问此项目")


def _get_visible_project_ids(
    user: dict,
    project_service: ProjectRegistryService,
    auth_svc,
) -> set[str]:
    """Return the set of *project_id* values visible to *user*."""
    if is_admin(user):
        return {p.project_id for p in project_service.list_projects()}

    owned = {p.project_id for p in project_service.list_projects(owner_user_id=user["id"])}
    if auth_svc is not None:
        collab = set(auth_svc.get_user_project_ids(user["id"]))
        owned |= collab
    return owned


def _get_agentic_researcher_service(request: Request):
    service = getattr(request.app.state, "agentic_researcher_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="AgenticResearcher service not initialized")
    return service


def _serialize_project(project: ProjectRecord) -> ProjectResponse:
    payload = dict(asdict(project))
    payload["created_at"] = project.created_at.isoformat()
    payload["updated_at"] = project.updated_at.isoformat()
    return ProjectResponse.model_validate(payload)


def _serialize_reference(
    reference: ProjectEnvironmentReference,
) -> ProjectEnvironmentReferenceResponse:
    payload = dict(asdict(reference))
    payload.pop("project_id", None)
    return ProjectEnvironmentReferenceResponse.model_validate(payload)


def _serialize_task_edge(edge: TaskEdgeRecord) -> TaskEdgeResponse:
    return TaskEdgeResponse(
        edge_id=edge.edge_id,
        project_id=edge.project_id,
        source_task_id=edge.source_task_id,
        target_task_id=edge.target_task_id,
        created_at=edge.created_at.isoformat(),
    )


def _serialize_domain_task_edge(edge: dict[str, object]) -> TaskEdgeResponse:
    return TaskEdgeResponse.model_validate(edge)


def _serialize_domain_collaborator(
    member: dict[str, object], auth_service: object
) -> CollaboratorResponse:
    user_id = str(member["user_id"])
    username = ""
    display_name = ""
    get_user = getattr(auth_service, "get_user", None)
    if callable(get_user):
        try:
            auth_user = get_user(user_id)
            username_value = getattr(auth_user, "username", "")
            display_name_value = getattr(auth_user, "display_name", "")
            username = username_value if isinstance(username_value, str) else ""
            display_name = display_name_value if isinstance(display_name_value, str) else ""
        except Exception:
            # Imported historical member IDs can outlive an auth record.  The
            # v2 relationship remains auditable without exposing a lookup error.
            pass
    return CollaboratorResponse(
        user_id=user_id,
        username=username,
        display_name=display_name,
        role=str(member["role"]),
        can_publish=bool(member.get("can_publish", False)),
    )


def _serialize_domain_member(
    member: dict[str, object], auth_service: object
) -> ProjectMemberResponse:
    collaborator = _serialize_domain_collaborator(member, auth_service)
    role = collaborator.role
    if role not in {"viewer", "editor"}:
        raise ValueError("Domain Project member has an invalid role")
    return ProjectMemberResponse(
        user_id=collaborator.user_id,
        username=collaborator.username,
        display_name=collaborator.display_name,
        role=cast(Literal["viewer", "editor"], role),
        can_publish=collaborator.can_publish,
    )


def _translate_project_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected project error",
    )


def _translate_task_edge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, TaskEdgeNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task edge not found")
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task edge not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected task edge error",
    )


def _translate_reference_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, EnvironmentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if isinstance(exc, ProjectReferenceNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project environment reference not found",
        )
    if isinstance(exc, ProjectReferenceConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Environment is already referenced by this project",
        )
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected project environment reference error",
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request, response: Response) -> ProjectListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.list",
            replacement="GET /projects",
        )
        try:
            return ProjectListResponse(
                items=[
                    _serialize_domain_project(domain, project, user)
                    for project in domain.list_projects(user)
                ]
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        visible_ids = _get_visible_project_ids(user, service, auth_svc)
        items = [
            _serialize_project(project)
            for project in service.list_projects()
            if project.project_id in visible_ids
        ]
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return ProjectListResponse(items=items)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    response: Response,
) -> ProjectResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.create",
            replacement="POST /projects",
        )
        try:
            project = domain.create_project(
                user,
                name=payload.name,
                description=payload.description,
                idempotency_key=require_idempotency_key(request, payload.idempotency_key),
            )
            return _serialize_domain_project(domain, project, user)
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    service = _get_project_service(request)
    try:
        project = service.create_project(
            name=payload.name,
            description=payload.description,
            owner_user_id=user["id"],
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return _serialize_project(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def read_project(
    project_id: str,
    request: Request,
    response: Response,
) -> ProjectResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.read",
            replacement=f"/projects/{project_id}/workspaces",
        )
        try:
            return _serialize_domain_project(
                domain,
                _active_domain_project(domain, project_id, user),
                user,
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        project = service.get_project(project_id)
        _check_project_visible(user, project, auth_svc)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return _serialize_project(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    request: Request,
    response: Response,
) -> ProjectResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.update",
            replacement=f"/projects/{project_id}/primary-workspace/{{workspace_id}}",
        )
        try:
            project = _active_domain_project(domain, project_id, user)
            domain.require_project_editor(project_id, user)
            changes = payload.model_dump(exclude_unset=True)
            idempotency_key = require_idempotency_key(request, payload.idempotency_key)
            changes.pop("idempotency_key", None)
            default_workspace_id = changes.get("default_workspace_id")
            if "default_workspace_id" in changes and (
                "name" in changes or "description" in changes
            ):
                raise ValueError(
                    "Primary Workspace and Project metadata must be updated by separate requests"
                )
            if "default_workspace_id" in changes:
                if not isinstance(default_workspace_id, str) or not default_workspace_id:
                    raise ValueError("A Primary Workspace cannot be cleared through this endpoint")
                domain.set_primary_workspace(
                    project_id,
                    default_workspace_id,
                    user,
                    idempotency_key=idempotency_key,
                )
            if "default_environment_id" in changes:
                primary = _primary_link(domain, project_id, user)
                if primary is None or changes["default_environment_id"] != primary.get(
                    "environment_id"
                ):
                    raise ValueError("default_environment_id is derived from the Primary Workspace")
            if "name" in changes or "description" in changes:
                if "description" in changes:
                    project = domain.update_project(
                        project_id,
                        user,
                        name=changes.get("name"),
                        description=changes["description"],
                        idempotency_key=idempotency_key,
                    )
                else:
                    project = domain.update_project(
                        project_id,
                        user,
                        name=changes.get("name"),
                        idempotency_key=idempotency_key,
                    )
            return _serialize_domain_project(domain, project, user)
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        project = service.get_project(project_id)
        _check_project_visible(user, project, auth_svc, require_owner=True)
        changes = payload.model_dump(exclude_unset=True)
        project = service.update_project(
            project_id,
            name=changes.get("name"),
            description=changes.get("description"),
            default_workspace_id=changes.get("default_workspace_id"),
            default_environment_id=changes.get("default_environment_id"),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return _serialize_project(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, request: Request, response: Response) -> None:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.delete",
            replacement=f"POST /projects/{project_id}/archive",
        )
        try:
            domain.require_project_owner(project_id, user)
            domain.archive_project(
                project_id,
                user,
                reason="deprecated project DELETE",
                idempotency_key=require_idempotency_key(request),
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
        return None
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        project = service.get_project(project_id)
        _check_project_visible(user, project, auth_svc, require_owner=True)
        service.delete_project(project_id)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.post("/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(project_id: str, request: Request) -> None:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project archive is unavailable")
    try:
        domain.require_project_owner(project_id, get_current_user(request))
        domain.archive_project(
            project_id,
            get_current_user(request),
            reason="user archived project",
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.post("/{project_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_project(project_id: str, request: Request) -> None:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project unarchive is unavailable")
    try:
        domain.require_project_owner(project_id, get_current_user(request))
        domain.unarchive_project(
            project_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.get("/{project_id}/workspaces")
async def list_project_workspace_links(project_id: str, request: Request) -> dict[str, object]:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project Workspace links are unavailable")
    try:
        return {"items": domain.workspace_links(project_id, get_current_user(request))}
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.post("/{project_id}/workspaces/{workspace_id}")
async def attach_project_workspace(
    project_id: str,
    workspace_id: str,
    request: Request,
) -> dict[str, object]:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project Workspace links are unavailable")
    try:
        domain.require_project_editor(project_id, get_current_user(request))
        return domain.attach_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.delete("/{project_id}/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_project_workspace(
    project_id: str,
    workspace_id: str,
    request: Request,
    allow_no_primary: bool = Query(False),
) -> None:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project Workspace links are unavailable")
    try:
        domain.require_project_editor(project_id, get_current_user(request))
        domain.detach_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
            allow_no_primary=allow_no_primary,
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.put("/{project_id}/primary-workspace/{workspace_id}")
async def set_primary_project_workspace(
    project_id: str,
    workspace_id: str,
    request: Request,
    previous_workspace_id: str | None = Query(None),
) -> dict[str, object]:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project Workspace links are unavailable")
    try:
        domain.require_project_editor(project_id, get_current_user(request))
        if previous_workspace_id is not None:
            return domain.replace_primary_workspace(
                project_id,
                previous_workspace_id,
                workspace_id,
                get_current_user(request),
                idempotency_key=require_idempotency_key(request),
            )
        return domain.set_primary_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get(
    "/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceListResponse,
)
async def list_project_environment_refs(
    project_id: str,
    request: Request,
    response: Response,
) -> ProjectEnvironmentReferenceListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.environment_refs.list",
            replacement=f"/projects/{project_id}/workspaces",
        )
        try:
            _active_domain_project(domain, project_id, user)
            primary = _primary_link(domain, project_id, user)
            if primary is None:
                return ProjectEnvironmentReferenceListResponse(items=[])
            environment_id = primary.get("environment_id")
            if not isinstance(environment_id, str):
                return ProjectEnvironmentReferenceListResponse(items=[])
            return ProjectEnvironmentReferenceListResponse(
                items=[
                    ProjectEnvironmentReferenceResponse(
                        environment_id=environment_id,
                        is_default=True,
                    )
                ]
            )
        except Exception as exc:
            raise _translate_reference_error(exc) from exc
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request))
    service = _get_environment_service(request)
    items = [
        _serialize_reference(reference) for reference in service.list_project_references(project_id)
    ]
    return ProjectEnvironmentReferenceListResponse(items=items)


@router.post(
    "/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_environment_ref(
    project_id: str,
    payload: ProjectEnvironmentReferenceCreateRequest,
    request: Request,
) -> ProjectEnvironmentReferenceResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            _active_domain_project(domain, project_id, user)
            domain.require_project_editor(project_id, user)
        except Exception as exc:
            raise _translate_reference_error(exc) from exc
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Project environment references are replaced by explicit Workspace links",
            headers=deprecation_headers(
                route="projects.environment_refs.create",
                replacement=f"POST /projects/{project_id}/workspaces/{{workspace_id}}",
            ),
        )
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request), require_owner=True)
    service = _get_environment_service(request)
    try:
        reference = service.create_project_reference(
            project_id=project_id,
            environment_id=payload.environment_id,
            is_default=payload.is_default,
            override_workdir=payload.override_workdir,
            override_env_name=payload.override_env_name,
            override_env_manager=payload.override_env_manager,
            override_runtime_notes=payload.override_runtime_notes,
        )
    except Exception as exc:  # pragma: no cover - defensive translation
        raise _translate_reference_error(exc) from exc
    return _serialize_reference(reference)


@router.patch(
    "/{project_id}/environment-refs/{environment_id}",
    response_model=ProjectEnvironmentReferenceResponse,
)
async def update_project_environment_ref(
    project_id: str,
    environment_id: str,
    payload: ProjectEnvironmentReferenceUpdateRequest,
    request: Request,
) -> ProjectEnvironmentReferenceResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            _active_domain_project(domain, project_id, user)
            domain.require_project_editor(project_id, user)
        except Exception as exc:
            raise _translate_reference_error(exc) from exc
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Project environment references are replaced by explicit Workspace links",
            headers=deprecation_headers(
                route="projects.environment_refs.update",
                replacement=f"PUT /projects/{project_id}/primary-workspace/{{workspace_id}}",
            ),
        )
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request), require_owner=True)
    service = _get_environment_service(request)
    try:
        current = service.get_project_reference(project_id, environment_id)
        changes = payload.model_dump(exclude_unset=True)
        reference = service.upsert_project_reference(
            project_id=project_id,
            environment_id=environment_id,
            is_default=changes.get("is_default", current.is_default),
            override_workdir=changes.get("override_workdir", current.override_workdir),
            override_env_name=changes.get("override_env_name", current.override_env_name),
            override_env_manager=changes.get("override_env_manager", current.override_env_manager),
            override_runtime_notes=changes.get(
                "override_runtime_notes",
                current.override_runtime_notes,
            ),
        )
    except Exception as exc:
        raise _translate_reference_error(exc) from exc
    return _serialize_reference(reference)


@router.delete(
    "/{project_id}/environment-refs/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_environment_ref(
    project_id: str,
    environment_id: str,
    request: Request,
) -> None:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            _active_domain_project(domain, project_id, user)
            domain.require_project_editor(project_id, user)
        except Exception as exc:
            raise _translate_reference_error(exc) from exc
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Project environment references are replaced by explicit Workspace links",
            headers=deprecation_headers(
                route="projects.environment_refs.delete",
                replacement=f"DELETE /projects/{project_id}/workspaces/{{workspace_id}}",
            ),
        )
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request), require_owner=True)
    service = _get_environment_service(request)
    try:
        service.delete_project_reference(project_id, environment_id)
    except Exception as exc:
        raise _translate_reference_error(exc) from exc
    return None


@router.get("/{project_id}/cost-summary", response_model=ProjectCostSummaryResponse)
async def get_project_cost_summary(
    project_id: str,
    request: Request,
    response: Response,
) -> ProjectCostSummaryResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            _active_domain_project(domain, project_id, user)
        except Exception as exc:
            raise _translate_project_error(exc) from exc
        projection = getattr(request.app.state, "project_cost_projection_service", None)
        summary = getattr(projection, "project_cost_summary", None)
        if not callable(summary):
            raise HTTPException(status_code=503, detail="Project cost projection is unavailable")
        _mark_v2_compatibility_route(
            response,
            route_name="projects.cost_summary",
            replacement="Attempt cost projection",
        )
        try:
            return ProjectCostSummaryResponse.model_validate(summary(project_id, user))
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request))
    session_service = _get_session_service(request)
    try:
        sessions = session_service.list_sessions(project_id=project_id)
    except Exception as exc:
        raise _translate_project_error(exc) from exc

    total_cost = 0.0
    total_tokens = 0
    by_model: dict[str, dict] = {}

    session_ids = [s.id for s in sessions]
    attempts_by_session = session_service.list_attempts_for_sessions(session_ids)
    for s in sessions:
        total_cost += s.total_cost_usd
        for a in attempts_by_session.get(s.id, []):
            if a.token_usage_json:
                try:
                    tu = json_mod.loads(a.token_usage_json)
                except Exception:
                    continue
                total_t = tu.get("total", {})
                total_tokens += total_t.get("input_tokens", 0)
                total_tokens += total_t.get("output_tokens", 0)
                total_tokens += total_t.get("cache_creation_input_tokens", 0)
                total_tokens += total_t.get("cache_read_input_tokens", 0)
                for model, usage in tu.get("by_model", {}).items():
                    if model not in by_model:
                        by_model[model] = {"cost_usd": 0.0, "tokens": 0}
                    by_model[model]["cost_usd"] += usage.get("cost_usd", 0)
                    by_model[model]["tokens"] += usage.get("input_tokens", 0)
                    by_model[model]["tokens"] += usage.get("output_tokens", 0)

    return ProjectCostSummaryResponse.model_validate(
        {
            "project_id": project_id,
            "total_cost_usd": round(total_cost, 2),
            "total_tokens": total_tokens,
            "session_count": len(sessions),
            "by_model": by_model,
        }
    )


@router.get(
    "/{project_id}/task-edges",
    response_model=TaskEdgeListResponse,
)
async def list_project_task_edges(
    project_id: str,
    request: Request,
    response: Response,
) -> TaskEdgeListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.task_edges.list",
            replacement=f"GET /projects/{project_id}/tasks",
        )
        try:
            return TaskEdgeListResponse(
                items=[
                    _serialize_domain_task_edge(edge)
                    for edge in domain.list_task_relationships(project_id, user)
                ]
            )
        except Exception as exc:
            raise _translate_task_edge_error(exc) from exc
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        project = service.get_project(project_id)
        _check_project_visible(user, project, auth_svc)
        edges = service.list_task_edges(project_id)
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc
    return TaskEdgeListResponse(items=[_serialize_task_edge(edge) for edge in edges])


@router.post(
    "/{project_id}/task-edges",
    response_model=TaskEdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_task_edge(
    project_id: str,
    payload: TaskEdgeCreateRequest,
    request: Request,
    response: Response,
) -> TaskEdgeResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.task_edges.create",
            replacement="Task relationship API",
        )
        try:
            domain.require_project_editor(project_id, user)
            return _serialize_domain_task_edge(
                domain.create_task_relationship(
                    project_id,
                    user,
                    source_task_id=payload.source_task_id,
                    target_task_id=payload.target_task_id,
                    idempotency_key=require_idempotency_key(request, payload.idempotency_key),
                )
            )
        except Exception as exc:
            raise _translate_task_edge_error(exc) from exc
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        project = service.get_project(project_id)
        _check_project_visible(user, project, auth_svc)
        edge = service.create_task_edge(
            project_id,
            source_task_id=payload.source_task_id,
            target_task_id=payload.target_task_id,
        )
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc
    return _serialize_task_edge(edge)


@task_edges_router.delete("/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request, response: Response) -> None:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="task_edges.delete",
            replacement="Task relationship API",
        )
        try:
            domain.delete_task_relationship(
                edge_id,
                user,
                idempotency_key=require_idempotency_key(request),
            )
        except Exception as exc:
            raise _translate_task_edge_error(exc) from exc
        return None
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        edge = service.get_task_edge(edge_id)
        project = service.get_project(edge.project_id)
        _check_project_visible(user, project, auth_svc)
        service.delete_task_edge(edge_id)
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc


@router.get("/{project_id}/tasks", response_model=TaskListResponse)
async def list_project_tasks(
    project_id: str,
    request: Request,
    include_archived: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    sort: str = Query("updated"),
) -> TaskListResponse:
    """List tasks belonging to a specific project.

    Users who can view the project see all tasks inside it (not just
    their own), matching the "project as a collaboration unit" model.
    """
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            _active_domain_project(domain, project_id, user)
        except Exception as exc:
            raise _translate_project_error(exc) from exc
        projection = getattr(request.app.state, "project_task_projection_service", None)
        list_project = getattr(projection, "list_project_tasks", None)
        if not callable(list_project):
            raise HTTPException(status_code=503, detail="Project Task projection is unavailable")
        try:
            return TaskListResponse.model_validate(
                list_project(
                    project_id,
                    user,
                    include_archived=include_archived,
                    limit=limit,
                    sort=sort,
                )
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    service = _get_agentic_researcher_service(request)
    auth_svc = _get_auth_service(request)
    proj_svc = _get_project_service(request)

    try:
        project = proj_svc.get_project(project_id)
    except Exception as exc:
        raise _translate_project_error(exc) from exc

    _check_project_visible(user, project, auth_svc)
    # Visible users see every task in the project (collaboration model).
    tasks = service.list_tasks(
        project_id=project_id,
        user_id=None,
        include_archived=include_archived,
        limit=limit,
        sort=sort,
    )

    return TaskListResponse(
        items=[_task_to_response(task, service) for task in tasks],
        total=len(tasks),
    )


@router.get("/{project_id}/members", response_model=ProjectMemberListResponse)
async def list_project_members(
    project_id: str,
    request: Request,
) -> ProjectMemberListResponse:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project member API is unavailable")
    try:
        auth_service = _get_auth_service(request)
        return ProjectMemberListResponse(
            items=[
                _serialize_domain_member(member, auth_service)
                for member in domain.list_project_members(project_id, get_current_user(request))
            ]
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.put(
    "/{project_id}/members/{member_user_id}",
    response_model=ProjectMemberResponse,
)
async def upsert_project_member(
    project_id: str,
    member_user_id: str,
    payload: ProjectMemberRequest,
    request: Request,
) -> ProjectMemberResponse:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project member API is unavailable")
    user = get_current_user(request)
    try:
        domain.require_project_owner(project_id, user)
        domain.add_member(
            project_id,
            member_user_id,
            payload.role,
            payload.can_publish,
            user,
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
        members = domain.list_project_members(project_id, user)
        member = next(
            (item for item in members if item.get("user_id") == member_user_id),
            None,
        )
        if member is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("Updated Project member could not be read")
        return _serialize_domain_member(member, _get_auth_service(request))
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.delete("/{project_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_member(
    project_id: str,
    member_user_id: str,
    request: Request,
) -> None:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project member API is unavailable")
    try:
        domain.require_project_owner(project_id, get_current_user(request))
        domain.remove_member(
            project_id,
            member_user_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.post(
    "/{project_id}/owner-transfer",
    response_model=ProjectResponse,
)
async def transfer_project_owner(
    project_id: str,
    payload: ProjectOwnerTransferRequest,
    request: Request,
) -> ProjectResponse:
    domain = _v2_domain_service(request)
    if domain is None:
        raise HTTPException(status_code=404, detail="Project owner transfer is unavailable")
    user = get_current_user(request)
    try:
        domain.require_project_owner(project_id, user)
        domain.transfer_project_owner(
            project_id,
            payload.new_owner_user_id,
            user,
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
        # The caller is deliberately retained as an editor during transfer,
        # so it can read the resulting Project projection.
        return _serialize_domain_project(domain, domain.project(project_id, user), user)
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get("/{project_id}/collaborators", response_model=CollaboratorListResponse)
async def list_collaborators(
    project_id: str,
    request: Request,
    response: Response,
) -> CollaboratorListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.collaborators.list",
            replacement="Project member API",
        )
        try:
            auth_service = _get_auth_service(request)
            return CollaboratorListResponse(
                items=[
                    _serialize_domain_collaborator(member, auth_service)
                    for member in domain.list_project_members(project_id, user)
                ]
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request))
    auth_svc = _get_auth_service(request)
    collabs = auth_svc.list_collaborators(project_id)
    return CollaboratorListResponse.model_validate({"items": collabs})


@router.put(
    "/{project_id}/collaborators",
    response_model=CollaboratorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_collaborator(
    project_id: str,
    payload: CollaboratorRequest,
    request: Request,
    response: Response,
) -> CollaboratorResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            response,
            route_name="projects.collaborators.add",
            replacement="Project member API",
        )
        role = payload.role if payload.role in {"viewer", "editor"} else "viewer"
        try:
            domain.require_project_owner(project_id, user)
            domain.add_member(
                project_id,
                payload.user_id,
                role,
                payload.can_publish,
                user,
                idempotency_key=require_idempotency_key(request, payload.idempotency_key),
            )
            return _serialize_domain_collaborator(
                {
                    "user_id": payload.user_id,
                    "role": role,
                    "can_publish": payload.can_publish,
                },
                _get_auth_service(request),
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request), require_owner=True)
    auth_svc = _get_auth_service(request)
    auth_svc.add_collaborator(
        project_id=project_id, user_id=payload.user_id, role=payload.role, added_by=user["id"]
    )
    return CollaboratorResponse.model_validate(
        {"user_id": payload.user_id, "username": "", "display_name": "", "role": payload.role}
    )


@router.delete("/{project_id}/collaborators/{user_id}", status_code=204)
async def remove_collaborator(project_id: str, user_id: str, request: Request) -> Response:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        try:
            domain.require_project_owner(project_id, user)
            domain.remove_member(
                project_id,
                user_id,
                user,
                idempotency_key=require_idempotency_key(request),
            )
        except Exception as exc:
            raise _translate_project_error(exc) from exc
        response = Response(status_code=204)
        _mark_v2_compatibility_route(
            response,
            route_name="projects.collaborators.remove",
            replacement="Project member API",
        )
        return response
    proj = _get_project_service(request).get_project(project_id)
    _check_project_visible(user, proj, _get_auth_service(request), require_owner=True)
    auth_svc = _get_auth_service(request)
    auth_svc.remove_collaborator(project_id, user_id)
    return Response(status_code=204)

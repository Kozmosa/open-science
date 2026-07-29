from __future__ import annotations
import logging
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
from ainrf.auth.permissions import get_current_user
from ainrf.domain import DomainPermissionError, DomainService, TaskApplicationService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import MaintenanceModeError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])
task_edges_router = APIRouter(prefix="/task-edges", tags=["projects"])


def _domain_service(request: Request) -> DomainService:
    service = getattr(request.app.state, "domain_service", None)
    if not isinstance(service, DomainService) or not service.v2_ready():
        raise HTTPException(status_code=503, detail="Domain cutover is not ready")
    return service


def _task_application_service(request: Request) -> TaskApplicationService:
    service = getattr(request.app.state, "task_application_service", None)
    if not isinstance(service, TaskApplicationService):
        raise HTTPException(status_code=503, detail="Task application module is unavailable")
    return service


def _mark_v2_compatibility_route(response: Response, *, route_name: str, replacement: str) -> None:
    mark_deprecated(response, route=route_name, replacement=replacement)


def _primary_link(
    domain: DomainService, project_id: str, user: dict[str, object]
) -> dict[str, object] | None:
    for link in domain.workspace_links(project_id, user):
        if link.get("status") == "active" and link.get("is_primary") is True:
            return link
    return None


def _serialize_domain_project(
    domain: DomainService, project: dict[str, object], user: dict[str, object]
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
    domain: DomainService, project_id: str, user: dict[str, object]
) -> dict[str, object]:
    project = domain.project(project_id, user)
    if project.get("status") != "active":
        raise DomainNotFoundError(project_id)
    return project


def _get_auth_service(request: Request):
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


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
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected project error"
    )


def _translate_task_edge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task edge not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected task edge error"
    )


def _translate_reference_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
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
    domain = _domain_service(request)
    _mark_v2_compatibility_route(response, route_name="projects.list", replacement="GET /projects")
    try:
        return ProjectListResponse(
            items=[
                _serialize_domain_project(domain, project, user)
                for project in domain.list_projects(user)
            ]
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest, request: Request, response: Response
) -> ProjectResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.create", replacement="POST /projects"
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


@router.get("/{project_id}", response_model=ProjectResponse)
async def read_project(project_id: str, request: Request, response: Response) -> ProjectResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.read", replacement=f"/projects/{project_id}/workspaces"
    )
    try:
        return _serialize_domain_project(
            domain, _active_domain_project(domain, project_id, user), user
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, payload: ProjectUpdateRequest, request: Request, response: Response
) -> ProjectResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
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
        if "default_workspace_id" in changes and ("name" in changes or "description" in changes):
            raise ValueError("Primary Workspace and Project metadata must be updated separately")
        if "default_workspace_id" in changes:
            if not isinstance(default_workspace_id, str) or not default_workspace_id:
                raise ValueError("A Primary Workspace cannot be cleared through this endpoint")
            domain.set_primary_workspace(
                project_id, default_workspace_id, user, idempotency_key=idempotency_key
            )
        if "default_environment_id" in changes:
            primary = _primary_link(domain, project_id, user)
            if primary is None or changes["default_environment_id"] != primary.get(
                "environment_id"
            ):
                raise ValueError("default_environment_id is derived from the Primary Workspace")
        if "name" in changes or "description" in changes:
            update_kwargs = {"name": changes.get("name")}
            if "description" in changes:
                update_kwargs["description"] = changes["description"]
            project = domain.update_project(
                project_id, user, idempotency_key=idempotency_key, **update_kwargs
            )
        return _serialize_domain_project(domain, project, user)
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, request: Request, response: Response) -> None:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.delete", replacement=f"POST /projects/{project_id}/archive"
    )
    try:
        domain.require_project_owner(project_id, user)
        _task_application_service(request).archive_project(
            project_id,
            user,
            reason="deprecated project DELETE",
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.post("/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(project_id: str, request: Request) -> None:
    domain = _domain_service(request)
    try:
        domain.require_project_owner(project_id, get_current_user(request))
        _task_application_service(request).archive_project(
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
    domain = _domain_service(request)
    try:
        domain.require_project_owner(project_id, get_current_user(request))
        _task_application_service(request).unarchive_project(
            project_id, get_current_user(request), idempotency_key=require_idempotency_key(request)
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.get("/{project_id}/workspaces")
async def list_project_workspace_links(project_id: str, request: Request) -> dict[str, object]:
    domain = _domain_service(request)
    try:
        return {"items": domain.workspace_links(project_id, get_current_user(request))}
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.post("/{project_id}/workspaces/{workspace_id}")
async def attach_project_workspace(
    project_id: str, workspace_id: str, request: Request
) -> dict[str, object]:
    domain = _domain_service(request)
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
    project_id: str, workspace_id: str, request: Request, allow_no_primary: bool = Query(False)
) -> None:
    domain = _domain_service(request)
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
    domain = _domain_service(request)
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
    "/{project_id}/environment-refs", response_model=ProjectEnvironmentReferenceListResponse
)
async def list_project_environment_refs(
    project_id: str, request: Request, response: Response
) -> ProjectEnvironmentReferenceListResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
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
                ProjectEnvironmentReferenceResponse(environment_id=environment_id, is_default=True)
            ]
        )
    except Exception as exc:
        raise _translate_reference_error(exc) from exc


@router.post(
    "/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_environment_ref(
    project_id: str, payload: ProjectEnvironmentReferenceCreateRequest, request: Request
) -> ProjectEnvironmentReferenceResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
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
    domain = _domain_service(request)
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


@router.delete(
    "/{project_id}/environment-refs/{environment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_project_environment_ref(
    project_id: str, environment_id: str, request: Request
) -> None:
    user = get_current_user(request)
    domain = _domain_service(request)
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


@router.get("/{project_id}/cost-summary", response_model=ProjectCostSummaryResponse)
async def get_project_cost_summary(
    project_id: str, request: Request, response: Response
) -> ProjectCostSummaryResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    try:
        _active_domain_project(domain, project_id, user)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    projection = getattr(request.app.state, "project_cost_projection_service", None)
    summary = getattr(projection, "project_cost_summary", None)
    if not callable(summary):
        raise HTTPException(status_code=503, detail="Project cost projection is unavailable")
    _mark_v2_compatibility_route(
        response, route_name="projects.cost_summary", replacement="Attempt cost projection"
    )
    try:
        return ProjectCostSummaryResponse.model_validate(summary(project_id, user))
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get("/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_project_task_edges(
    project_id: str, request: Request, response: Response
) -> TaskEdgeListResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
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


@router.post(
    "/{project_id}/task-edges", response_model=TaskEdgeResponse, status_code=status.HTTP_201_CREATED
)
async def create_project_task_edge(
    project_id: str, payload: TaskEdgeCreateRequest, request: Request, response: Response
) -> TaskEdgeResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.task_edges.create", replacement="Task relationship API"
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


@task_edges_router.delete("/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request, response: Response) -> None:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="task_edges.delete", replacement="Task relationship API"
    )
    try:
        domain.delete_task_relationship(
            edge_id, user, idempotency_key=require_idempotency_key(request)
        )
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc
    return None


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
    domain = _domain_service(request)
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
                project_id, user, include_archived=include_archived, limit=limit, sort=sort
            )
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get("/{project_id}/members", response_model=ProjectMemberListResponse)
async def list_project_members(project_id: str, request: Request) -> ProjectMemberListResponse:
    domain = _domain_service(request)
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


@router.put("/{project_id}/members/{member_user_id}", response_model=ProjectMemberResponse)
async def upsert_project_member(
    project_id: str, member_user_id: str, payload: ProjectMemberRequest, request: Request
) -> ProjectMemberResponse:
    domain = _domain_service(request)
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
        member = next((item for item in members if item.get("user_id") == member_user_id), None)
        if member is None:
            raise RuntimeError("Updated Project member could not be read")
        return _serialize_domain_member(member, _get_auth_service(request))
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.delete("/{project_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_member(project_id: str, member_user_id: str, request: Request) -> None:
    domain = _domain_service(request)
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


@router.post("/{project_id}/owner-transfer", response_model=ProjectResponse)
async def transfer_project_owner(
    project_id: str, payload: ProjectOwnerTransferRequest, request: Request
) -> ProjectResponse:
    domain = _domain_service(request)
    user = get_current_user(request)
    try:
        domain.require_project_owner(project_id, user)
        domain.transfer_project_owner(
            project_id,
            payload.new_owner_user_id,
            user,
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
        return _serialize_domain_project(domain, domain.project(project_id, user), user)
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get("/{project_id}/collaborators", response_model=CollaboratorListResponse)
async def list_collaborators(
    project_id: str, request: Request, response: Response
) -> CollaboratorListResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.collaborators.list", replacement="Project member API"
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


@router.put(
    "/{project_id}/collaborators",
    response_model=CollaboratorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_collaborator(
    project_id: str, payload: CollaboratorRequest, request: Request, response: Response
) -> CollaboratorResponse:
    user = get_current_user(request)
    domain = _domain_service(request)
    _mark_v2_compatibility_route(
        response, route_name="projects.collaborators.add", replacement="Project member API"
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
            {"user_id": payload.user_id, "role": role, "can_publish": payload.can_publish},
            _get_auth_service(request),
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.delete("/{project_id}/collaborators/{user_id}", status_code=204)
async def remove_collaborator(project_id: str, user_id: str, request: Request) -> Response:
    user = get_current_user(request)
    domain = _domain_service(request)
    try:
        domain.require_project_owner(project_id, user)
        domain.remove_member(
            project_id, user_id, user, idempotency_key=require_idempotency_key(request)
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    response = Response(status_code=204)
    _mark_v2_compatibility_route(
        response, route_name="projects.collaborators.remove", replacement="Project member API"
    )
    return response

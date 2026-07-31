from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from ainrf.api.deprecation import mark_deprecated
from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.schemas import (
    ProjectCostSummaryResponse,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
    TaskListResponse,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import DomainPermissionError, ProjectModule
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import MaintenanceModeError

router = APIRouter(prefix="/projects", tags=["projects"])
task_edges_router = APIRouter(prefix="/task-edges", tags=["projects"])


def _project_module(request: Request) -> ProjectModule:
    module = getattr(request.app.state, "project_module", None)
    if not isinstance(module, ProjectModule) or not module.v2_ready():
        raise HTTPException(status_code=503, detail="Domain cutover is not ready")
    return module


def _active_domain_project(
    module: ProjectModule,
    project_id: str,
    user: dict[str, object],
) -> None:
    if module.project(project_id, user).get("status") != "active":
        raise DomainNotFoundError(project_id)


def _mark_retained_projection(
    response: Response,
    *,
    route_name: str,
    replacement: str,
) -> None:
    mark_deprecated(response, route=route_name, replacement=replacement)


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
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task edge not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected task edge error",
    )


@router.get("/{project_id}/cost-summary", response_model=ProjectCostSummaryResponse)
async def get_project_cost_summary(
    project_id: str,
    request: Request,
    response: Response,
) -> ProjectCostSummaryResponse:
    user = get_current_user(request)
    module = _project_module(request)
    try:
        _active_domain_project(module, project_id, user)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    projection = getattr(request.app.state, "project_cost_projection_service", None)
    summary = getattr(projection, "project_cost_summary", None)
    if not callable(summary):
        raise HTTPException(status_code=503, detail="Project cost projection is unavailable")
    _mark_retained_projection(
        response,
        route_name="projects.cost_summary",
        replacement="Attempt cost projection",
    )
    try:
        return ProjectCostSummaryResponse.model_validate(summary(project_id, user))
    except Exception as exc:
        raise _translate_project_error(exc) from exc


@router.get("/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_project_task_edges(
    project_id: str,
    request: Request,
    response: Response,
) -> TaskEdgeListResponse:
    user = get_current_user(request)
    module = _project_module(request)
    _mark_retained_projection(
        response,
        route_name="projects.task_edges.list",
        replacement="Task relationship Interface",
    )
    try:
        return TaskEdgeListResponse(
            items=[
                TaskEdgeResponse.model_validate(edge)
                for edge in module.list_task_relationships(project_id, user)
            ]
        )
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc


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
    module = _project_module(request)
    _mark_retained_projection(
        response,
        route_name="projects.task_edges.create",
        replacement="Task relationship Interface",
    )
    try:
        module.require_project_editor(project_id, user)
        return TaskEdgeResponse.model_validate(
            module.create_task_relationship(
                project_id,
                user,
                source_task_id=payload.source_task_id,
                target_task_id=payload.target_task_id,
                idempotency_key=require_idempotency_key(request),
            )
        )
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc


@task_edges_router.delete("/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request, response: Response) -> None:
    user = get_current_user(request)
    module = _project_module(request)
    _mark_retained_projection(
        response,
        route_name="task_edges.delete",
        replacement="Task relationship Interface",
    )
    try:
        module.delete_task_relationship(
            edge_id,
            user,
            idempotency_key=require_idempotency_key(request),
        )
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
    user = get_current_user(request)
    module = _project_module(request)
    try:
        _active_domain_project(module, project_id, user)
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

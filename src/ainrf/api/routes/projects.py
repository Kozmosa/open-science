from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.api.schemas import (
    ProjectCreateRequest,
    ProjectEnvironmentReferenceCreateRequest,
    ProjectEnvironmentReferenceListResponse,
    ProjectEnvironmentReferenceResponse,
    ProjectEnvironmentReferenceUpdateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
)
from ainrf.environments import (
    EnvironmentNotFoundError,
    InMemoryEnvironmentService,
    ProjectEnvironmentReference,
    ProjectReferenceConflictError,
    ProjectReferenceNotFoundError,
)
from ainrf.projects import ProjectNotFoundError, ProjectRegistryService
from ainrf.task_harness import (
    TaskHarnessError,
    TaskHarnessNotFoundError,
    TaskHarnessService,
)
from ainrf.workspaces import WorkspaceNotFoundError

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_project_service(request: Request) -> ProjectRegistryService:
    service = getattr(request.app.state, "project_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="project service not initialized")
    return service


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _serialize_project(project: any) -> ProjectResponse:
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


def _translate_project_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected project error",
    )


def _translate_reference_error(exc: Exception) -> HTTPException:
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
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected project environment reference error",
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    service = _get_project_service(request)
    try:
        items = [_serialize_project(project) for project in service.list_projects()]
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return ProjectListResponse(items=items)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreateRequest, request: Request) -> ProjectResponse:
    service = _get_project_service(request)
    try:
        project = service.create_project(
            name=payload.name,
            description=payload.description,
        )
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return _serialize_project(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def read_project(project_id: str, request: Request) -> ProjectResponse:
    service = _get_project_service(request)
    try:
        project = service.get_project(project_id)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return _serialize_project(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    request: Request,
) -> ProjectResponse:
    service = _get_project_service(request)
    try:
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
async def delete_project(project_id: str, request: Request) -> None:
    service = _get_project_service(request)
    try:
        service.delete_project(project_id)
    except Exception as exc:
        raise _translate_project_error(exc) from exc
    return None


@router.get(
    "/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceListResponse,
)
async def list_project_environment_refs(
    project_id: str,
    request: Request,
) -> ProjectEnvironmentReferenceListResponse:
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
    service = _get_environment_service(request)
    try:
        service.delete_project_reference(project_id, environment_id)
    except Exception as exc:
        raise _translate_reference_error(exc) from exc
    return None


def _get_task_harness_service(request: Request) -> TaskHarnessService:
    service = getattr(request.app.state, "task_harness_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="task harness service not initialized")
    return service


def _translate_task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaskHarnessNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=404, detail="Workspace not found")
    if exc.__class__.__name__ == "EnvironmentNotFoundError":
        return HTTPException(status_code=404, detail="Environment not found")
    if isinstance(exc, TaskHarnessError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected task harness error")


@router.get("/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_task_edges(project_id: str, request: Request) -> TaskEdgeListResponse:
    service = _get_task_harness_service(request)
    try:
        edges = service.get_task_edges(project_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeListResponse.model_validate(
        {
            "items": [
                {
                    "edge_id": edge.edge_id,
                    "project_id": edge.project_id,
                    "source_task_id": edge.source_task_id,
                    "target_task_id": edge.target_task_id,
                    "created_at": edge.created_at.isoformat(),
                }
                for edge in edges
            ]
        }
    )


@router.post(
    "/{project_id}/task-edges",
    response_model=TaskEdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_edge(
    project_id: str, payload: TaskEdgeCreateRequest, request: Request
) -> TaskEdgeResponse:
    service = _get_task_harness_service(request)
    try:
        edge = service.create_task_edge(
            project_id=project_id,
            source_task_id=payload.source_task_id,
            target_task_id=payload.target_task_id,
        )
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeResponse.model_validate(
        {
            "edge_id": edge.edge_id,
            "project_id": edge.project_id,
            "source_task_id": edge.source_task_id,
            "target_task_id": edge.target_task_id,
            "created_at": edge.created_at.isoformat(),
        }
    )


@router.delete("/{project_id}/task-edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(project_id: str, edge_id: str, request: Request) -> None:
    service = _get_task_harness_service(request)
    try:
        service.delete_task_edge(edge_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

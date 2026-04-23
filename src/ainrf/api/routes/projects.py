from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.api.schemas import (
    ProjectEnvironmentReferenceCreateRequest,
    ProjectEnvironmentReferenceListResponse,
    ProjectEnvironmentReferenceResponse,
    ProjectEnvironmentReferenceUpdateRequest,
)
from ainrf.environments import (
    EnvironmentNotFoundError,
    InMemoryEnvironmentService,
    ProjectEnvironmentReference,
    ProjectReferenceConflictError,
    ProjectReferenceNotFoundError,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _serialize_reference(
    reference: ProjectEnvironmentReference,
) -> ProjectEnvironmentReferenceResponse:
    payload = dict(asdict(reference))
    payload.pop("project_id", None)
    return ProjectEnvironmentReferenceResponse.model_validate(payload)


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

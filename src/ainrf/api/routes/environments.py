from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.api.schemas import (
    EnvironmentCreateRequest,
    EnvironmentListResponse,
    EnvironmentResponse,
    EnvironmentUpdateRequest,
)
from ainrf.environments import (
    AliasConflictError,
    DeleteReferencedEnvironmentError,
    DeleteSeedEnvironmentError,
    EnvironmentNotFoundError,
    InMemoryEnvironmentService,
)

router = APIRouter(prefix="/environments", tags=["environments"])


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _serialize_environment(
    service: InMemoryEnvironmentService,
    environment_id: str,
) -> EnvironmentResponse:
    environment = service.get_environment(environment_id)
    payload = asdict(environment)
    latest_detection = service.get_latest_detection(environment.id)
    payload["latest_detection"] = asdict(latest_detection) if latest_detection is not None else None
    return EnvironmentResponse.model_validate(payload)


def _translate_environment_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EnvironmentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if isinstance(exc, AliasConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Environment alias already exists"
        )
    if isinstance(exc, DeleteReferencedEnvironmentError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Environment is still referenced by a project",
        )
    if isinstance(exc, DeleteSeedEnvironmentError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Default localhost environment cannot be deleted",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected environment error"
    )


@router.get("", response_model=EnvironmentListResponse)
async def list_environments(request: Request) -> EnvironmentListResponse:
    service = _get_environment_service(request)
    items = [
        _serialize_environment(service, environment.id)
        for environment in service.list_environments()
    ]
    return EnvironmentListResponse(items=items)


@router.post("", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    payload: EnvironmentCreateRequest,
    request: Request,
) -> EnvironmentResponse:
    service = _get_environment_service(request)
    try:
        environment = service.create_environment(
            alias=payload.alias,
            display_name=payload.display_name,
            host=payload.host,
            description=payload.description,
            tags=payload.tags,
            port=payload.port,
            user=payload.user,
            auth_kind=payload.auth_kind,
            identity_file=payload.identity_file,
            proxy_jump=payload.proxy_jump,
            proxy_command=payload.proxy_command,
            ssh_options=payload.ssh_options,
            default_workdir=payload.default_workdir,
            preferred_python=payload.preferred_python,
            preferred_env_manager=payload.preferred_env_manager,
            preferred_runtime_notes=payload.preferred_runtime_notes,
            task_harness_profile=payload.task_harness_profile,
        )
    except Exception as exc:  # pragma: no cover - defensive translation
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment.id)


@router.get("/{environment_id}", response_model=EnvironmentResponse)
async def read_environment(environment_id: str, request: Request) -> EnvironmentResponse:
    service = _get_environment_service(request)
    try:
        return _serialize_environment(service, environment_id)
    except Exception as exc:
        raise _translate_environment_error(exc) from exc


@router.patch("/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
    environment_id: str,
    payload: EnvironmentUpdateRequest,
    request: Request,
) -> EnvironmentResponse:
    service = _get_environment_service(request)
    try:
        service.update_environment(
            environment_id,
            alias=payload.alias,
            display_name=payload.display_name,
            description=payload.description,
            tags=payload.tags,
            host=payload.host,
            port=payload.port,
            user=payload.user,
            auth_kind=payload.auth_kind,
            identity_file=payload.identity_file,
            proxy_jump=payload.proxy_jump,
            proxy_command=payload.proxy_command,
            ssh_options=payload.ssh_options,
            default_workdir=payload.default_workdir,
            preferred_python=payload.preferred_python,
            preferred_env_manager=payload.preferred_env_manager,
            preferred_runtime_notes=payload.preferred_runtime_notes,
            task_harness_profile=payload.task_harness_profile,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment_id)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(environment_id: str, request: Request) -> None:
    service = _get_environment_service(request)
    try:
        service.delete_environment(environment_id)
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    return None


@router.post("/{environment_id}/detect", response_model=EnvironmentResponse)
async def detect_environment(environment_id: str, request: Request) -> EnvironmentResponse:
    service = _get_environment_service(request)
    try:
        service.detect_environment(environment_id)
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment_id)

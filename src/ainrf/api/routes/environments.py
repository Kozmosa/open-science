from __future__ import annotations

from dataclasses import asdict
import logging

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.api.schemas import (
    EnvironmentCodeServerInstallResponse,
    EnvironmentCreateRequest,
    EnvironmentListResponse,
    EnvironmentResponse,
    EnvironmentUpdateRequest,
)
from ainrf.code_server_installer import CodeServerInstallError, install_code_server
from ainrf.environments import (
    AliasConflictError,
    DeleteReferencedEnvironmentError,
    DeleteSeedEnvironmentError,
    EnvironmentNotFoundError,
    InMemoryEnvironmentService,
)

router = APIRouter(prefix="/environments", tags=["environments"])
logger = logging.getLogger(__name__)


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
    if isinstance(exc, CodeServerInstallError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    logger.exception("Unexpected environment error", exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected environment error: {type(exc).__name__}: {exc}",
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
            code_server_path=payload.code_server_path,
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
            code_server_path=payload.code_server_path,
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


@router.post(
    "/{environment_id}/install-code-server", response_model=EnvironmentCodeServerInstallResponse
)
async def install_environment_code_server(
    environment_id: str,
    request: Request,
) -> EnvironmentCodeServerInstallResponse:
    service = _get_environment_service(request)
    app_user_id = request.headers.get("X-AINRF-User-Id")
    terminal_session_manager = getattr(request.app.state, "terminal_session_manager", None)
    terminal_attachment_broker = getattr(request.app.state, "terminal_attachment_broker", None)
    try:
        logger.info(
            "code_server_install_requested",
            extra={"environment_id": environment_id, "has_app_user_id": app_user_id is not None},
        )
        result = await install_code_server(
            environment_id,
            environment_service=service,
            app_user_id=app_user_id,
            terminal_session_manager=terminal_session_manager,
            terminal_attachment_broker=terminal_attachment_broker,
            api_base_url=str(request.base_url),
        )
        logger.info(
            "code_server_install_succeeded",
            extra={
                "environment_id": environment_id,
                "execution_mode": result.execution_mode,
                "already_installed": result.already_installed,
                "code_server_path": result.code_server_path,
            },
        )
    except Exception as exc:
        logger.exception(
            "code_server_install_failed",
            extra={"environment_id": environment_id, "has_app_user_id": app_user_id is not None},
        )
        raise _translate_environment_error(exc) from exc
    return EnvironmentCodeServerInstallResponse(
        environment=_serialize_environment(service, environment_id),
        installed=not result.already_installed,
        version=result.version,
        install_dir=result.install_dir,
        code_server_path=result.code_server_path,
        execution_mode=result.execution_mode,
        already_installed=result.already_installed,
        detail=result.detail,
        terminal_session_id=result.terminal_session_id,
        terminal_attachment_id=result.terminal_attachment_id,
        terminal_ws_url=result.terminal_ws_url,
        terminal_attachment_expires_at=result.terminal_attachment_expires_at,
    )


@router.post("/{environment_id}/detect", response_model=EnvironmentResponse)
async def detect_environment(environment_id: str, request: Request) -> EnvironmentResponse:
    service = _get_environment_service(request)
    app_user_id = request.headers.get("X-AINRF-User-Id")
    terminal_session_manager = getattr(request.app.state, "terminal_session_manager", None)
    try:
        logger.info(
            "environment_detect_requested",
            extra={"environment_id": environment_id, "has_app_user_id": app_user_id is not None},
        )
        snapshot = await service.detect_environment(
            environment_id,
            app_user_id=app_user_id,
            terminal_session_manager=terminal_session_manager,
        )
        logger.info(
            "environment_detect_completed",
            extra={
                "environment_id": environment_id,
                "status": snapshot.status,
                "warnings": snapshot.warnings,
                "errors": snapshot.errors,
                "code_server_path": snapshot.code_server.path,
            },
        )
    except Exception as exc:
        logger.exception(
            "environment_detect_failed",
            extra={"environment_id": environment_id, "has_app_user_id": app_user_id is not None},
        )
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment_id)

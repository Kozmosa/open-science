from __future__ import annotations

from dataclasses import asdict
import logging

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.auth.permissions import get_current_user, is_admin, require_admin
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
    user = get_current_user(request)
    service = _get_environment_service(request)
    if is_admin(user):
        environments = service.list_environments()
    else:
        auth_svc = getattr(request.app.state, "auth_service", None)
        if auth_svc is not None:
            accessible_ids = set(auth_svc.get_user_environment_ids(user["id"]))
        else:
            accessible_ids = set()
        environments = [env for env in service.list_environments() if env.id in accessible_ids]
    items = [_serialize_environment(service, environment.id) for environment in environments]
    return EnvironmentListResponse(items=items)


@router.post("", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    payload: EnvironmentCreateRequest,
    request: Request,
) -> EnvironmentResponse:
    user = get_current_user(request)
    require_admin(user)
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
    user = get_current_user(request)
    service = _get_environment_service(request)
    if not is_admin(user):
        auth_svc = getattr(request.app.state, "auth_service", None)
        if auth_svc is not None:
            accessible_ids = set(auth_svc.get_user_environment_ids(user["id"]))
            if environment_id not in accessible_ids:
                raise HTTPException(status_code=404, detail="Environment not found")
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
    user = get_current_user(request)
    require_admin(user)
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
    user = get_current_user(request)
    require_admin(user)
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
    user = get_current_user(request)
    require_admin(user)
    service = _get_environment_service(request)
    app_user_id = user["id"]
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
    user = get_current_user(request)
    service = _get_environment_service(request)
    # Verify the user has access to this environment
    if not is_admin(user):
        auth_svc = getattr(request.app.state, "auth_service", None)
        if auth_svc is not None:
            accessible_ids = set(auth_svc.get_user_environment_ids(user["id"]))
            if environment_id not in accessible_ids:
                raise HTTPException(status_code=404, detail="Environment not found")
    app_user_id = user["id"]
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
                "codex_path": snapshot.codex.path,
            },
        )
    except Exception as exc:
        logger.exception(
            "environment_detect_failed",
            extra={"environment_id": environment_id, "has_app_user_id": app_user_id is not None},
        )
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment_id)

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from typing import NotRequired, TypedDict

from fastapi import APIRouter, HTTPException, Request, Response, status

from ainrf.api.deprecation import mark_deprecated
from ainrf.api.idempotency import require_idempotency_key
from ainrf.auth.permissions import get_current_user, is_admin, require_admin
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
from ainrf.environments.models import DetectionSnapshot
from ainrf.domain import DomainPermissionError, DomainService
from ainrf.domain_control import DomainModelMode, MaintenanceModeError

router = APIRouter(prefix="/environments", tags=["environments"])
logger = logging.getLogger(__name__)


class _EnvironmentUpdateKwargs(TypedDict):
    """Typed sparse arguments forwarded to the durable Environment service."""

    alias: NotRequired[str | None]
    display_name: NotRequired[str | None]
    description: NotRequired[str | None]
    connection: NotRequired[dict[str, object]]


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _v2_domain_service(request: Request) -> DomainService | None:
    """Return the authoritative v2 service only after the cutover fuse is live."""

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
    """Record a deprecated-route use when the app wires the B7 telemetry hook."""

    _ = request
    mark_deprecated(response, route=route_name, replacement=replacement)


def _connection_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): item for key, item in parsed.items()}


def _connection_value(connection: dict[str, object], name: str, default: object) -> object:
    return connection.get(name, default)


def _serialize_domain_environment(
    environment: dict[str, object],
    *,
    latest_detection: DetectionSnapshot | None = None,
) -> EnvironmentResponse:
    """Project a durable Environment row onto the legacy response contract."""

    connection = _connection_object(environment.get("connection_json"))
    tags_value = _connection_value(connection, "tags", [])
    tags = [str(item) for item in tags_value] if isinstance(tags_value, list) else []
    ssh_options_value = _connection_value(connection, "ssh_options", {})
    ssh_options = (
        {str(key): str(value) for key, value in ssh_options_value.items()}
        if isinstance(ssh_options_value, dict)
        else {}
    )
    return EnvironmentResponse.model_validate(
        {
            "id": str(environment["environment_id"]),
            "alias": str(environment["alias"]),
            "display_name": str(environment["display_name"]),
            "description": environment.get("description"),
            "is_seed": bool(environment.get("is_seed", False)),
            "tags": tags,
            "host": str(_connection_value(connection, "host", "")),
            "port": _connection_value(connection, "port", 22),
            "user": str(_connection_value(connection, "user", "root")),
            "auth_kind": str(_connection_value(connection, "auth_kind", "ssh_key")),
            "identity_file": _connection_value(connection, "identity_file", None),
            "proxy_jump": _connection_value(connection, "proxy_jump", None),
            "proxy_command": _connection_value(connection, "proxy_command", None),
            "ssh_options": ssh_options,
            "default_workdir": _connection_value(connection, "default_workdir", None),
            "preferred_python": _connection_value(connection, "preferred_python", None),
            "preferred_env_manager": _connection_value(connection, "preferred_env_manager", None),
            "preferred_runtime_notes": _connection_value(
                connection, "preferred_runtime_notes", None
            ),
            "task_harness_profile": _connection_value(connection, "task_harness_profile", None),
            "created_at": environment.get("created_at"),
            "updated_at": environment.get("updated_at"),
            "latest_detection": asdict(latest_detection) if latest_detection is not None else None,
        }
    )


def _v2_latest_detection(request: Request, environment_id: str) -> DetectionSnapshot | None:
    observations = getattr(request.app.state, "environment_observation_service", None)
    get_latest = getattr(observations, "get_latest_detection", None)
    if not callable(get_latest):
        return None
    return get_latest(environment_id)


def _connection_from_create_payload(payload: EnvironmentCreateRequest) -> dict[str, object]:
    return {
        "host": payload.host,
        "port": payload.port,
        "user": payload.user,
        "auth_kind": payload.auth_kind.value,
        "identity_file": payload.identity_file,
        "proxy_jump": payload.proxy_jump,
        "proxy_command": payload.proxy_command,
        "ssh_options": payload.ssh_options,
        "default_workdir": payload.default_workdir,
        "preferred_python": payload.preferred_python,
        "preferred_env_manager": payload.preferred_env_manager,
        "preferred_runtime_notes": payload.preferred_runtime_notes,
        "task_harness_profile": payload.task_harness_profile,
        "tags": payload.tags,
    }


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
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain writes are paused for maintenance",
        )
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
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
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    logger.exception("Unexpected environment error", exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected environment error: {type(exc).__name__}: {exc}",
    )


@router.get("", response_model=EnvironmentListResponse)
async def list_environments(request: Request, response: Response) -> EnvironmentListResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "environments.list", "/domain/capabilities")
        try:
            return EnvironmentListResponse(
                items=[
                    _serialize_domain_environment(
                        environment,
                        latest_detection=_v2_latest_detection(
                            request, str(environment["environment_id"])
                        ),
                    )
                    for environment in domain.list_environments(user)
                ]
            )
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
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
    response: Response,
) -> EnvironmentResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            request, response, "environments.create", "/domain/capabilities"
        )
        try:
            environment = domain.create_environment(
                user,
                alias=payload.alias,
                display_name=payload.display_name,
                description=payload.description,
                connection=_connection_from_create_payload(payload),
                idempotency_key=require_idempotency_key(request, payload.idempotency_key),
            )
            return _serialize_domain_environment(environment)
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
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
        )
    except Exception as exc:  # pragma: no cover - defensive translation
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment.id)


@router.get("/{environment_id}", response_model=EnvironmentResponse)
async def read_environment(
    environment_id: str,
    request: Request,
    response: Response,
) -> EnvironmentResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(request, response, "environments.read", "/domain/capabilities")
        try:
            return _serialize_domain_environment(
                domain.environment(environment_id, user, include_disabled=False),
                latest_detection=_v2_latest_detection(request, environment_id),
            )
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
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
    response: Response,
) -> EnvironmentResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            request, response, "environments.update", "/domain/capabilities"
        )
        try:
            current = domain.environment(environment_id, user)
            fields_set = payload.model_fields_set
            connection = _connection_object(current.get("connection_json"))
            for name in (
                "host",
                "port",
                "user",
                "identity_file",
                "proxy_jump",
                "proxy_command",
                "ssh_options",
                "default_workdir",
                "preferred_python",
                "preferred_env_manager",
                "preferred_runtime_notes",
                "task_harness_profile",
                "tags",
            ):
                if name in fields_set:
                    connection[name] = getattr(payload, name)
            if "auth_kind" in fields_set:
                auth_kind = payload.auth_kind
                connection["auth_kind"] = (
                    auth_kind.value if hasattr(auth_kind, "value") else str(auth_kind)
                )
            kwargs: _EnvironmentUpdateKwargs = {
                "connection": connection,
            }
            if "alias" in fields_set:
                kwargs["alias"] = payload.alias
            if "display_name" in fields_set:
                kwargs["display_name"] = payload.display_name
            if "description" in fields_set:
                kwargs["description"] = payload.description
            environment = domain.update_environment(
                environment_id,
                user,
                idempotency_key=require_idempotency_key(request, payload.idempotency_key),
                **kwargs,
            )
            return _serialize_domain_environment(
                environment,
                latest_detection=_v2_latest_detection(request, environment_id),
            )
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
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
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    return _serialize_environment(service, environment_id)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    environment_id: str,
    request: Request,
    response: Response,
) -> None:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            request, response, "environments.delete", "/domain/capabilities"
        )
        try:
            domain.disable_environment(
                environment_id,
                user,
                idempotency_key=require_idempotency_key(request),
            )
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
        return None
    require_admin(user)
    service = _get_environment_service(request)
    try:
        service.delete_environment(environment_id)
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    return None


@router.post("/{environment_id}/detect", response_model=EnvironmentResponse)
async def detect_environment(
    environment_id: str,
    request: Request,
    response: Response,
) -> EnvironmentResponse:
    user = get_current_user(request)
    domain = _v2_domain_service(request)
    if domain is not None:
        _mark_v2_compatibility_route(
            request, response, "environments.detect", "/domain/capabilities"
        )
        try:
            environment = domain.environment(environment_id, user, include_disabled=False)
        except Exception as exc:
            raise _translate_environment_error(exc) from exc
        observations = getattr(request.app.state, "environment_observation_service", None)
        detect = getattr(observations, "detect_environment", None)
        if not callable(detect):  # pragma: no cover - create_app wires every v2 process
            raise HTTPException(
                status_code=500, detail="Environment observation service is unavailable"
            )
        try:
            snapshot = await detect(
                environment_id,
                app_user_id=user.get("id") if isinstance(user.get("id"), str) else None,
                terminal_session_manager=getattr(
                    request.app.state, "terminal_session_manager", None
                ),
            )
            return _serialize_domain_environment(environment, latest_detection=snapshot)
        except Exception as exc:
            logger.exception(
                "v2_environment_detect_failed", extra={"environment_id": environment_id}
            )
            raise _translate_environment_error(exc) from exc
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

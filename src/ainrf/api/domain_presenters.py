from __future__ import annotations

from dataclasses import asdict
import json
from typing import Literal, cast

from fastapi import HTTPException, Request

from ainrf.api.schemas import (
    EnvironmentCreateRequest,
    EnvironmentResponse,
    ProjectMemberResponse,
)
from ainrf.environments.models import DetectionSnapshot


def auth_service(request: Request) -> object:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


def serialize_project_member(member: dict[str, object], auth: object) -> ProjectMemberResponse:
    user_id = str(member["user_id"])
    username = ""
    display_name = ""
    get_user = getattr(auth, "get_user", None)
    if callable(get_user):
        try:
            auth_user = get_user(user_id)
            username_value = getattr(auth_user, "username", "")
            display_name_value = getattr(auth_user, "display_name", "")
            username = username_value if isinstance(username_value, str) else ""
            display_name = display_name_value if isinstance(display_name_value, str) else ""
        except Exception:
            pass
    role = str(member["role"])
    if role not in {"viewer", "editor"}:
        raise ValueError("Domain Project member has an invalid role")
    return ProjectMemberResponse(
        user_id=user_id,
        username=username,
        display_name=display_name,
        role=cast(Literal["viewer", "editor"], role),
        can_publish=bool(member.get("can_publish", False)),
    )


def environment_connection(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): item for key, item in parsed.items()}


def environment_connection_from_create(
    payload: EnvironmentCreateRequest,
) -> dict[str, object]:
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


def serialize_environment(
    environment: dict[str, object],
    *,
    latest_detection: DetectionSnapshot | None = None,
) -> EnvironmentResponse:
    connection = environment_connection(environment.get("connection_json"))
    tags_value = connection.get("tags", [])
    tags = [str(item) for item in tags_value] if isinstance(tags_value, list) else []
    ssh_options_value = connection.get("ssh_options", {})
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
            "host": str(connection.get("host", "")),
            "port": connection.get("port", 22),
            "user": str(connection.get("user", "root")),
            "auth_kind": str(connection.get("auth_kind", "ssh_key")),
            "identity_file": connection.get("identity_file"),
            "proxy_jump": connection.get("proxy_jump"),
            "proxy_command": connection.get("proxy_command"),
            "ssh_options": ssh_options,
            "default_workdir": connection.get("default_workdir"),
            "preferred_python": connection.get("preferred_python"),
            "preferred_env_manager": connection.get("preferred_env_manager"),
            "preferred_runtime_notes": connection.get("preferred_runtime_notes"),
            "task_harness_profile": connection.get("task_harness_profile"),
            "created_at": environment.get("created_at"),
            "updated_at": environment.get("updated_at"),
            "latest_detection": asdict(latest_detection) if latest_detection is not None else None,
        }
    )


def latest_environment_detection(request: Request, environment_id: str) -> DetectionSnapshot | None:
    observations = getattr(request.app.state, "environment_observation_service", None)
    get_latest = getattr(observations, "get_latest_detection", None)
    if not callable(get_latest):
        return None
    return get_latest(environment_id)

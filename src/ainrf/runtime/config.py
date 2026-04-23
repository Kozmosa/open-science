from __future__ import annotations

import getpass
import os
from copy import deepcopy
from typing import Any, cast

from ainrf.execution import ContainerConfig

DEFAULT_CONTAINER_PROFILE_NAME = "localhost"
DEFAULT_CONTAINER_HOST = "127.0.0.1"
DEFAULT_CONTAINER_PORT = 22
DEFAULT_CONTAINER_PROJECT_DIR = "/workspace/projects"
DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_COMMAND_TIMEOUT = 3600


def _default_container_user() -> str:
    env_user = (
        os.environ.get("AINRF_CONTAINER_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
    )
    if env_user:
        return env_user
    try:
        return getpass.getuser()
    except Exception:
        return "root"


DEFAULT_CONTAINER_USER = _default_container_user()


def build_default_container_profile() -> dict[str, str | int | None]:
    return {
        "host": DEFAULT_CONTAINER_HOST,
        "port": DEFAULT_CONTAINER_PORT,
        "user": DEFAULT_CONTAINER_USER,
        "ssh_key_path": None,
        "ssh_password": None,
        "project_dir": DEFAULT_CONTAINER_PROJECT_DIR,
        "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
        "command_timeout": DEFAULT_COMMAND_TIMEOUT,
    }


def build_default_runtime_config() -> dict[str, Any]:
    return {
        "container_profiles": {DEFAULT_CONTAINER_PROFILE_NAME: build_default_container_profile()},
        "default_container_profile": DEFAULT_CONTAINER_PROFILE_NAME,
    }


def normalize_runtime_config(payload: object) -> dict[str, Any]:
    normalized: dict[str, Any]
    if isinstance(payload, dict):
        normalized = cast(dict[str, Any], deepcopy(payload))
    else:
        normalized = {}

    raw_profiles = normalized.get("container_profiles")
    if isinstance(raw_profiles, dict):
        profiles: dict[str, Any] = cast(dict[str, Any], deepcopy(raw_profiles))
    else:
        profiles = {}
    profiles.setdefault(DEFAULT_CONTAINER_PROFILE_NAME, build_default_container_profile())
    normalized["container_profiles"] = profiles

    default_profile = normalized.get("default_container_profile")
    if not isinstance(default_profile, str) or not default_profile.strip():
        normalized["default_container_profile"] = DEFAULT_CONTAINER_PROFILE_NAME
    return normalized


def _parse_container_profile(profile: object) -> ContainerConfig | None:
    if not isinstance(profile, dict):
        return None
    normalized_profile = cast(dict[str, object], profile)
    host = normalized_profile.get("host")
    user = normalized_profile.get("user")
    if not isinstance(host, str) or not host or not isinstance(user, str) or not user:
        return None
    port = normalized_profile.get("port", DEFAULT_CONTAINER_PORT)
    if not isinstance(port, int):
        return None
    ssh_key_path = normalized_profile.get("ssh_key_path")
    ssh_password = normalized_profile.get("ssh_password")
    project_dir = normalized_profile.get("project_dir", DEFAULT_CONTAINER_PROJECT_DIR)
    connect_timeout = normalized_profile.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT)
    command_timeout = normalized_profile.get("command_timeout", DEFAULT_COMMAND_TIMEOUT)
    if not isinstance(project_dir, str):
        return None
    if not isinstance(connect_timeout, int) or not isinstance(command_timeout, int):
        return None
    return ContainerConfig(
        host=host,
        port=port,
        user=user,
        ssh_key_path=ssh_key_path if isinstance(ssh_key_path, str) else None,
        ssh_password=ssh_password if isinstance(ssh_password, str) and ssh_password else None,
        connect_timeout=connect_timeout,
        command_timeout=command_timeout,
        project_dir=project_dir,
    )


def parse_container_config_from_runtime_config(payload: object) -> ContainerConfig | None:
    if not isinstance(payload, dict):
        return _parse_container_profile(build_default_container_profile())

    normalized = normalize_runtime_config(payload)
    raw_profiles = normalized.get("container_profiles")
    if not isinstance(raw_profiles, dict):
        return None
    profiles = cast(dict[str, object], raw_profiles)

    default_profile_name = normalized.get("default_container_profile")
    if isinstance(default_profile_name, str):
        parsed_default = _parse_container_profile(profiles.get(default_profile_name))
        if parsed_default is not None:
            return parsed_default

    return _parse_container_profile(profiles.get(DEFAULT_CONTAINER_PROFILE_NAME))

"""Read-only Workspace registration path checks across execution environments."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from fastapi import Request

from ainrf.auth.service import (
    _is_container_environment,
    _linux_user_exists,
    tenant_linux_username,
)
from ainrf.environments.local import is_localhost_environment
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.ssh import SSHExecutor
from ainrf.files.service import _build_container_config

_PATH_TEST_TIMEOUT_SECONDS = 10.0
_TENANT_ROOT = Path("/home/ainrf_tenants")


class WorkspacePathPreflightError(ValueError):
    """Raised when a proposed canonical path cannot be used for execution."""


async def validate_workspace_registration_path(
    request: Request,
    *,
    environment_id: str,
    canonical_path: str,
    user_id: str,
) -> None:
    """Validate an existing directory with the identity that will execute Tasks."""

    environment_service = getattr(request.app.state, "environment_service", None)
    if environment_service is None:
        raise WorkspacePathPreflightError("Environment runtime is not initialized")
    try:
        environment = environment_service.get_environment(environment_id)
    except Exception as exc:
        raise WorkspacePathPreflightError("Environment runtime metadata is unavailable") from exc
    if not isinstance(environment, EnvironmentRegistryEntry):
        raise WorkspacePathPreflightError("Environment runtime metadata is invalid")
    tenant_user = _resolve_tenant_user(request, user_id)
    await validate_workspace_path(environment, canonical_path, tenant_user=tenant_user)


async def validate_workspace_path(
    environment: EnvironmentRegistryEntry,
    canonical_path: str,
    *,
    tenant_user: str | None = None,
) -> None:
    """Check directory existence and read/write/traverse permission without creating it."""

    path = Path(canonical_path)
    if not path.is_absolute():
        raise WorkspacePathPreflightError("Workspace canonical path must be absolute")
    is_local = not environment.host or is_localhost_environment(environment)
    if is_local:
        if tenant_user is not None:
            await _validate_local_tenant_path(canonical_path, tenant_user)
            return
        if _is_container_environment() and _is_under_tenant_root(path):
            raise WorkspacePathPreflightError(
                "Workspace tenant user is not provisioned for this canonical path"
            )
        if not path.is_dir():
            raise WorkspacePathPreflightError(
                "Workspace canonical path is not an existing directory"
            )
        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise WorkspacePathPreflightError(
                "Workspace canonical path requires read, write, and traverse permission"
            )
        return

    config = _build_container_config(environment)
    executor = SSHExecutor(config)
    quoted_path = shlex.quote(canonical_path)
    try:
        result = await executor.run_command(
            f"test -d {quoted_path} && test -r {quoted_path} && "
            f"test -w {quoted_path} && test -x {quoted_path}",
            timeout=_PATH_TEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise WorkspacePathPreflightError(
            "Workspace canonical path could not be verified through the Environment"
        ) from exc
    finally:
        await executor.close()
    if result.exit_code != 0:
        raise WorkspacePathPreflightError(
            "Workspace canonical path is missing or lacks read, write, and traverse permission"
        )


async def _validate_local_tenant_path(canonical_path: str, tenant_user: str) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            "-u",
            tenant_user,
            "--",
            "sh",
            "-c",
            'test -d "$1" && test -r "$1" && test -w "$1" && test -x "$1"',
            "workspace-path-preflight",
            canonical_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise WorkspacePathPreflightError(
            "Workspace tenant permission check could not be started"
        ) from exc
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_PATH_TEST_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise WorkspacePathPreflightError("Workspace tenant permission check timed out") from exc
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise WorkspacePathPreflightError(
            "Workspace canonical path is missing or inaccessible to the tenant user" + suffix
        )


def _resolve_tenant_user(request: Request, user_id: str) -> str | None:
    if not _is_container_environment():
        return None
    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is None:
        return None
    try:
        user = auth_service.get_user(user_id)
    except Exception:
        return None
    tenant_user = tenant_linux_username(user.username)
    return tenant_user if _linux_user_exists(tenant_user) else None


def _is_under_tenant_root(path: Path) -> bool:
    try:
        path.relative_to(_TENANT_ROOT)
    except ValueError:
        return False
    return True

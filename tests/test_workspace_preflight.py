"""Workspace registration path preflight behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ainrf.api import workspace_preflight
from ainrf.api.workspace_preflight import WorkspacePathPreflightError, validate_workspace_path
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.models import CommandResult

pytestmark = [pytest.mark.unit]


@pytest.mark.anyio
async def test_local_workspace_preflight_requires_an_existing_writable_directory(
    tmp_path: Path,
) -> None:
    environment = EnvironmentRegistryEntry(
        id="local",
        alias="local",
        display_name="Local",
        description=None,
        host="localhost",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    await validate_workspace_path(environment, str(workspace))

    with pytest.raises(WorkspacePathPreflightError, match="existing directory"):
        await validate_workspace_path(environment, str(tmp_path / "missing"))


@pytest.mark.anyio
async def test_local_tenant_workspace_preflight_runs_as_the_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

        def kill(self) -> None:
            raise AssertionError("successful preflight must not be killed")

    async def create_subprocess_exec(*args: object, **_kwargs: object) -> Process:
        calls.append(args)
        return Process()

    monkeypatch.setattr(
        workspace_preflight.asyncio, "create_subprocess_exec", create_subprocess_exec
    )
    environment = EnvironmentRegistryEntry(
        id="tenant-local",
        alias="tenant-local",
        display_name="Tenant local",
        description=None,
        host="127.0.0.1",
    )

    await validate_workspace_path(
        environment,
        str(tmp_path / "tenant-workspace"),
        tenant_user="ainrf_researcher",
    )

    assert calls
    assert calls[0][:6] == ("sudo", "-n", "-u", "ainrf_researcher", "--", "sh")


@pytest.mark.anyio
async def test_remote_workspace_preflight_uses_the_environment_ssh_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, float | None]] = []
    closed = False

    class Executor:
        def __init__(self, config: object) -> None:
            self.config = config

        async def run_command(
            self,
            command: str,
            timeout: float | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
        ) -> CommandResult:
            _ = cwd, env
            commands.append((command, timeout))
            return CommandResult(exit_code=0, stdout="", stderr="")

        async def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(workspace_preflight, "SSHExecutor", Executor)
    environment = EnvironmentRegistryEntry(
        id="remote",
        alias="remote",
        display_name="Remote",
        description=None,
        host="research.example",
        port=2222,
        user="scientist",
        identity_file="/keys/research",
    )

    await validate_workspace_path(environment, "/srv/research/workspace")

    assert commands == [
        (
            "test -d /srv/research/workspace && test -r /srv/research/workspace && "
            "test -w /srv/research/workspace && test -x /srv/research/workspace",
            10.0,
        )
    ]
    assert closed


@pytest.mark.anyio
async def test_remote_workspace_preflight_rejects_failed_permission_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Executor:
        def __init__(self, _config: object) -> None:
            pass

        async def run_command(self, *_args: object, **_kwargs: Any) -> CommandResult:
            return CommandResult(exit_code=1, stdout="", stderr="permission denied")

        async def close(self) -> None:
            pass

    monkeypatch.setattr(workspace_preflight, "SSHExecutor", Executor)
    environment = EnvironmentRegistryEntry(
        id="remote",
        alias="remote",
        display_name="Remote",
        description=None,
        host="research.example",
    )

    with pytest.raises(WorkspacePathPreflightError, match="missing or lacks"):
        await validate_workspace_path(environment, "/srv/research/workspace")

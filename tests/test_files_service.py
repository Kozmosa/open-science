from __future__ import annotations

import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.execution.models import CommandResult
from ainrf.files.service import FileBrowserService
from ainrf.workspaces.models import WorkspaceRecord

pytestmark = [pytest.mark.unit]


class _EnvironmentReader:
    def __init__(self, environment: EnvironmentRegistryEntry) -> None:
        self._environment = environment

    def get_environment(self, environment_id: str) -> EnvironmentRegistryEntry:
        assert environment_id == self._environment.id
        return self._environment

    def list_environments(self) -> list[EnvironmentRegistryEntry]:
        return [self._environment]

    def resolve_effective_workdir(
        self,
        project_id: str,
        environment_id: str,
        state_root: Path,
        /,
    ) -> str | None:
        del project_id, state_root
        assert environment_id == self._environment.id
        return self._environment.default_workdir


class _WorkspaceReader:
    def __init__(self, workspace: WorkspaceRecord) -> None:
        self._workspace = workspace

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        assert workspace_id == self._workspace.workspace_id
        return self._workspace


def _service(workdir: Path) -> FileBrowserService:
    environment = EnvironmentRegistryEntry(
        id="local-env",
        alias="local-env",
        display_name="Local environment",
        description=None,
        host="127.0.0.1",
        default_workdir=str(workdir),
    )
    now = datetime.now(UTC)
    workspace = WorkspaceRecord(
        workspace_id="tenant-workspace",
        project_id="tenant-project",
        label="Tenant workspace",
        description=None,
        default_workdir=str(workdir),
        workspace_prompt="",
        created_at=now,
        updated_at=now,
        owner_user_id="tenant-user",
    )
    return FileBrowserService(
        _EnvironmentReader(environment),
        _WorkspaceReader(workspace),
        cache_ttl_seconds=0,
    )


@pytest.mark.anyio
async def test_local_file_operations_run_as_tenant_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = tmp_path / "tenant-workspace"
    workdir.mkdir()
    (workdir / "visible.txt").write_text("tenant content", encoding="utf-8")
    upload_source = tmp_path / "upload.txt"
    upload_source.write_text("uploaded content", encoding="utf-8")
    upload_source.chmod(0o644)
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def run_as_user(user: str, *command: str) -> CommandResult:
        calls.append((user, command))
        if command[:2] == ("python3", "-c"):
            target = Path(command[3])
            if len(command) == 4:
                entries = [
                    {
                        "name": child.name,
                        "kind": "directory" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                    for child in target.iterdir()
                ]
                return CommandResult(0, json.dumps(entries), "")
            return CommandResult(0, base64.b64encode(target.read_bytes()).decode("ascii"), "")
        if command[:2] == ("mkdir", "-p"):
            Path(command[2]).mkdir(parents=True, exist_ok=True)
            return CommandResult(0, "", "")
        if command[0] == "cp":
            shutil.copy(command[1], command[2])
            return CommandResult(0, "", "")
        if command[:3] == ("stat", "-c", "%s"):
            return CommandResult(0, str(Path(command[3]).stat().st_size), "")
        raise AssertionError(f"Unexpected tenant command: {command}")

    monkeypatch.setattr(FileBrowserService, "_run_local_command", staticmethod(run_as_user))
    service = _service(workdir)

    listing = await service.list_directory(
        "local-env",
        "",
        "tenant-workspace",
        run_as_user="ainrf_tenant",
    )
    content = await service.read_file(
        "local-env",
        "visible.txt",
        "tenant-workspace",
        run_as_user="ainrf_tenant",
    )
    streamed = await service.read_stream_file(
        str(workdir / "visible.txt"),
        run_as_user="ainrf_tenant",
    )
    uploaded = await service.upload_file(
        "local-env",
        "uploaded.txt",
        upload_source,
        "tenant-workspace",
        run_as_user="ainrf_tenant",
    )

    assert [entry.name for entry in listing.entries] == ["visible.txt"]
    assert content.content == "tenant content"
    assert streamed == b"tenant content"
    assert uploaded.path == str(workdir / "uploaded.txt")
    assert (workdir / "uploaded.txt").read_text(encoding="utf-8") == "uploaded content"
    assert len(calls) == 6
    assert {user for user, _command in calls} == {"ainrf_tenant"}

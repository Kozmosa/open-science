from __future__ import annotations

import base64
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ainrf.environments.local import is_localhost_environment
from ainrf.execution.models import CommandResult, ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.files.cache import FileTreeCache
from ainrf.files.language_map import is_image_file, language_from_path, mime_type_from_path
from ainrf.files.models import DirectoryListing, FileContent, FileEntry, FileKind, FileUploadResult

if TYPE_CHECKING:
    from ainrf.environments.models import EnvironmentRegistryEntry
    from ainrf.environments.protocols import EnvironmentRuntimeReader
    from ainrf.workspaces.models import WorkspaceRecord

_MAX_FILE_SIZE_BYTES = 50_000_000
_MAX_DIRECTORY_ENTRIES = 1_000
_BINARY_PROBE_BYTES = 8_192
_STREAM_FILE_SIZE_BYTES = 100 * 1024 * 1024


class WorkspaceReader(Protocol):
    def get_workspace(self, workspace_id: str) -> WorkspaceRecord: ...


class FileBrowserError(Exception):
    pass


class PathNotFoundError(FileBrowserError):
    pass


class FileTooLargeError(FileBrowserError):
    pass


class _EnvironmentResolver:
    def __init__(
        self,
        environment_service: EnvironmentRuntimeReader,
        workspace_service: WorkspaceReader | None = None,
    ) -> None:
        self._environment_service = environment_service
        self._workspace_service = workspace_service

    def resolve(
        self, environment_id: str, workspace_id: str | None = None
    ) -> tuple[EnvironmentRegistryEntry, str]:
        environment = self._environment_service.get_environment(environment_id)
        if workspace_id is not None and self._workspace_service is not None:
            workspace = self._workspace_service.get_workspace(workspace_id)
            workdir = workspace.default_workdir or environment.default_workdir or "/"
        else:
            workdir = environment.default_workdir or "/"
        if workdir.startswith("~"):
            workdir = str(Path(workdir).expanduser().resolve())
        return environment, workdir


def _resolve_path(workdir: str, path: str) -> str:
    if not path:
        return workdir
    if path.startswith("/"):
        # Use absolute() instead of resolve() to avoid following symlinks
        resolved = Path(path).absolute()
    else:
        resolved = (Path(workdir) / path).absolute()
    workdir_resolved = Path(workdir).absolute()
    try:
        resolved.relative_to(workdir_resolved)
    except ValueError:
        raise PathNotFoundError("Path is outside the workspace directory")
    return str(resolved)


def _build_container_config(environment: EnvironmentRegistryEntry) -> ContainerConfig:
    return ContainerConfig(
        host=environment.host,
        port=environment.port,
        user=environment.user,
        ssh_key_path=environment.identity_file,
        project_dir=environment.default_workdir or "/",
    )


class FileBrowserService:
    def __init__(
        self,
        environment_service: EnvironmentRuntimeReader,
        workspace_service: WorkspaceReader | None = None,
        cache_ttl_seconds: float = 60.0,
        max_file_size_bytes: int = _MAX_FILE_SIZE_BYTES,
    ) -> None:
        self._environment_service = environment_service
        self._cache = FileTreeCache(ttl_seconds=cache_ttl_seconds)
        self._max_file_size = max_file_size_bytes
        self._resolver = _EnvironmentResolver(environment_service, workspace_service)

    async def list_directory(
        self,
        environment_id: str,
        path: str,
        workspace_id: str | None = None,
        *,
        run_as_user: str | None = None,
    ) -> DirectoryListing:
        environment, workdir = self._resolver.resolve(environment_id, workspace_id)
        resolved_path = _resolve_path(workdir, path)
        cache_key = f"{environment_id}:{workspace_id or ''}:{run_as_user or ''}:{resolved_path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if is_localhost_environment(environment):
            listing = await self._list_local(resolved_path, run_as_user=run_as_user)
        else:
            listing = await self._list_remote(environment, resolved_path)

        self._cache.set(cache_key, listing)
        return listing

    async def read_file(
        self,
        environment_id: str,
        path: str,
        workspace_id: str | None = None,
        *,
        run_as_user: str | None = None,
    ) -> FileContent:
        environment, workdir = self._resolver.resolve(environment_id, workspace_id)
        resolved_path = _resolve_path(workdir, path)

        if is_localhost_environment(environment):
            return await self._read_local(resolved_path, run_as_user=run_as_user)
        return await self._read_remote(environment, resolved_path)

    async def read_stream_file(
        self,
        path: str,
        *,
        run_as_user: str | None = None,
    ) -> bytes:
        return await self._read_local_bytes(
            path,
            max_file_size_bytes=_STREAM_FILE_SIZE_BYTES,
            run_as_user=run_as_user,
        )

    async def resolve_stream_target(
        self, environment_id: str, path: str, workspace_id: str | None = None
    ):
        """Return (is_local, local_path, environment_obj) for streaming a file."""
        environment, workdir = self._resolver.resolve(environment_id, workspace_id)
        resolved_path = _resolve_path(workdir, path)
        return (
            is_localhost_environment(environment),
            resolved_path,
            environment,
        )

    def invalidate_cache(self, environment_id: str) -> None:
        self._cache.invalidate_environment(environment_id)

    async def upload_file(
        self,
        environment_id: str,
        path: str,
        local_temp_path: Path,
        workspace_id: str | None = None,
        *,
        run_as_user: str | None = None,
    ) -> FileUploadResult:
        environment, workdir = self._resolver.resolve(environment_id, workspace_id)
        resolved_path = _resolve_path(workdir, path)

        if is_localhost_environment(environment):
            if run_as_user is None:
                target = Path(resolved_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(local_temp_path, target)
                size = target.stat().st_size
            else:
                mkdir_result = await self._run_local_command(
                    run_as_user,
                    "mkdir",
                    "-p",
                    str(Path(resolved_path).parent),
                )
                self._require_local_command(mkdir_result, "create upload directory")
                copy_result = await self._run_local_command(
                    run_as_user,
                    "cp",
                    str(local_temp_path),
                    resolved_path,
                )
                self._require_local_command(copy_result, "copy uploaded file")
                size_result = await self._run_local_command(
                    run_as_user,
                    "stat",
                    "-c",
                    "%s",
                    resolved_path,
                )
                self._require_local_command(size_result, "read uploaded file size")
                try:
                    size = int(size_result.stdout.strip())
                except ValueError as exc:
                    raise FileBrowserError("Uploaded file size could not be read") from exc
        else:
            config = _build_container_config(environment)
            executor = SSHExecutor(config)
            try:
                await executor.upload(local_temp_path, resolved_path)
            finally:
                await executor.close()
            size = local_temp_path.stat().st_size

        self.invalidate_cache(environment_id)
        return FileUploadResult(path=resolved_path, size=size)

    async def _list_local(
        self,
        path: str,
        *,
        run_as_user: str | None = None,
    ) -> DirectoryListing:
        if run_as_user is not None:
            return await self._list_local_as_user(path, run_as_user)
        target = Path(path)
        if not target.exists():
            raise PathNotFoundError(f"Directory not found: {path}")
        if not target.is_dir():
            raise PathNotFoundError(f"Path is not a directory: {path}")

        entries: list[FileEntry] = []
        for item in target.iterdir():
            if item.is_symlink():
                kind = "symlink"
            elif item.is_dir():
                kind = "directory"
            else:
                kind = "file"
            size = item.stat().st_size if item.is_file() and not item.is_symlink() else None
            entries.append(
                FileEntry(
                    name=item.name,
                    path=str(item.resolve()),
                    kind=kind,
                    size=size,
                )
            )
            if len(entries) >= _MAX_DIRECTORY_ENTRIES:
                break

        entries.sort(key=lambda e: (0 if e.kind == "directory" else 1, e.name.lower()))
        return DirectoryListing(path=path, entries=entries)

    async def _list_local_as_user(self, path: str, run_as_user: str) -> DirectoryListing:
        script = """
import json
import os
import sys

path = sys.argv[1]
if not os.path.exists(path):
    print("not-found", file=sys.stderr)
    raise SystemExit(2)
if not os.path.isdir(path):
    print("not-directory", file=sys.stderr)
    raise SystemExit(3)
entries = []
for name in os.listdir(path):
    target = os.path.join(path, name)
    if os.path.islink(target):
        kind = "symlink"
    elif os.path.isdir(target):
        kind = "directory"
    else:
        kind = "file"
    size = os.path.getsize(target) if kind == "file" else None
    entries.append({"name": name, "kind": kind, "size": size})
print(json.dumps(entries))
"""
        result = await self._run_local_command(run_as_user, "python3", "-c", script, path)
        if result.exit_code in {2, 3}:
            raise PathNotFoundError(f"Directory not found: {path}")
        if result.exit_code != 0:
            raise FileBrowserError(f"Failed to list directory: {result.stderr.strip()}")
        try:
            raw_entries = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FileBrowserError(f"Invalid directory listing response: {exc}") from exc
        entries = [
            FileEntry(
                name=str(item["name"]),
                path=str(Path(path) / str(item["name"])),
                kind=cast(FileKind, str(item["kind"])),
                size=int(item["size"]) if item["size"] is not None else None,
            )
            for item in raw_entries[:_MAX_DIRECTORY_ENTRIES]
        ]
        entries.sort(key=lambda entry: (0 if entry.kind == "directory" else 1, entry.name.lower()))
        return DirectoryListing(path=path, entries=entries)

    async def _list_remote(
        self, environment: EnvironmentRegistryEntry, path: str
    ) -> DirectoryListing:
        quoted_path = shlex.quote(path)
        script = (
            f"import os, json; p={quoted_path}; "
            f"entries=[]; "
            f"[entries.append({{'n':n,'k':'directory' if os.path.isdir(os.path.join(p,n)) else 'file',"
            f"'s':os.path.getsize(os.path.join(p,n)) if os.path.isfile(os.path.join(p,n)) else None}}) "
            f"for n in os.listdir(p)]; "
            f"print(json.dumps(entries))"
        )
        cmd = f"python3 -c {shlex.quote(script)}"
        result = await self._run_ssh_command(environment, cmd)
        if result.exit_code != 0:
            if "No such file" in result.stderr or "Not a directory" in result.stderr:
                raise PathNotFoundError(f"Directory not found: {path}")
            raise FileBrowserError(f"Failed to list directory: {result.stderr.strip()}")

        try:
            raw_entries = json.loads(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise FileBrowserError(f"Invalid directory listing response: {exc}")

        entries: list[FileEntry] = []
        for item in raw_entries:
            entries.append(
                FileEntry(
                    name=item["n"],
                    path=str(Path(path) / item["n"]),
                    kind=item["k"],
                    size=item.get("s"),
                )
            )
            if len(entries) >= _MAX_DIRECTORY_ENTRIES:
                break

        entries.sort(key=lambda e: (0 if e.kind == "directory" else 1, e.name.lower()))
        return DirectoryListing(path=path, entries=entries)

    async def _read_local(
        self,
        path: str,
        *,
        run_as_user: str | None = None,
    ) -> FileContent:
        data = await self._read_local_bytes(
            path,
            max_file_size_bytes=self._max_file_size,
            run_as_user=run_as_user,
        )
        return self._build_file_content(path, data)

    async def _read_local_bytes(
        self,
        path: str,
        *,
        max_file_size_bytes: int,
        run_as_user: str | None,
    ) -> bytes:
        if run_as_user is not None:
            script = """
import base64
import os
import sys

path = sys.argv[1]
limit = int(sys.argv[2])
if not os.path.exists(path):
    print("not-found", file=sys.stderr)
    raise SystemExit(2)
if os.path.isdir(path):
    print("is-directory", file=sys.stderr)
    raise SystemExit(3)
if os.path.getsize(path) > limit:
    print("too-large", file=sys.stderr)
    raise SystemExit(4)
with open(path, "rb") as handle:
    sys.stdout.write(base64.b64encode(handle.read()).decode("ascii"))
"""
            result = await self._run_local_command(
                run_as_user,
                "python3",
                "-c",
                script,
                path,
                str(max_file_size_bytes),
            )
            if result.exit_code in {2, 3}:
                raise PathNotFoundError(f"File not found: {path}")
            if result.exit_code == 4:
                raise FileTooLargeError(f"File exceeds {max_file_size_bytes // 1_048_576} MB limit")
            if result.exit_code != 0:
                raise FileBrowserError(f"Failed to read file: {result.stderr.strip()}")
            try:
                return base64.b64decode(result.stdout, validate=True)
            except ValueError as exc:
                raise FileBrowserError("Invalid local file response") from exc

        from anyio import to_thread

        target = Path(path)

        def _check() -> tuple[bool, bool]:
            return (target.exists(), target.is_dir())

        exists, is_dir = await to_thread.run_sync(_check)
        if not exists:
            raise PathNotFoundError(f"File not found: {path}")
        if is_dir:
            raise PathNotFoundError(f"Path is a directory: {path}")
        stat = await to_thread.run_sync(target.stat)
        if stat.st_size > max_file_size_bytes:
            raise FileTooLargeError(f"File exceeds {max_file_size_bytes // 1_048_576} MB limit")
        return await to_thread.run_sync(target.read_bytes)

    @staticmethod
    async def _run_local_command(run_as_user: str, *command: str) -> CommandResult:
        from anyio import to_thread

        try:
            process = await to_thread.run_sync(
                lambda: subprocess.run(
                    ("sudo", "-n", "-u", run_as_user, "--", *command),
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=30,
                )
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FileBrowserError(f"Tenant file command could not be started: {exc}") from exc
        return CommandResult(
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

    @staticmethod
    def _require_local_command(result: CommandResult, action: str) -> None:
        if result.exit_code != 0:
            detail = result.stderr.strip() or f"exit code {result.exit_code}"
            raise FileBrowserError(f"Failed to {action}: {detail}")

    async def _read_remote(self, environment: EnvironmentRegistryEntry, path: str) -> FileContent:
        quoted_path = shlex.quote(path)

        size_result = await self._run_ssh_command(
            environment, f"stat -c %s {quoted_path} 2>/dev/null || echo -1"
        )
        try:
            size = int(size_result.stdout.strip())
        except ValueError:
            size = -1
        if size < 0:
            raise PathNotFoundError(f"File not found: {path}")
        if size > self._max_file_size:
            raise FileTooLargeError(f"File exceeds {self._max_file_size // 1_048_576} MB limit")

        if is_image_file(path):
            result = await self._run_ssh_command(environment, f"base64 {quoted_path}")
            if result.exit_code != 0:
                raise FileBrowserError(f"Failed to read file: {result.stderr.strip()}")
            return FileContent(
                path=path,
                content=result.stdout.strip(),
                is_binary=True,
                size=size,
                mime_type=mime_type_from_path(path),
            )

        result = await self._run_ssh_command(environment, f"cat {quoted_path}")
        if result.exit_code != 0:
            raise FileBrowserError(f"Failed to read file: {result.stderr.strip()}")
        return self._build_file_content(path, result.stdout.encode("utf-8", errors="replace"))

    def _build_file_content(self, path: str, data: bytes) -> FileContent:
        is_binary = b"\x00" in data[:_BINARY_PROBE_BYTES]
        mime_type = mime_type_from_path(path)
        if is_binary:
            return FileContent(
                path=path,
                content=base64.b64encode(data).decode("ascii"),
                is_binary=True,
                size=len(data),
                mime_type=mime_type,
            )
        text = data.decode("utf-8", errors="replace")
        return FileContent(
            path=path,
            content=text,
            is_binary=False,
            size=len(data),
            language=language_from_path(path),
            mime_type=mime_type,
        )

    async def _run_ssh_command(
        self, environment: EnvironmentRegistryEntry, cmd: str
    ) -> CommandResult:
        config = _build_container_config(environment)
        executor = SSHExecutor(config)
        try:
            return await executor.run_command(cmd)
        except Exception as exc:
            raise FileBrowserError(f"SSH command failed: {exc}") from exc
        finally:
            await executor.close()

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from ainrf.environments.local import is_localhost_environment
from ainrf.execution.models import CommandResult, ContainerConfig
from ainrf.execution.ssh import SSHExecutor
from ainrf.files.cache import FileTreeCache
from ainrf.files.language_map import is_image_file, language_from_path, mime_type_from_path
from ainrf.files.models import DirectoryListing, FileContent, FileEntry

if TYPE_CHECKING:
    from ainrf.environments.models import EnvironmentRegistryEntry
    from ainrf.environments.service import InMemoryEnvironmentService

_MAX_FILE_SIZE_BYTES = 1_048_576
_MAX_DIRECTORY_ENTRIES = 1_000
_BINARY_PROBE_BYTES = 8_192


class FileBrowserError(Exception):
    pass


class PathNotFoundError(FileBrowserError):
    pass


class FileTooLargeError(FileBrowserError):
    pass


class _EnvironmentResolver:
    def __init__(self, environment_service: InMemoryEnvironmentService) -> None:
        self._environment_service = environment_service

    def resolve(self, environment_id: str) -> tuple[EnvironmentRegistryEntry, str]:
        environment = self._environment_service.get_environment(environment_id)
        workdir = environment.default_workdir or "/"
        return environment, workdir


def _resolve_path(workdir: str, path: str) -> str:
    if not path:
        return workdir
    if path.startswith("/"):
        resolved = Path(path).resolve()
    else:
        resolved = (Path(workdir) / path).resolve()
    workdir_resolved = Path(workdir).resolve()
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
        environment_service: InMemoryEnvironmentService,
        cache_ttl_seconds: float = 60.0,
        max_file_size_bytes: int = _MAX_FILE_SIZE_BYTES,
    ) -> None:
        self._environment_service = environment_service
        self._cache = FileTreeCache(ttl_seconds=cache_ttl_seconds)
        self._max_file_size = max_file_size_bytes
        self._resolver = _EnvironmentResolver(environment_service)

    async def list_directory(self, environment_id: str, path: str) -> DirectoryListing:
        environment, workdir = self._resolver.resolve(environment_id)
        resolved_path = _resolve_path(workdir, path)
        cache_key = f"{environment_id}:{resolved_path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if is_localhost_environment(environment):
            listing = await self._list_local(resolved_path)
        else:
            listing = await self._list_remote(environment, resolved_path)

        self._cache.set(cache_key, listing)
        return listing

    async def read_file(self, environment_id: str, path: str) -> FileContent:
        environment, workdir = self._resolver.resolve(environment_id)
        resolved_path = _resolve_path(workdir, path)

        if is_localhost_environment(environment):
            return await self._read_local(resolved_path)
        return await self._read_remote(environment, resolved_path)

    def invalidate_cache(self, environment_id: str) -> None:
        self._cache.invalidate_environment(environment_id)

    async def _list_local(self, path: str) -> DirectoryListing:
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

    async def _read_local(self, path: str) -> FileContent:
        target = Path(path)
        if not target.exists():
            raise PathNotFoundError(f"File not found: {path}")
        if target.is_dir():
            raise PathNotFoundError(f"Path is a directory: {path}")

        size = target.stat().st_size
        if size > self._max_file_size:
            raise FileTooLargeError(f"File exceeds {self._max_file_size // 1024} KB limit")

        data = target.read_bytes()
        return self._build_file_content(path, data)

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
            raise FileTooLargeError(f"File exceeds {self._max_file_size // 1024} KB limit")

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
        if is_binary:
            return FileContent(
                path=path,
                content="",
                is_binary=True,
                size=len(data),
            )
        text = data.decode("utf-8", errors="replace")
        return FileContent(
            path=path,
            content=text,
            is_binary=False,
            size=len(data),
            language=language_from_path(path),
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

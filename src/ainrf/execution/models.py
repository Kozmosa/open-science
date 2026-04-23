from __future__ import annotations

from dataclasses import dataclass, field
from os import environ


@dataclass(slots=True)
class ContainerConfig:
    host: str
    port: int = 22
    user: str = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    connect_timeout: int = 30
    command_timeout: int = 3600
    project_dir: str = "/workspace/projects"

    @classmethod
    def from_env(cls, prefix: str = "AINRF_CONTAINER_") -> ContainerConfig:
        host = environ.get(f"{prefix}HOST")
        if not host:
            raise ValueError(f"Missing required environment variable: {prefix}HOST")

        port = int(environ.get(f"{prefix}PORT", "22"))
        user = environ.get(f"{prefix}USER", "root")
        ssh_key_path = environ.get(f"{prefix}SSH_KEY_PATH")
        ssh_password = environ.get(f"{prefix}PASSWORD")
        connect_timeout = int(environ.get(f"{prefix}CONNECT_TIMEOUT", "30"))
        command_timeout = int(environ.get(f"{prefix}COMMAND_TIMEOUT", "3600"))
        project_dir = environ.get(f"{prefix}PROJECT_DIR", "/workspace/projects")

        return cls(
            host=host,
            port=port,
            user=user,
            ssh_key_path=ssh_key_path,
            ssh_password=ssh_password,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
            project_dir=project_dir,
        )


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class ContainerHealth:
    ssh_ok: bool
    claude_ok: bool
    project_dir_writable: bool
    claude_version: str | None = None
    gpu_models: list[str] = field(default_factory=list)
    cuda_version: str | None = None
    disk_free_bytes: int | None = None
    warnings: list[str] = field(default_factory=list)

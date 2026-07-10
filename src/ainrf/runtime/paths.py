from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_TENANT_HOME_ROOT = Path("/home/ainrf_tenants")


@dataclass(frozen=True, slots=True)
class RuntimePathConfig:
    startup_cwd: Path

    @property
    def workspace_root(self) -> Path:
        return self.startup_cwd / "workspace"

    @property
    def default_workspace_dir(self) -> Path:
        return Path.home() / ".ainrf_workspaces" / "default"

    def tenant_workspace_dir(self, username: str, label: str = "default") -> Path:
        """Return the workspace directory for a tenant user.

        Convention: ``/home/ainrf_tenants/<username>/workspaces/<label>/``.
        """
        return _TENANT_HOME_ROOT / username / "workspaces" / label

    def ensure_default_workspace_dir(self) -> Path:
        path = self.default_workspace_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


def build_runtime_path_config(startup_cwd: Path | None = None) -> RuntimePathConfig:
    return RuntimePathConfig(startup_cwd=(startup_cwd or Path.cwd()).resolve())

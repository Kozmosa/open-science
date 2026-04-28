from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePathConfig:
    startup_cwd: Path

    @property
    def workspace_root(self) -> Path:
        return self.startup_cwd / "workspace"

    @property
    def default_workspace_dir(self) -> Path:
        return self.workspace_root / "default"

    def ensure_default_workspace_dir(self) -> Path:
        path = self.default_workspace_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


def build_runtime_path_config(startup_cwd: Path | None = None) -> RuntimePathConfig:
    return RuntimePathConfig(startup_cwd=(startup_cwd or Path.cwd()).resolve())

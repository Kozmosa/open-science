from __future__ import annotations

import json
import os
import pwd
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ainrf.execution import ContainerConfig
from ainrf.runtime import parse_container_config_from_runtime_config
from ainrf.runtime.paths import RuntimePathConfig, build_runtime_path_config
from ainrf.state import default_state_root


def hash_api_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _parse_api_key_hashes(raw: str) -> frozenset[str]:
    hashes = {item.strip() for item in raw.split(",") if item.strip()}
    return frozenset(hashes)


def _default_terminal_command() -> tuple[str, ...]:
    shell_path: str | None
    try:
        shell_path = pwd.getpwuid(os.getuid()).pw_shell
    except Exception:
        shell_path = None
    if not shell_path:
        shell_path = os.environ.get("SHELL")
    if not shell_path:
        shell_path = "/bin/sh"
    return (shell_path,)


@dataclass(slots=True)
class ApiConfig:
    api_key_hashes: frozenset[str]
    state_root: Path
    container_config: ContainerConfig | None = None
    terminal_command: tuple[str, ...] = field(default_factory=_default_terminal_command)
    code_server_host: str = "127.0.0.1"
    code_server_port: int = 18080
    code_server_workspace_dir: Path | None = None
    startup_cwd: Path = field(default_factory=Path.cwd)

    @property
    def runtime_paths(self) -> RuntimePathConfig:
        return build_runtime_path_config(self.startup_cwd)

    @classmethod
    def from_env(cls, state_root: Path | None = None) -> ApiConfig:
        startup_cwd = Path.cwd().resolve()
        resolved_state_root = state_root or default_state_root()
        env_hashes = os.environ.get("AINRF_API_KEY_HASHES")
        api_key_hashes = _parse_api_key_hashes(env_hashes) if env_hashes else frozenset()

        payload: object | None = None
        config_path = resolved_state_root / "config.json"
        if config_path.exists():
            payload = json.loads(config_path.read_text(encoding="utf-8"))

        if not api_key_hashes:
            api_key_hashes = cls._parse_config_hashes(payload)

        if not api_key_hashes:
            raise ValueError("AINRF API key hashes are not configured")

        try:
            container_config = ContainerConfig.from_env()
        except ValueError:
            container_config = parse_container_config_from_runtime_config(payload)

        return cls(
            api_key_hashes=api_key_hashes,
            state_root=resolved_state_root,
            container_config=container_config,
            code_server_workspace_dir=Path(container_config.project_dir)
            if container_config
            else None,
            startup_cwd=startup_cwd,
        )

    @staticmethod
    def _parse_config_hashes(payload: object) -> frozenset[str]:
        if not isinstance(payload, dict):
            return frozenset()
        normalized_payload = cast(dict[str, object], payload)
        raw_hashes = normalized_payload.get("api_key_hashes")
        if not isinstance(raw_hashes, list):
            return frozenset()
        normalized = {item for item in raw_hashes if isinstance(item, str) and item}
        return frozenset(normalized)

    def verify_api_key(self, value: str | None) -> bool:
        if value is None:
            return False
        return hash_api_key(value) in self.api_key_hashes

    def as_public_health_payload(self) -> dict[str, Any]:
        return {
            "state_root": str(self.state_root),
            "startup_cwd": str(self.startup_cwd),
            "default_workspace_dir": str(self.runtime_paths.default_workspace_dir),
            "container_configured": self.container_config is not None,
        }

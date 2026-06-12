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
    startup_cwd: Path = field(default_factory=Path.cwd)
    production: bool = False
    allowed_cidrs: tuple[str, ...] = ()
    max_request_body_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_concurrent_requests: int = 0  # 0 = unlimited
    login_max_failures: int = 10
    login_lockout_hours: int = 24
    metrics_enabled: bool = False
    metrics_path: str = "/metrics"
    slow_request_threshold_seconds: float = 5.0
    public_registration_enabled: bool = True
    trusted_proxy_cidrs: tuple[str, ...] = ()

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

        production = os.environ.get("AINRF_PRODUCTION", "").lower() in ("1", "true", "yes")
        raw_cidrs = os.environ.get("AINRF_ALLOWED_CIDRS", "")
        allowed_cidrs = tuple(c.strip() for c in raw_cidrs.split(",") if c.strip())
        max_concurrent = int(os.environ.get("AINRF_MAX_CONCURRENT_REQUESTS", "0"))
        login_max_failures = int(os.environ.get("AINRF_LOGIN_MAX_FAILURES", "10"))
        login_lockout_hours = int(os.environ.get("AINRF_LOGIN_LOCKOUT_HOURS", "24"))
        metrics_enabled = os.environ.get("AINRF_METRICS_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        metrics_path = os.environ.get("AINRF_METRICS_PATH", "/metrics")
        slow_request_threshold = float(
            os.environ.get("AINRF_SLOW_REQUEST_THRESHOLD_SECONDS", "5.0")
        )
        public_registration_enabled = os.environ.get(
            "AINRF_PUBLIC_REGISTRATION_ENABLED", "true"
        ).lower() in ("1", "true", "yes")
        trusted_raw = os.environ.get("AINRF_TRUSTED_PROXY_CIDRS", "")
        trusted_proxy_cidrs = tuple(c.strip() for c in trusted_raw.split(",") if c.strip())
        return cls(
            api_key_hashes=api_key_hashes,
            state_root=resolved_state_root,
            container_config=container_config,
            startup_cwd=startup_cwd,
            production=production,
            allowed_cidrs=allowed_cidrs,
            max_concurrent_requests=max_concurrent,
            login_max_failures=login_max_failures,
            login_lockout_hours=login_lockout_hours,
            metrics_enabled=metrics_enabled,
            metrics_path=metrics_path,
            slow_request_threshold_seconds=slow_request_threshold,
            public_registration_enabled=public_registration_enabled,
            trusted_proxy_cidrs=trusted_proxy_cidrs,
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

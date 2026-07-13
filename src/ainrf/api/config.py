from __future__ import annotations

import json
import os
import pwd
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ainrf.execution import ContainerConfig
from ainrf.domain_control import DomainModelMode
from ainrf.runtime import parse_container_config_from_runtime_config
from ainrf.runtime.paths import RuntimePathConfig, build_runtime_path_config
from ainrf.state import default_state_root


def hash_api_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _env_value(name: str, legacy_name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    return os.environ.get(legacy_name, default)


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
    # Password and refresh-token authentication can be disabled for an
    # isolated state clone.  A staging-only API key remains available for
    # constrained read smoke checks, but copied password hashes/tokens never
    # become a new local authentication authority by accident.
    interactive_auth_enabled: bool = True
    trusted_proxy_cidrs: tuple[str, ...] = ()
    observability_enabled: bool = False
    observability_base_url: str = ""
    observability_secret_key: str = ""
    observability_public_key: str = ""
    auth_cookie_namespace: str = ""
    domain_model_mode: DomainModelMode = DomainModelMode.LEGACY
    # Disable automatic runtime observation/reconciliation for an isolated
    # clone without disabling authenticated API reads.  This is intentionally
    # separate from the domain model mode: legacy data may still be inspected
    # while the process is forbidden to initiate SSH/tmux work on startup.
    runtime_reconciliation_enabled: bool = True
    # Exact immutable artifact digest bound by the B7 cutover controller.  It
    # is intentionally absent in legacy/validate mode; a v2 process must
    # supply it and fail closed if it does not match the committed fuse.
    domain_artifact_sha: str | None = None

    @property
    def access_cookie_names(self) -> tuple[str, str]:
        suffix = f"_{self.auth_cookie_namespace}" if self.auth_cookie_namespace else ""
        return (
            f"openscience{suffix}_access_token",
            f"ainrf{suffix}_access_token",
        )

    @property
    def runtime_paths(self) -> RuntimePathConfig:
        return build_runtime_path_config(self.startup_cwd)

    @classmethod
    def from_env(cls, state_root: Path | None = None) -> ApiConfig:
        startup_cwd = Path.cwd().resolve()
        resolved_state_root = (
            state_root
            or Path(_env_value("OPENSCIENCE_STATE_ROOT", "AINRF_STATE_ROOT"))
            or default_state_root()
        )
        env_hashes = _env_value("OPENSCIENCE_API_KEY_HASHES", "AINRF_API_KEY_HASHES")
        api_key_hashes = _parse_api_key_hashes(env_hashes) if env_hashes else frozenset()

        payload: object | None = None
        config_path = resolved_state_root / "config.json"
        if config_path.exists():
            payload = json.loads(config_path.read_text(encoding="utf-8"))

        if not api_key_hashes:
            api_key_hashes = cls._parse_config_hashes(payload)

        if not api_key_hashes:
            raise ValueError("OpenScience API key hashes are not configured")

        try:
            container_config = ContainerConfig.from_env()
        except ValueError:
            container_config = parse_container_config_from_runtime_config(payload)

        production = _env_value("OPENSCIENCE_PRODUCTION", "AINRF_PRODUCTION").lower() in (
            "1",
            "true",
            "yes",
        )
        raw_cidrs = _env_value("OPENSCIENCE_ALLOWED_CIDRS", "AINRF_ALLOWED_CIDRS")
        allowed_cidrs = tuple(c.strip() for c in raw_cidrs.split(",") if c.strip())
        max_concurrent = int(
            _env_value("OPENSCIENCE_MAX_CONCURRENT_REQUESTS", "AINRF_MAX_CONCURRENT_REQUESTS", "0")
        )
        login_max_failures = int(
            _env_value("OPENSCIENCE_LOGIN_MAX_FAILURES", "AINRF_LOGIN_MAX_FAILURES", "10")
        )
        login_lockout_hours = int(
            _env_value("OPENSCIENCE_LOGIN_LOCKOUT_HOURS", "AINRF_LOGIN_LOCKOUT_HOURS", "24")
        )
        metrics_enabled = _env_value(
            "OPENSCIENCE_METRICS_ENABLED", "AINRF_METRICS_ENABLED"
        ).lower() in (
            "1",
            "true",
            "yes",
        )
        metrics_path = _env_value("OPENSCIENCE_METRICS_PATH", "AINRF_METRICS_PATH", "/metrics")
        slow_request_threshold = float(
            _env_value(
                "OPENSCIENCE_SLOW_REQUEST_THRESHOLD_SECONDS",
                "AINRF_SLOW_REQUEST_THRESHOLD_SECONDS",
                "5.0",
            )
        )
        public_registration_enabled = _env_value(
            "OPENSCIENCE_PUBLIC_REGISTRATION_ENABLED",
            "AINRF_PUBLIC_REGISTRATION_ENABLED",
            "true",
        ).lower() in ("1", "true", "yes")
        interactive_auth_enabled = _env_value(
            "OPENSCIENCE_INTERACTIVE_AUTH_ENABLED",
            "AINRF_INTERACTIVE_AUTH_ENABLED",
            "true",
        ).lower() in ("1", "true", "yes")
        trusted_raw = _env_value("OPENSCIENCE_TRUSTED_PROXY_CIDRS", "AINRF_TRUSTED_PROXY_CIDRS")
        trusted_proxy_cidrs = tuple(c.strip() for c in trusted_raw.split(",") if c.strip())
        observability_enabled = _env_value(
            "OPENSCIENCE_OBSERVABILITY_ENABLED", "AINRF_OBSERVABILITY_ENABLED"
        ).lower() in (
            "1",
            "true",
            "yes",
        )
        observability_base_url = _env_value(
            "OPENSCIENCE_OBSERVABILITY_BASE_URL", "AINRF_OBSERVABILITY_BASE_URL"
        )
        observability_secret_key = _env_value(
            "OPENSCIENCE_OBSERVABILITY_SECRET_KEY", "AINRF_OBSERVABILITY_SECRET_KEY"
        )
        observability_public_key = _env_value(
            "OPENSCIENCE_OBSERVABILITY_PUBLIC_KEY", "AINRF_OBSERVABILITY_PUBLIC_KEY"
        )
        auth_cookie_namespace = _env_value(
            "OPENSCIENCE_AUTH_COOKIE_NAMESPACE", "AINRF_AUTH_COOKIE_NAMESPACE"
        ).strip()
        raw_domain_model_mode = _env_value(
            "OPENSCIENCE_DOMAIN_MODEL_MODE", "AINRF_DOMAIN_MODEL_MODE", "legacy"
        ).lower()
        try:
            domain_model_mode = DomainModelMode(raw_domain_model_mode)
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in DomainModelMode)
            raise ValueError(f"OPENSCIENCE_DOMAIN_MODEL_MODE must be one of: {allowed}") from exc
        raw_domain_artifact_sha = _env_value(
            "OPENSCIENCE_DOMAIN_ARTIFACT_SHA", "AINRF_DOMAIN_ARTIFACT_SHA"
        ).strip()
        runtime_reconciliation_enabled = _env_value(
            "OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED",
            "AINRF_RUNTIME_RECONCILIATION_ENABLED",
            "true",
        ).lower() in ("1", "true", "yes")
        if (
            auth_cookie_namespace
            and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", auth_cookie_namespace) is None
        ):
            raise ValueError(
                "OpenScience auth cookie namespace must contain only lowercase "
                "letters, digits, underscores, or hyphens"
            )
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
            interactive_auth_enabled=interactive_auth_enabled,
            trusted_proxy_cidrs=trusted_proxy_cidrs,
            observability_enabled=observability_enabled,
            observability_base_url=observability_base_url,
            observability_secret_key=observability_secret_key,
            observability_public_key=observability_public_key,
            auth_cookie_namespace=auth_cookie_namespace,
            domain_model_mode=domain_model_mode,
            domain_artifact_sha=raw_domain_artifact_sha or None,
            runtime_reconciliation_enabled=runtime_reconciliation_enabled,
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

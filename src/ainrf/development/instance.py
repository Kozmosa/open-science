from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping


INSTANCE_SCHEMA_VERSION = 2
DEFAULT_DEVELOPMENT_ROOT = Path("/tmp/openscience-dev")
_PORT_BASE = 41000
_PORT_SLOT_COUNT = 1000
_PROFILE_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


@dataclass(frozen=True, slots=True)
class FrontendDevPorts:
    frontend: int
    api: int
    cdp: int


@dataclass(frozen=True, slots=True)
class FrontendDevInstance:
    schema_version: int
    instance_id: str
    repo_root: Path
    branch: str
    head: str
    profile: str
    bind_host: str
    ports: FrontendDevPorts
    instance_root: Path
    state_root: Path
    runtime_root: Path
    log_root: Path
    marker_path: Path
    credential_path: Path
    login_credentials_path: Path

    def as_public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["repo_root"] = str(self.repo_root)
        payload["instance_root"] = str(self.instance_root)
        payload["state_root"] = str(self.state_root)
        payload["runtime_root"] = str(self.runtime_root)
        payload["log_root"] = str(self.log_root)
        payload["marker_path"] = str(self.marker_path)
        payload["credential_path"] = str(self.credential_path)
        payload["login_credentials_path"] = str(self.login_credentials_path)
        return payload


def _git_value(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _resolve_git_identity(repo_root: Path) -> tuple[str, str]:
    head = _git_value(repo_root, "rev-parse", "HEAD")
    branch = _git_value(repo_root, "branch", "--show-current")
    if not branch:
        branch = f"detached-{head[:8]}"
    return branch, head


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:32] or "worktree"


def _validate_profile(profile: str) -> str:
    normalized = profile.strip().lower()
    if _PROFILE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("development profile must match [a-z0-9][a-z0-9-]{0,31}")
    return normalized


def _validate_port(name: str, value: int) -> int:
    if not 1024 <= value <= 65535:
        raise ValueError(f"{name} must be between 1024 and 65535")
    return value


def _port_from_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    return _validate_port(name, parsed)


def _assert_outside_git_worktree(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        marker = ancestor / ".git"
        if marker.is_file() or (marker / "HEAD").is_file():
            raise ValueError("development runtime root must live outside every Git worktree")
    return resolved


def resolve_frontend_dev_instance(
    repo_root: Path,
    *,
    profile: str = "full",
    env: Mapping[str, str] | None = None,
) -> FrontendDevInstance:
    resolved_repo_root = repo_root.expanduser().resolve()
    environment = os.environ if env is None else env
    normalized_profile = _validate_profile(profile)
    branch, head = _resolve_git_identity(resolved_repo_root)
    identity = f"{resolved_repo_root}\0{branch}\0{normalized_profile}"
    digest = sha256(identity.encode("utf-8")).hexdigest()
    slot = int(digest[:8], 16) % _PORT_SLOT_COUNT
    default_frontend_port = _PORT_BASE + slot * 3
    ports = FrontendDevPorts(
        frontend=_port_from_env(
            environment,
            "OPENSCIENCE_DEV_FRONTEND_PORT",
            default_frontend_port,
        ),
        api=_port_from_env(
            environment,
            "OPENSCIENCE_DEV_API_PORT",
            default_frontend_port + 1,
        ),
        cdp=_port_from_env(
            environment,
            "OPENSCIENCE_DEV_CDP_PORT",
            default_frontend_port + 2,
        ),
    )
    if len({ports.frontend, ports.api, ports.cdp}) != 3:
        raise ValueError("development frontend, API, and CDP ports must be distinct")

    root_value = environment.get("OPENSCIENCE_DEV_ROOT", "").strip()
    development_root = _assert_outside_git_worktree(
        Path(root_value) if root_value else DEFAULT_DEVELOPMENT_ROOT
    )
    instance_id = f"{_slug(branch)}-{normalized_profile}-{digest[:8]}"
    instance_root = development_root / instance_id
    runtime_root = instance_root / "runtime"
    bind_host = environment.get("OPENSCIENCE_DEV_BIND_HOST", "127.0.0.1").strip()
    if not bind_host:
        raise ValueError("OPENSCIENCE_DEV_BIND_HOST must not be empty")
    return FrontendDevInstance(
        schema_version=INSTANCE_SCHEMA_VERSION,
        instance_id=instance_id,
        repo_root=resolved_repo_root,
        branch=branch,
        head=head,
        profile=normalized_profile,
        bind_host=bind_host,
        ports=ports,
        instance_root=instance_root,
        state_root=instance_root / "state",
        runtime_root=runtime_root,
        log_root=instance_root / "logs",
        marker_path=instance_root / ".openscience-dev-instance.json",
        credential_path=runtime_root / "api-key",
        login_credentials_path=runtime_root / "frontend-login-identities.json",
    )


def ensure_frontend_dev_instance(instance: FrontendDevInstance) -> str:
    instance.runtime_root.mkdir(parents=True, exist_ok=True)
    instance.log_root.mkdir(parents=True, exist_ok=True)
    if instance.credential_path.exists():
        api_key = instance.credential_path.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("development API key file is empty")
    else:
        api_key = secrets.token_urlsafe(32)
        descriptor = os.open(
            instance.credential_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{api_key}\n")
    instance.credential_path.chmod(0o600)
    _write_json_atomic(instance.marker_path, instance.as_public_dict())
    return api_key


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        f"{json.dumps(dict(payload), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)

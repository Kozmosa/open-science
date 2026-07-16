from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from http.client import HTTPException
from pathlib import Path
from typing import Mapping
from urllib.error import URLError
from urllib.request import urlopen

from ainrf.api.config import hash_api_key
from ainrf.development.instance import (
    FrontendDevInstance,
    ensure_frontend_dev_instance,
)
from ainrf.development.frontend_faults import (
    FrontendDevFaultProfile,
    normalize_frontend_dev_fault_profile,
)


STACK_MANIFEST_SCHEMA_VERSION = 1


class DevelopmentStackError(RuntimeError):
    pass


class DevelopmentStackMode(StrEnum):
    DEV = "dev"
    PREVIEW = "preview"


@dataclass(frozen=True, slots=True)
class DevelopmentProcessRecord:
    service: str
    pid: int
    start_time: str
    command: tuple[str, ...]
    log_path: str


@dataclass(frozen=True, slots=True)
class DevelopmentStackStatus:
    state: str
    payload: dict[str, object]


class DevelopmentStack:
    def __init__(
        self,
        instance: FrontendDevInstance,
        *,
        artifact_sha: str,
        mode: DevelopmentStackMode = DevelopmentStackMode.DEV,
        api_key: str | None = None,
        personal_state_root: Path | None = None,
        frontend_bind_host: str | None = None,
        fault_profile: FrontendDevFaultProfile | str = FrontendDevFaultProfile.NONE,
    ) -> None:
        self.instance = instance
        self.artifact_sha = artifact_sha
        self.mode = mode
        self.personal_state_root = (
            personal_state_root.expanduser().resolve() if personal_state_root is not None else None
        )
        self.frontend_bind_host = frontend_bind_host or instance.bind_host
        self.fault_profile = normalize_frontend_dev_fault_profile(fault_profile)
        if self.is_personal and self.fault_profile is not FrontendDevFaultProfile.NONE:
            raise ValueError("frontend fault profiles are forbidden for personal state roots")
        self.api_key = api_key or ensure_frontend_dev_instance(instance)
        self.manifest_path = instance.runtime_root / "stack.json"

    @property
    def state_root(self) -> Path:
        return self.personal_state_root or self.instance.state_root

    @property
    def is_personal(self) -> bool:
        return self.personal_state_root is not None

    def prepare(self) -> dict[str, object]:
        ensure_frontend_dev_instance(self.instance)
        if self.is_personal:
            self.state_root.mkdir(parents=True, exist_ok=True)
            return {
                "state_root": str(self.state_root),
                "profile": "personal",
                "fixture": False,
            }
        command = [
            "uv",
            "run",
            "openscience",
            "frontend-dev",
            "prepare",
            "--state-root",
            str(self.state_root),
            "--api-key",
            self.api_key,
            "--credentials-path",
            str(self.instance.login_credentials_path),
            "--artifact-sha",
            self.artifact_sha,
            "--profile",
            self.instance.profile,
            "--fault-profile",
            self.fault_profile.value,
        ]
        result = subprocess.run(
            command,
            cwd=self.instance.repo_root,
            env=self.environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "fixture preparation failed"
            raise DevelopmentStackError(detail)
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise DevelopmentStackError("frontend fixture prepare returned malformed JSON")
        return {str(key): value for key, value in payload.items()}

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "OPENSCIENCE_STATE_ROOT": str(self.state_root),
                "OPENSCIENCE_JWT_SECRET": f"development-{self.instance.instance_id}",
                "OPENSCIENCE_WEBUI_API_KEY": self.api_key,
                "OPENSCIENCE_API_KEY_HASHES": hash_api_key(self.api_key),
                "AINRF_API_KEY_HASHES": hash_api_key(self.api_key),
                "OPENSCIENCE_AUTH_COOKIE_NAMESPACE": f"dev-{self.instance.instance_id[-8:]}",
                "OPENSCIENCE_WEBUI_BACKEND_TARGET": (
                    f"http://{self._api_probe_host()}:{self.instance.ports.api}"
                ),
                "OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED": "false",
                "OPENSCIENCE_FRONTEND_DEV_FAULT_PROFILE": self.fault_profile.value,
                "UV_CACHE_DIR": environment.get("UV_CACHE_DIR", "/tmp/uv-cache"),
            }
        )
        environment.pop("VITE_OPENSCIENCE_API_KEY", None)
        environment.pop("VITE_AINRF_API_KEY", None)
        if not self.is_personal:
            environment.update(
                {
                    "OPENSCIENCE_DOMAIN_MODEL_MODE": "v2",
                    "OPENSCIENCE_DOMAIN_ARTIFACT_SHA": self.artifact_sha,
                }
            )
        return environment

    def up(self) -> DevelopmentStackStatus:
        current = self.status()
        if current.state == "healthy":
            return current
        if self.manifest_path.exists():
            self.down()
        self._assert_ports_available()
        self.prepare()
        if self.mode is DevelopmentStackMode.PREVIEW:
            self._build_frontend_preview()
        else:
            self._write_frontend_dev_build_info()
        records: list[DevelopmentProcessRecord] = []
        try:
            records.append(
                self._start_process(
                    "api",
                    self._api_command(),
                )
            )
            self._write_manifest(records)
            self._wait_http(
                f"http://{self._api_probe_host()}:{self.instance.ports.api}/health",
                records[-1],
            )
            if not self.is_personal:
                records.append(
                    self._start_process(
                        "worker",
                        (
                            "uv",
                            "run",
                            "openscience",
                            "frontend-dev",
                            "worker",
                            "--state-root",
                            str(self.state_root),
                            "--artifact-sha",
                            self.artifact_sha,
                        ),
                    )
                )
                self._write_manifest(records)
                time.sleep(0.5)
                if not _record_is_alive(records[-1]):
                    raise DevelopmentStackError("domain worker exited during startup")
            frontend_script = "dev" if self.mode is DevelopmentStackMode.DEV else "preview"
            records.append(
                self._start_process(
                    "frontend",
                    (
                        "npm",
                        "--prefix",
                        str(self.instance.repo_root / "frontend"),
                        "run",
                        frontend_script,
                        "--",
                        "--host",
                        self.frontend_bind_host,
                        "--port",
                        str(self.instance.ports.frontend),
                        "--strictPort",
                    ),
                )
            )
            self._write_manifest(records)
            self._wait_http(
                f"http://{self._frontend_probe_host()}:{self.instance.ports.frontend}/",
                records[-1],
            )
        except Exception:
            self._stop_records(records)
            self.manifest_path.unlink(missing_ok=True)
            raise
        return self.status()

    def smoke(self) -> dict[str, object]:
        status = self.status()
        if status.state != "healthy":
            raise DevelopmentStackError("development stack must be healthy before smoke")
        frontend_base = f"http://{self._frontend_probe_host()}:{self.instance.ports.frontend}"
        checks: dict[str, object] = {}
        index = _fetch_http_text(f"{frontend_base}/")
        if '<div id="root"></div>' not in index:
            raise DevelopmentStackError("Vite index does not contain the React root")
        checks["frontend_index"] = True
        asset_match = re.search(r'<script[^>]+src="([^"]+)"', index)
        if asset_match is not None:
            asset_path = asset_match.group(1)
            _fetch_http_text(f"{frontend_base}{asset_path}")
            checks["frontend_asset"] = asset_path
        proxy_health = _fetch_http_json(f"{frontend_base}/api/health")
        checks["proxy_health"] = proxy_health.get("status") or "ok"
        capabilities = _fetch_http_json(f"{frontend_base}/api/domain/capabilities")
        if capabilities.get("domain_contract_version") != 2:
            raise DevelopmentStackError("development capabilities did not expose contract v2")
        checks["capabilities"] = {
            "domain_contract_version": capabilities.get("domain_contract_version"),
            "mode": capabilities.get("mode"),
        }
        projects = _fetch_http_json(f"{frontend_base}/api/domain/projects")
        workspaces = _fetch_http_json(f"{frontend_base}/api/domain/workspaces")
        project_items = projects.get("items")
        workspace_items = workspaces.get("items")
        if not isinstance(project_items, list) or not isinstance(workspace_items, list):
            raise DevelopmentStackError("domain projection smoke returned malformed lists")
        checks["projects"] = len(project_items)
        checks["workspaces"] = len(workspace_items)
        return {
            "instance_id": self.instance.instance_id,
            "profile": self.instance.profile,
            "mode": self.mode.value,
            "frontend_url": frontend_base,
            "checks": checks,
        }

    def down(self) -> DevelopmentStackStatus:
        records = self._load_records()
        self._stop_records(records)
        self.manifest_path.unlink(missing_ok=True)
        return self.status()

    def reset(self) -> dict[str, object]:
        if self.is_personal:
            raise DevelopmentStackError("reset is forbidden for personal state roots")
        self.down()
        if self.instance.instance_root.exists():
            self._assert_managed_instance_marker()
            shutil.rmtree(self.instance.instance_root)
        self.api_key = ensure_frontend_dev_instance(self.instance)
        return self.prepare()

    def status(self) -> DevelopmentStackStatus:
        records = self._load_records()
        service_payload: dict[str, object] = {}
        alive_by_service: dict[str, bool] = {}
        for record in records:
            alive = _record_is_alive(record)
            alive_by_service[record.service] = alive
            service_payload[record.service] = {
                "pid": record.pid,
                "alive": alive,
                "log_path": record.log_path,
            }
        expected = {"api", "frontend"} | (set() if self.is_personal else {"worker"})
        present = set(service_payload)
        api_healthy = _http_healthy(
            f"http://{self._api_probe_host()}:{self.instance.ports.api}/health"
        )
        frontend_healthy = _http_healthy(
            f"http://{self._frontend_probe_host()}:{self.instance.ports.frontend}/"
        )
        alive = all(alive_by_service[name] for name in expected & present)
        manifest_mode = self._manifest_mode()
        mode_matches = manifest_mode in {None, self.mode.value}
        manifest_fault_profile = self._manifest_fault_profile()
        fault_profile_matches = manifest_fault_profile in {None, self.fault_profile.value}
        if not records:
            state = "stopped"
        elif (
            present == expected
            and alive
            and api_healthy
            and frontend_healthy
            and mode_matches
            and fault_profile_matches
        ):
            state = "healthy"
        else:
            state = "degraded"
        payload: dict[str, object] = {
            "schema_version": STACK_MANIFEST_SCHEMA_VERSION,
            "state": state,
            "instance_id": self.instance.instance_id,
            "profile": "personal" if self.is_personal else self.instance.profile,
            "mode": manifest_mode or self.mode.value,
            "requested_mode": self.mode.value,
            "fault_profile": manifest_fault_profile or self.fault_profile.value,
            "requested_fault_profile": self.fault_profile.value,
            "source": {
                "branch": self.instance.branch,
                "head": self.instance.head,
                "repo_root": str(self.instance.repo_root),
            },
            "urls": {
                "frontend": (
                    f"http://{self._frontend_probe_host()}:{self.instance.ports.frontend}"
                ),
                "api": f"http://{self._api_probe_host()}:{self.instance.ports.api}",
            },
            "paths": {
                "state_root": str(self.state_root),
                "runtime_root": str(self.instance.runtime_root),
                "log_root": str(self.instance.log_root),
            },
            "services": service_payload,
        }
        return DevelopmentStackStatus(state=state, payload=payload)

    def log_paths(self, service: str) -> list[Path]:
        valid = {"api", "worker", "frontend", "all"}
        if service not in valid:
            raise DevelopmentStackError(f"unknown development service: {service}")
        services = ["api", "worker", "frontend"] if service == "all" else [service]
        return [self.instance.log_root / f"{name}.log" for name in services]

    def _start_process(
        self,
        service: str,
        command: tuple[str, ...],
    ) -> DevelopmentProcessRecord:
        log_path = self.instance.log_root / f"{service}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as handle:
            process = subprocess.Popen(
                command,
                cwd=self.instance.repo_root,
                env=self.environment(),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return DevelopmentProcessRecord(
            service=service,
            pid=process.pid,
            start_time=_process_start_time(process.pid),
            command=command,
            log_path=str(log_path),
        )

    def _api_command(self) -> tuple[str, ...]:
        if self.mode is DevelopmentStackMode.DEV:
            return (
                "uv",
                "run",
                "uvicorn",
                "ainrf.server:create_development_app",
                "--factory",
                "--host",
                self.instance.bind_host,
                "--port",
                str(self.instance.ports.api),
                "--reload",
                "--reload-dir",
                str(self.instance.repo_root / "src" / "ainrf"),
                "--ws-ping-interval",
                "10",
                "--ws-ping-timeout",
                "30",
            )
        return (
            "uv",
            "run",
            "openscience",
            "serve",
            "--host",
            self.instance.bind_host,
            "--port",
            str(self.instance.ports.api),
            "--state-root",
            str(self.state_root),
        )

    def _build_frontend_preview(self) -> None:
        log_path = self.instance.log_root / "frontend-build.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("wb") as handle:
            result = subprocess.run(
                (
                    "npm",
                    "--prefix",
                    str(self.instance.repo_root / "frontend"),
                    "run",
                    "build",
                ),
                cwd=self.instance.repo_root,
                env=self.environment(),
                check=False,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        if result.returncode != 0:
            raise DevelopmentStackError(f"frontend preview build failed; inspect {log_path}")

    def _write_frontend_dev_build_info(self) -> None:
        log_path = self.instance.log_root / "frontend-build-info.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("wb") as handle:
            result = subprocess.run(
                (
                    "node",
                    str(self.instance.repo_root / "frontend" / "scripts" / "write-build-info.mjs"),
                ),
                cwd=self.instance.repo_root,
                env=self.environment(),
                check=False,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        if result.returncode != 0:
            raise DevelopmentStackError(f"frontend dev build metadata failed; inspect {log_path}")

    def _write_manifest(self, records: list[DevelopmentProcessRecord]) -> None:
        payload = {
            "schema_version": STACK_MANIFEST_SCHEMA_VERSION,
            "instance_id": self.instance.instance_id,
            "profile": "personal" if self.is_personal else self.instance.profile,
            "mode": self.mode.value,
            "fault_profile": self.fault_profile.value,
            "processes": [asdict(record) for record in records],
        }
        _write_json_atomic(self.manifest_path, payload)

    def _load_records(self) -> list[DevelopmentProcessRecord]:
        if not self.manifest_path.is_file():
            return []
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != STACK_MANIFEST_SCHEMA_VERSION:
            raise DevelopmentStackError("development stack manifest version is unsupported")
        if payload.get("instance_id") != self.instance.instance_id:
            raise DevelopmentStackError("development stack manifest belongs to another instance")
        processes = payload.get("processes")
        if not isinstance(processes, list):
            raise DevelopmentStackError("development stack manifest is malformed")
        records: list[DevelopmentProcessRecord] = []
        for item in processes:
            if not isinstance(item, dict):
                raise DevelopmentStackError("development process record is malformed")
            command = item.get("command")
            if not isinstance(command, list) or not all(
                isinstance(value, str) for value in command
            ):
                raise DevelopmentStackError("development process command is malformed")
            records.append(
                DevelopmentProcessRecord(
                    service=str(item["service"]),
                    pid=int(item["pid"]),
                    start_time=str(item["start_time"]),
                    command=tuple(command),
                    log_path=str(item["log_path"]),
                )
            )
        return records

    def _manifest_mode(self) -> str | None:
        if not self.manifest_path.is_file():
            return None
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        mode = payload.get("mode")
        return str(mode) if mode is not None else None

    def _manifest_fault_profile(self) -> str | None:
        if not self.manifest_path.is_file():
            return None
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        value = payload.get("fault_profile")
        return str(value) if value is not None else None

    def _stop_records(self, records: list[DevelopmentProcessRecord]) -> None:
        owned = [record for record in reversed(records) if _record_is_alive(record)]
        for record in owned:
            try:
                os.killpg(os.getpgid(record.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5.0
        while owned and time.monotonic() < deadline:
            owned = [record for record in owned if _record_is_alive(record)]
            if owned:
                time.sleep(0.05)
        for record in owned:
            try:
                os.killpg(os.getpgid(record.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _wait_http(
        self,
        url: str,
        record: DevelopmentProcessRecord,
        timeout_seconds: float = 30.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _http_healthy(url):
                return
            if not _record_is_alive(record):
                raise DevelopmentStackError(f"{record.service} exited before becoming healthy")
            time.sleep(0.2)
        raise DevelopmentStackError(f"timed out waiting for {record.service}: {url}")

    def _assert_ports_available(self) -> None:
        for name, port in (
            ("frontend", self.instance.ports.frontend),
            ("api", self.instance.ports.api),
        ):
            host = self.frontend_bind_host if name == "frontend" else self.instance.bind_host
            if not _port_available(host, port):
                raise DevelopmentStackError(
                    f"{name} port {port} is already in use by an unowned process; "
                    f"set OPENSCIENCE_DEV_{name.upper()}_PORT to override"
                )

    def _frontend_probe_host(self) -> str:
        return "127.0.0.1" if self.frontend_bind_host == "0.0.0.0" else self.frontend_bind_host

    def _api_probe_host(self) -> str:
        return "127.0.0.1" if self.instance.bind_host == "0.0.0.0" else self.instance.bind_host

    def _assert_managed_instance_marker(self) -> None:
        marker_path = self.instance.marker_path
        if not marker_path.is_file():
            raise DevelopmentStackError("refusing reset without a managed instance marker")
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        if payload.get("instance_id") != self.instance.instance_id:
            raise DevelopmentStackError("refusing reset for a marker owned by another instance")


def _process_start_time(pid: int) -> str:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError) as exc:
        raise DevelopmentStackError(f"cannot inspect development process {pid}") from exc
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split()
    if closing < 0 or len(fields) <= 19:
        raise DevelopmentStackError(f"cannot parse development process {pid}")
    return fields[19]


def _record_is_alive(record: DevelopmentProcessRecord) -> bool:
    try:
        os.kill(record.pid, 0)
        return _process_start_time(record.pid) == record.start_time
    except (ProcessLookupError, PermissionError, DevelopmentStackError):
        return False


def _port_available(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((probe_host, port))
        except OSError:
            return False
    return True


def _http_healthy(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            return 200 <= response.status < 500
    except (OSError, URLError, HTTPException):
        return False


def _fetch_http_text(url: str) -> str:
    try:
        with urlopen(url, timeout=2.0) as response:
            if not 200 <= response.status < 300:
                raise DevelopmentStackError(f"HTTP smoke failed for {url}: {response.status}")
            return response.read().decode("utf-8")
    except (OSError, URLError, HTTPException) as exc:
        raise DevelopmentStackError(f"HTTP smoke failed for {url}: {exc}") from exc


def _fetch_http_json(url: str) -> dict[str, object]:
    try:
        payload = json.loads(_fetch_http_text(url))
    except json.JSONDecodeError as exc:
        raise DevelopmentStackError(f"HTTP smoke returned invalid JSON for {url}") from exc
    if not isinstance(payload, dict):
        raise DevelopmentStackError(f"HTTP smoke returned a non-object for {url}")
    return {str(key): value for key, value in payload.items()}


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        f"{json.dumps(dict(payload), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    temporary.replace(path)

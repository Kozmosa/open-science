from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Mapping
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from ainrf.development.instance import FrontendDevInstance


@dataclass(frozen=True, slots=True)
class DevelopmentDoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class BrowserCdpProbe:
    ok: bool
    browser: str
    browser_version: str | None
    protocol_version: str | None
    websocket_debugger_url: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class DevelopmentDoctorResult:
    ok: bool
    instance_id: str
    checks: tuple[DevelopmentDoctorCheck, ...]
    browser_probe: BrowserCdpProbe | None
    session_restart_required: bool
    session_tool_visibility: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_chrome(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path | None, list[str]]:
    environment = os.environ if env is None else env
    resolved_home = (home or Path.home()).expanduser().resolve()
    rejected: list[str] = []
    candidates: list[Path] = []
    explicit = environment.get("PUPPETEER_EXECUTABLE_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    path_value = environment.get("PATH")
    for command in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(command, path=path_value)
        if found:
            candidates.append(Path(found))
    candidates.extend(
        sorted(
            resolved_home.glob(".cache/puppeteer/chrome/linux-*/chrome-linux64/chrome"),
            reverse=True,
        )
    )
    seen: set[Path] = set()
    for candidate in candidates:
        expanded = candidate.expanduser()
        if _is_snap_chromium(expanded):
            rejected.append(f"rejected broken snap Chromium: {expanded}")
            continue
        resolved = expanded.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_snap_chromium(resolved):
            rejected.append(f"rejected broken snap Chromium: {resolved}")
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved, rejected
        rejected.append(f"Chrome candidate is not executable: {resolved}")
    return None, rejected


def discover_chrome_devtools_mcp(
    *, env: Mapping[str, str] | None = None
) -> tuple[str | None, list[str]]:
    environment = os.environ if env is None else env
    path_value = environment.get("PATH")
    command = shutil.which("chrome-devtools-mcp", path=path_value)
    if command:
        return command, []
    npx = shutil.which("npx", path=path_value)
    if npx:
        return npx, ["chrome-devtools-mcp is not directly on PATH; npx is available"]
    return None, ["neither chrome-devtools-mcp nor npx is available"]


def chrome_devtools_config_locations(home: Path | None = None) -> list[Path]:
    resolved_home = (home or Path.home()).expanduser().resolve()
    return [
        resolved_home / ".claude" / "settings.json",
        resolved_home / ".omp" / "agent" / "mcp.json",
    ]


def configured_chrome_devtools_servers(home: Path | None = None) -> list[str]:
    configured: list[str] = []
    for path in chrome_devtools_config_locations(home):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        if any("chrome-devtools" in str(name) for name in servers):
            configured.append(str(path))
    return configured


def probe_chrome_cdp(
    chrome_path: Path,
    *,
    port: int,
    runtime_root: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> BrowserCdpProbe:
    environment = os.environ.copy()
    if env is not None:
        environment.update(env)
    runtime_root.mkdir(parents=True, exist_ok=True)
    user_data_dir = runtime_root / f"chrome-preflight-{uuid4().hex}"
    log_path = runtime_root / "browser-preflight.log"
    extra_args = shlex.split(environment.get("OPENSCIENCE_DEV_CHROME_ARGS", ""))
    command = [
        str(chrome_path),
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *extra_args,
        "about:blank",
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        with log_path.open("wb") as handle:
            process = subprocess.Popen(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = _read_cdp_version(port)
            if payload is not None:
                return BrowserCdpProbe(
                    ok=True,
                    browser=str(chrome_path),
                    browser_version=_optional_string(payload.get("Browser")),
                    protocol_version=_optional_string(payload.get("Protocol-Version")),
                    websocket_debugger_url=_optional_string(payload.get("webSocketDebuggerUrl")),
                    detail=f"CDP responded on 127.0.0.1:{port}",
                )
            if process.poll() is not None:
                return BrowserCdpProbe(
                    ok=False,
                    browser=str(chrome_path),
                    browser_version=None,
                    protocol_version=None,
                    websocket_debugger_url=None,
                    detail=_browser_failure_detail(log_path, "Chrome exited before CDP was ready"),
                )
            time.sleep(0.1)
        return BrowserCdpProbe(
            ok=False,
            browser=str(chrome_path),
            browser_version=None,
            protocol_version=None,
            websocket_debugger_url=None,
            detail=_browser_failure_detail(
                log_path,
                "Chrome CDP startup timed out; sandbox overrides are never added automatically",
            ),
        )
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        shutil.rmtree(user_data_dir, ignore_errors=True)


def run_development_doctor(
    instance: FrontendDevInstance,
    *,
    include_browser: bool,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> DevelopmentDoctorResult:
    environment = os.environ if env is None else env
    checks: list[DevelopmentDoctorCheck] = []
    for command in ("uv", "node", "npm", "curl"):
        resolved = shutil.which(command, path=environment.get("PATH"))
        checks.append(
            DevelopmentDoctorCheck(
                name=f"command:{command}",
                ok=resolved is not None,
                detail=resolved or f"{command} is not available on PATH",
            )
        )
    vite = instance.repo_root / "frontend" / "node_modules" / ".bin" / "vite"
    checks.append(
        DevelopmentDoctorCheck(
            name="frontend:dependencies",
            ok=vite.is_file() and os.access(vite, os.X_OK),
            detail=str(vite) if vite.exists() else "run npm --prefix frontend ci",
        )
    )
    try:
        instance.runtime_root.mkdir(parents=True, exist_ok=True)
        writable = os.access(instance.runtime_root, os.W_OK)
    except OSError:
        writable = False
    checks.append(
        DevelopmentDoctorCheck(
            name="runtime:writable",
            ok=writable,
            detail=str(instance.runtime_root),
        )
    )

    browser_probe: BrowserCdpProbe | None = None
    if include_browser:
        chrome_path, chrome_notes = discover_chrome(env=environment, home=home)
        checks.append(
            DevelopmentDoctorCheck(
                name="browser:chrome",
                ok=chrome_path is not None,
                detail=(
                    str(chrome_path) if chrome_path else "; ".join(chrome_notes) or "not found"
                ),
            )
        )
        mcp_command, mcp_notes = discover_chrome_devtools_mcp(env=environment)
        checks.append(
            DevelopmentDoctorCheck(
                name="browser:mcp-command",
                ok=mcp_command is not None,
                detail=(mcp_command if mcp_command else "; ".join(mcp_notes)),
            )
        )
        configured = configured_chrome_devtools_servers(home)
        checks.append(
            DevelopmentDoctorCheck(
                name="browser:mcp-config",
                ok=bool(configured),
                detail=", ".join(configured)
                if configured
                else "chrome-devtools MCP is not configured",
            )
        )
        if chrome_path is not None and not _port_available(instance.ports.cdp):
            browser_probe = BrowserCdpProbe(
                ok=False,
                browser=str(chrome_path),
                browser_version=None,
                protocol_version=None,
                websocket_debugger_url=None,
                detail=f"CDP port {instance.ports.cdp} is already in use",
            )
        elif chrome_path is not None:
            browser_probe = probe_chrome_cdp(
                chrome_path,
                port=instance.ports.cdp,
                runtime_root=instance.runtime_root,
                env=environment,
            )
        if browser_probe is not None:
            checks.append(
                DevelopmentDoctorCheck(
                    name="browser:cdp",
                    ok=browser_probe.ok,
                    detail=browser_probe.detail,
                )
            )
    return DevelopmentDoctorResult(
        ok=all(check.ok for check in checks),
        instance_id=instance.instance_id,
        checks=tuple(checks),
        browser_probe=browser_probe,
        session_restart_required=include_browser,
        session_tool_visibility=(
            "MCP configuration is loaded at session start; this process cannot prove that the "
            "current Codex session exposes browser tools"
        ),
    )


def _is_snap_chromium(path: Path) -> bool:
    value = str(path)
    return value == "/snap/bin/chromium" or "/snap/" in value


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _read_cdp_version(port: int) -> dict[str, object] | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, HTTPException, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _browser_failure_detail(log_path: Path, prefix: str) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    tail = " | ".join(lines[-3:])
    return f"{prefix}: {tail}" if tail else prefix

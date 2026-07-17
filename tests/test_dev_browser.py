from __future__ import annotations

import json
import signal
import stat
from pathlib import Path

import pytest

from ainrf.development import browser as browser_module
from ainrf.development import instance as instance_module
from ainrf.development.browser import (
    BrowserCdpProbe,
    configured_chrome_devtools_servers,
    discover_chrome,
    probe_chrome_cdp,
    run_development_doctor,
)
from ainrf.development.instance import FrontendDevInstance, resolve_frontend_dev_instance


pytestmark = [pytest.mark.cli]


class FakeChromeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0


def _write_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FrontendDevInstance:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    vite = repo_root / "frontend" / "node_modules" / ".bin" / "vite"
    _write_executable(vite)

    def fake_git_value(path: Path, *args: str) -> str:
        assert path == repo_root
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        if args == ("branch", "--show-current"):
            return "feat/frontend-phases"
        raise AssertionError(args)

    monkeypatch.setattr(instance_module, "_git_value", fake_git_value)
    return resolve_frontend_dev_instance(
        repo_root,
        env={"OPENSCIENCE_DEV_ROOT": str(tmp_path / "runtime")},
    )


def test_chrome_discovery_prefers_explicit_binary_and_rejects_snap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "chrome-for-testing"
    fallback = tmp_path / "google-chrome"
    _write_executable(explicit)
    _write_executable(fallback)

    selected, rejected = discover_chrome(
        env={"PUPPETEER_EXECUTABLE_PATH": str(explicit), "PATH": ""},
        home=tmp_path,
    )
    assert selected == explicit
    assert rejected == []

    def fake_which(command: str, path: str | None = None) -> str | None:
        del path
        if command == "chromium":
            return "/snap/bin/chromium"
        if command == "google-chrome":
            return str(fallback)
        return None

    monkeypatch.setattr(browser_module.shutil, "which", fake_which)
    selected, rejected = discover_chrome(env={"PATH": "/bin"}, home=tmp_path)
    assert selected == fallback
    assert any("broken snap Chromium" in note for note in rejected)


def test_chrome_devtools_config_discovery_reads_claude_and_omp(tmp_path: Path) -> None:
    claude = tmp_path / ".claude" / "settings.json"
    omp = tmp_path / ".omp" / "agent" / "mcp.json"
    claude.parent.mkdir(parents=True)
    omp.parent.mkdir(parents=True)
    claude.write_text(
        json.dumps({"mcpServers": {"chrome-devtools": {"command": "chrome-devtools-mcp"}}}),
        encoding="utf-8",
    )
    omp.write_text(
        json.dumps({"mcpServers": {"chrome-devtools-local": {"command": "npx"}}}),
        encoding="utf-8",
    )

    assert configured_chrome_devtools_servers(tmp_path) == [str(claude), str(omp)]


def test_cdp_probe_launches_isolated_profile_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chrome = tmp_path / "chrome"
    _write_executable(chrome)
    process = FakeChromeProcess()
    captured: dict[str, object] = {}
    signals: list[tuple[int, signal.Signals]] = []

    def fake_popen(command: list[str], **kwargs: object) -> FakeChromeProcess:
        captured["command"] = command
        captured.update(kwargs)
        return process

    monkeypatch.setattr(browser_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        browser_module,
        "_read_cdp_version",
        lambda port: {
            "Browser": "Chrome/149.0",
            "Protocol-Version": "1.3",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/test",
        },
    )
    monkeypatch.setattr(browser_module.os, "getpgid", lambda pid: pid + 1)
    monkeypatch.setattr(
        browser_module.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    result = probe_chrome_cdp(
        chrome,
        port=49222,
        runtime_root=tmp_path / "runtime",
        env={"OPENSCIENCE_DEV_CHROME_ARGS": "--disable-gpu"},
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--headless=new" in command
    assert "--remote-debugging-port=49222" in command
    assert "--disable-gpu" in command
    assert "--no-sandbox" not in command
    assert result.ok is True
    assert result.browser_version == "Chrome/149.0"
    assert signals == [(4322, signal.SIGTERM)]
    assert not any((tmp_path / "runtime").glob("chrome-preflight-*"))


def test_cdp_probe_timeout_is_non_destructive_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chrome = tmp_path / "chrome"
    _write_executable(chrome)
    process = FakeChromeProcess(pid=5000)
    signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(browser_module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(browser_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        browser_module.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    result = probe_chrome_cdp(
        chrome,
        port=49223,
        runtime_root=tmp_path / "runtime",
        timeout_seconds=0,
    )

    assert result.ok is False
    assert "timed out" in result.detail
    assert signals == [(5000, signal.SIGTERM)]
    assert not any((tmp_path / "runtime").glob("chrome-preflight-*"))


def test_development_doctor_reports_browser_and_session_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    chrome = tmp_path / "chrome"
    _write_executable(chrome)
    home = tmp_path / "home"
    config = home / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"mcpServers": {"chrome-devtools": {"command": "chrome-devtools-mcp"}}}),
        encoding="utf-8",
    )
    command_paths = {name: f"/usr/bin/{name}" for name in ("uv", "node", "npm", "curl")}

    def fake_which(command: str, path: str | None = None) -> str | None:
        del path
        if command == "chrome-devtools-mcp":
            return "/usr/bin/chrome-devtools-mcp"
        return command_paths.get(command)

    monkeypatch.setattr(browser_module.shutil, "which", fake_which)
    monkeypatch.setattr(browser_module, "discover_chrome", lambda **kwargs: (chrome, []))
    monkeypatch.setattr(browser_module, "_port_available", lambda port: True)
    monkeypatch.setattr(
        browser_module,
        "probe_chrome_cdp",
        lambda *args, **kwargs: BrowserCdpProbe(
            ok=True,
            browser=str(chrome),
            browser_version="Chrome/149.0",
            protocol_version="1.3",
            websocket_debugger_url="ws://127.0.0.1/devtools/browser/test",
            detail="CDP ready",
        ),
    )

    result = run_development_doctor(
        instance,
        include_browser=True,
        env={"PATH": "/usr/bin"},
        home=home,
    )

    assert result.ok is True
    assert result.browser_probe is not None and result.browser_probe.ok is True
    assert result.session_restart_required is True
    assert "cannot prove" in result.session_tool_visibility

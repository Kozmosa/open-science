from __future__ import annotations

from pathlib import Path
import signal
import sys

import pytest
from fastapi import FastAPI

from ainrf.api import ApiConfig
from ainrf.api.server import (
    _terminate_process,
    create_development_app,
    run_http_server,
    run_http_server_daemon,
    stop_http_server_daemon,
)

pytestmark = [pytest.mark.cli]


def test_create_development_app_uses_env_config_and_configures_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ApiConfig(api_key_hashes=frozenset({"hash"}), state_root=tmp_path)
    app = FastAPI()
    configured: list[Path] = []
    monkeypatch.setattr("ainrf.api.server.ApiConfig.from_env", lambda: config)
    monkeypatch.setattr("ainrf.api.server.configure_logging", configured.append)
    monkeypatch.setattr("ainrf.api.server.create_app", lambda value: app)

    result = create_development_app()

    assert result is app
    assert configured == [tmp_path]


def test_run_http_server_composes_app_and_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ApiConfig(api_key_hashes=frozenset({"hash"}), state_root=tmp_path)
    app = FastAPI()
    captured: dict[str, object] = {}
    monkeypatch.setattr("ainrf.api.server.ApiConfig.from_env", lambda state_root: config)
    monkeypatch.setattr("ainrf.api.server.configure_logging", lambda state_root: None)
    monkeypatch.setattr("ainrf.api.server.create_app", lambda value: app)
    monkeypatch.setattr(
        "ainrf.api.server.uvicorn.run",
        lambda application, **kwargs: captured.update(application=application, **kwargs),
    )

    run_http_server("127.0.0.1", 8765, tmp_path, workers=2)

    assert captured["application"] is app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert captured["workers"] == 2
    assert captured["factory"] is False
    assert captured["reload"] is False


def test_run_http_server_owns_reload_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr("ainrf.api.server.configure_logging", lambda state_root: None)
    monkeypatch.setattr(
        "ainrf.api.server.uvicorn.run",
        lambda application, **kwargs: captured.update(application=application, **kwargs),
    )

    run_http_server("127.0.0.1", 8765, tmp_path, reload=True)

    assert captured["application"] == "ainrf.api.server:create_development_app"
    assert captured["factory"] is True
    assert captured["reload"] is True
    assert captured["reload_dirs"]


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def test_run_server_daemon_writes_pid_and_uses_expected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(
        args: list[str],
        stdin: object,
        stdout: object,
        stderr: object,
        start_new_session: bool,
        text: bool,
    ) -> FakeProcess:
        captured["args"] = args
        captured["stdin"] = stdin
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["start_new_session"] = start_new_session
        captured["text"] = text
        return FakeProcess(9876)

    monkeypatch.setattr("ainrf.api.server.subprocess.Popen", fake_popen)
    monkeypatch.setattr("ainrf.api.server._wait_until_healthy", lambda host, port: True)

    pid_file = tmp_path / "runtime" / "ainrf-api.pid"
    log_file = tmp_path / "runtime" / "ainrf-api.log"
    pid = run_http_server_daemon("127.0.0.1", 8765, tmp_path, pid_file, log_file)

    assert pid == 9876
    assert pid_file.read_text(encoding="utf-8").strip() == "9876"
    assert log_file.exists()
    assert captured["args"] == [
        sys.executable,
        "-m",
        "ainrf",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--state-root",
        str(tmp_path),
    ]
    assert captured["start_new_session"] is True
    assert captured["text"] is True


def test_run_server_daemon_cleans_up_pid_file_on_failed_health_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ainrf.api.server.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(9876),
    )
    monkeypatch.setattr("ainrf.api.server._wait_until_healthy", lambda host, port: False)
    terminated: list[int] = []
    monkeypatch.setattr("ainrf.api.server._terminate_process", lambda pid: terminated.append(pid))

    pid_file = tmp_path / "runtime" / "ainrf-api.pid"
    log_file = tmp_path / "runtime" / "ainrf-api.log"

    with pytest.raises(RuntimeError):
        run_http_server_daemon("127.0.0.1", 8765, tmp_path, pid_file, log_file)

    assert terminated == [9876]
    assert not pid_file.exists()


def test_terminate_process_signals_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[tuple[int, int]] = []

    monkeypatch.setattr("ainrf.api.server.os.getpgid", lambda pid: 4321)
    monkeypatch.setattr(
        "ainrf.api.server.os.killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )
    monkeypatch.setattr("ainrf.api.server._process_exists", lambda pid: False)

    _terminate_process(9876)

    assert signals == [(4321, signal.SIGTERM)]


def test_stop_server_daemon_terminates_pid_and_removes_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "runtime" / "ainrf-api.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("9876\n", encoding="utf-8")
    terminated: list[int] = []

    monkeypatch.setattr("ainrf.api.server._process_exists", lambda pid: True)
    monkeypatch.setattr("ainrf.api.server._terminate_process", lambda pid: terminated.append(pid))

    assert stop_http_server_daemon(pid_file) is True
    assert terminated == [9876]
    assert not pid_file.exists()

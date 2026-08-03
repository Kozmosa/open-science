"""Disposable Gatus API and nginx subpath integration smoke."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Callable, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import pytest
import yaml

pytestmark = [pytest.mark.cli, pytest.mark.concurrent]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return cast(int, listener.getsockname()[1])


class _ProbeHandler(BaseHTTPRequestHandler):
    healthy = False

    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.healthy else 503
        body = b"OpenScience is healthy" if self.healthy else b"unavailable"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _probe_server() -> Iterator[tuple[int, type[_ProbeHandler]]]:
    handler = type("ProbeHandler", (_ProbeHandler,), {"healthy": False})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, handler
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _json(url: str) -> Any:
    with urlopen(url, timeout=3) as response:  # noqa: S310
        return json.load(response)


def _wait_json(url: str, predicate: Callable[[Any], bool], *, timeout: float = 20) -> Any:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = _json(url)
            if predicate(payload):
                return payload
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            error = exc
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {url}: {error}")


def _docker_image() -> str:
    candidates = (
        os.environ.get("OPENSCIENCE_GATUS_TEST_IMAGE"),
        "docker.1ms.run/twinproduction/gatus:v5.36.0",
        "ghcr.io/twin/gatus:v5.36.0",
    )
    for candidate in candidates:
        if candidate is None:
            continue
        result = subprocess.run(
            ["docker", "image", "inspect", candidate],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    pytest.skip("Gatus v5.36.0 image is not available locally")


def _status_entries(payload: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "success" in value:
                entries.append(cast(dict[str, Any], value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return entries


@pytest.mark.skipif(
    os.environ.get("OPENSCIENCE_RUN_DOCKER_INTEGRATION") != "1",
    reason="set OPENSCIENCE_RUN_DOCKER_INTEGRATION=1 for disposable Docker smoke",
)
def test_gatus_api_history_failure_recovery_and_nginx_subpath(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is unavailable")
    gatus_port = _free_port()
    nginx_port = _free_port()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.chmod(0o777)

    with _probe_server() as (probe_port, handler):
        config = {
            "metrics": True,
            "web": {"address": "127.0.0.1", "port": gatus_port},
            "storage": {"type": "sqlite", "path": "/data/gatus.db"},
            "ui": {"title": "OpenScience Status"},
            "endpoints": [
                {
                    "name": "Web App",
                    "group": "Development",
                    "url": f"http://127.0.0.1:{probe_port}/",
                    "interval": "1s",
                    "conditions": [
                        "[STATUS] == 200",
                        "[BODY] == pat(*OpenScience*)",
                    ],
                    "ui": {
                        "hide-url": True,
                        "hide-hostname": True,
                        "hide-errors": True,
                    },
                    "extra-labels": {
                        "environment": "development",
                        "component": "web",
                    },
                }
            ],
        }
        config_path = tmp_path / "gatus.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        nginx_path = tmp_path / "nginx.conf"
        nginx_path.write_text(
            """
events {}
http {
  server {
    listen 127.0.0.1:NGINX_PORT;
    location = /uptime { return 301 /uptime/; }
    location = /uptime/metrics { return 404; }
    location /uptime/ {
      proxy_pass http://127.0.0.1:GATUS_PORT/;
    }
  }
}
""".replace("NGINX_PORT", str(nginx_port)).replace("GATUS_PORT", str(gatus_port)),
            encoding="utf-8",
        )

        gatus_name = f"openscience-gatus-test-{os.getpid()}"
        nginx_name = f"openscience-nginx-test-{os.getpid()}"
        processes: list[str] = []
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    gatus_name,
                    "--network",
                    "host",
                    "-v",
                    f"{config_path}:/config/config.yaml:ro",
                    "-v",
                    f"{data_dir}:/data",
                    _docker_image(),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            processes.append(gatus_name)
            list_url = f"http://127.0.0.1:{gatus_port}/api/v1/endpoints/statuses"
            failed = _wait_json(
                list_url,
                lambda payload: any(
                    entry.get("success") is False for entry in _status_entries(payload)
                ),
            )
            entries = _status_entries(failed)
            assert entries
            endpoint_key = "development_web-app"

            handler.healthy = True
            recovered = _wait_json(
                list_url,
                lambda payload: any(
                    entry.get("success") is True for entry in _status_entries(payload)
                ),
            )
            assert any(entry.get("success") is True for entry in _status_entries(recovered))

            encoded_key = quote(endpoint_key, safe="")
            statuses = _json(
                f"http://127.0.0.1:{gatus_port}/api/v1/endpoints/{encoded_key}/statuses"
            )
            assert isinstance(_status_entries(statuses), list)
            uptime = _json(
                f"http://127.0.0.1:{gatus_port}/api/v1/endpoints/{encoded_key}/uptimes/24h"
            )
            assert isinstance(uptime, (dict, int, float))
            history = _json(
                f"http://127.0.0.1:{gatus_port}/api/v1/endpoints/{encoded_key}/response-times/24h/history"
            )
            assert isinstance(history, (dict, list))

            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    nginx_name,
                    "--network",
                    "host",
                    "-v",
                    f"{nginx_path}:/etc/nginx/nginx.conf:ro",
                    "docker.1ms.run/nginx:1.27-alpine",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            processes.append(nginx_name)
            proxied = _wait_json(
                f"http://127.0.0.1:{nginx_port}/uptime/api/v1/endpoints/statuses",
                lambda payload: bool(_status_entries(payload)),
            )
            assert _status_entries(proxied)
            with pytest.raises(HTTPError) as exc_info:
                urlopen(f"http://127.0.0.1:{nginx_port}/uptime/metrics", timeout=3)  # noqa: S310
            assert exc_info.value.code == 404
        finally:
            for name in reversed(processes):
                subprocess.run(
                    ["docker", "stop", "--time", "1", name],
                    check=False,
                    capture_output=True,
                    text=True,
                )

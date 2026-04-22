from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.terminal.models import TerminalAttachmentTarget
from ainrf.terminal.pty import (
    TERMINAL_LOCAL_TARGET_KIND,
    TerminalBridgeRuntime,
    build_attachment_ws_url,
    start_terminal_bridge,
    stop_terminal_bridge,
)


class DummyProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.pid = 4321
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float) -> int:
        _ = timeout
        self.returncode = 0
        return 0


def make_client(tmp_path: Path) -> tuple[TestClient, FastAPI]:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
        )
    )
    return TestClient(app), app


def test_build_attachment_ws_url_translates_http_base() -> None:
    assert build_attachment_ws_url("http://testserver", "attach-1", "token-1") == (
        "ws://testserver/terminal/attachments/attach-1/ws?token=token-1"
    )


def test_start_terminal_bridge_launches_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class PopenProcess:
        pid = 4321

    def fake_popen(*args: object, **kwargs: object) -> PopenProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return PopenProcess()

    monkeypatch.setattr("ainrf.terminal.pty.os.openpty", lambda: (11, 12))
    monkeypatch.setattr("ainrf.terminal.pty.subprocess.Popen", fake_popen)

    runtime = start_terminal_bridge(("/bin/sh",), tmp_path)

    assert captured["args"] == (["/bin/sh"],)
    assert captured["kwargs"] == {
        "stdin": 12,
        "stdout": 12,
        "stderr": 12,
        "cwd": tmp_path.resolve(),
        "start_new_session": True,
        "text": False,
        "close_fds": True,
    }
    assert runtime.process.pid == 4321
    assert runtime.master_fd == 11


def test_stop_terminal_bridge_terminates_running_process(monkeypatch: pytest.MonkeyPatch) -> None:
    kill_calls: list[tuple[int, int]] = []

    def fake_killpg(pid: int, signum: int) -> None:
        kill_calls.append((pid, signum))

    monkeypatch.setattr("ainrf.terminal.pty.os.killpg", fake_killpg)
    monkeypatch.setattr("ainrf.terminal.pty.os.close", lambda fd: None)

    runtime = TerminalBridgeRuntime(
        process=cast(Any, DummyProcess()),
        master_fd=10,
    )

    stop_terminal_bridge(runtime)

    assert kill_calls == [(4321, signal.SIGTERM)]
    assert runtime.master_fd is None


def test_terminal_attachment_websocket_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker
    input_calls: list[str] = []
    resize_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(
        "ainrf.api.routes.terminal.write_terminal_input",
        lambda runtime, data: input_calls.append(data),
    )
    monkeypatch.setattr(
        "ainrf.api.routes.terminal.resize_terminal",
        lambda runtime, cols, rows: resize_calls.append((cols, rows)),
    )
    monkeypatch.setattr("ainrf.terminal.attachments.stop_terminal_bridge", lambda runtime: None)

    read_fd, write_fd = os.pipe()
    runtime = TerminalBridgeRuntime(
        process=cast(Any, DummyProcess()),
        master_fd=read_fd,
    )
    monkeypatch.setattr(
        "ainrf.terminal.attachments.start_terminal_bridge",
        lambda command, cwd: runtime,
    )

    attachment = broker.create_attachment(
        "http://testserver/",
        TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="ainrf:u:daemon:e:env-1:personal",
            session_name="ainrf:u:daemon:e:env-1:personal",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "ainrf:u:daemon:e:env-1:personal"),
            spawn_working_directory=tmp_path,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        os.write(write_fd, b"hello from bridge\n")
        assert ws.receive_json() == {"type": "output", "data": "hello from bridge\n"}

        ws.send_text(json.dumps({"type": "input", "data": "ls\n"}))
        ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))

        assert input_calls == ["ls\n"]
        assert resize_calls == [(120, 40)]

    os.close(read_fd)
    os.close(write_fd)


def test_terminal_attachment_websocket_rejects_bad_token(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker
    attachment = broker.create_attachment(
        "http://testserver/",
        TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="ainrf:u:daemon:e:env-1:personal",
            session_name="ainrf:u:daemon:e:env-1:personal",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "ainrf:u:daemon:e:env-1:personal"),
            spawn_working_directory=tmp_path,
        ),
    )

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/terminal/attachments/{attachment.attachment_id}/ws?token=wrong-token"
        ) as ws:
            ws.receive_text()


def test_terminal_attachment_websocket_rejects_input_for_readonly_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker
    input_calls: list[str] = []

    monkeypatch.setattr(
        "ainrf.api.routes.terminal.write_terminal_input",
        lambda runtime, data: input_calls.append(data),
    )
    monkeypatch.setattr("ainrf.terminal.attachments.stop_terminal_bridge", lambda runtime: None)

    read_fd, write_fd = os.pipe()
    runtime = TerminalBridgeRuntime(
        process=cast(Any, DummyProcess()),
        master_fd=read_fd,
    )
    monkeypatch.setattr(
        "ainrf.terminal.attachments.start_terminal_bridge",
        lambda command, cwd: runtime,
    )

    attachment = broker.create_attachment(
        "http://testserver/",
        TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="ainrf:u:daemon:e:env-1:agent",
            session_name="ainrf:u:daemon:e:env-1:agent",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "ainrf:u:daemon:e:env-1:agent"),
            spawn_working_directory=tmp_path,
            readonly=True,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        ws.send_text(json.dumps({"type": "input", "data": "ls\n"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()

    assert input_calls == []
    os.close(read_fd)
    os.close(write_fd)

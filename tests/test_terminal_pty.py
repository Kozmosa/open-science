from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.terminal.models import TerminalAttachmentMode, TerminalAttachmentTarget
from ainrf.terminal.pty import (
    TERMINAL_LOCAL_TARGET_KIND,
    PtyUtf8Decoder,
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


class LoopProxy:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.add_reader_calls: list[int] = []
        self.remove_reader_calls: list[int] = []

    def add_reader(self, fd: int, callback: Any, *args: Any) -> None:
        self.add_reader_calls.append(fd)
        self._loop.add_reader(fd, callback, *args)

    def remove_reader(self, fd: int) -> bool:
        self.remove_reader_calls.append(fd)
        return self._loop.remove_reader(fd)


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


def test_start_terminal_bridge_launches_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_pty_utf8_decoder_preserves_split_multibyte_characters() -> None:
    decoder = PtyUtf8Decoder()
    encoded = "中".encode("utf-8")

    assert decoder.feed(encoded[:1]) == ""
    assert decoder.feed(encoded[1:2]) == ""
    assert decoder.feed(encoded[2:]) == "中"
    assert decoder.flush() == ""


def test_pty_utf8_decoder_preserves_mixed_ascii_and_chinese_across_chunks() -> None:
    decoder = PtyUtf8Decoder()
    text = "hello中文\n"
    encoded = text.encode("utf-8")

    decoded = "".join(
        [
            decoder.feed(encoded[:4]),
            decoder.feed(encoded[4:6]),
            decoder.feed(encoded[6:8]),
            decoder.feed(encoded[8:10]),
            decoder.feed(encoded[10:]),
            decoder.flush(),
        ]
    )

    assert decoded == text
    assert "�" not in decoded


def test_pty_utf8_decoder_replaces_invalid_bytes_without_raising() -> None:
    decoder = PtyUtf8Decoder()

    decoded = decoder.feed(b"ok\xff\xfe") + decoder.flush()

    assert decoded == "ok��"


def test_pty_utf8_decoder_flushes_incomplete_sequence_at_eof() -> None:
    decoder = PtyUtf8Decoder()

    assert decoder.feed(b"A\xe4\xb8") == "A"
    assert decoder.flush() == "�"


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
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
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
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not resize_calls:
            time.sleep(0.01)
        assert resize_calls == [(120, 40)]

    os.close(read_fd)
    os.close(write_fd)


def test_terminal_attachment_websocket_preserves_split_utf8_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker

    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_READ_CHUNK_BYTES", 1)
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
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
            spawn_working_directory=tmp_path,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        os.write(write_fd, "中文\n".encode("utf-8"))
        os.close(write_fd)

        payloads = [ws.receive_json(), ws.receive_json(), ws.receive_json()]

        assert payloads == [
            {"type": "output", "data": "中"},
            {"type": "output", "data": "文"},
            {"type": "output", "data": "\n"},
        ]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()

    os.close(read_fd)


def test_terminal_attachment_websocket_flushes_decoder_on_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker

    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_READ_CHUNK_BYTES", 2)
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
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
            spawn_working_directory=tmp_path,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        os.write(write_fd, b"A\xe4\xb8")
        os.close(write_fd)

        assert ws.receive_json() == {"type": "output", "data": "A"}
        assert ws.receive_json() == {"type": "output", "data": "�"}
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()

    os.close(read_fd)


def test_terminal_attachment_websocket_drains_output_before_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker

    monkeypatch.setattr("ainrf.terminal.attachments.stop_terminal_bridge", lambda runtime: None)

    process = DummyProcess()
    read_fd, write_fd = os.pipe()
    runtime = TerminalBridgeRuntime(
        process=cast(Any, process),
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
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
            spawn_working_directory=tmp_path,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        os.write(write_fd, b"hello before exit\n")
        process.returncode = 0
        os.close(write_fd)

        assert ws.receive_json() == {"type": "output", "data": "hello before exit\n"}
        assert ws.receive_json() == {"type": "status", "status": "exited", "return_code": 0}
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()

    os.close(read_fd)


def test_terminal_attachment_websocket_soft_backpressure_pauses_and_resumes_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker
    original_send_json = WebSocket.send_json
    real_get_running_loop = asyncio.get_running_loop
    loop_proxy_holder: dict[str, LoopProxy] = {}

    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_READ_CHUNK_BYTES", 4)
    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_QUEUE_MAX_CHUNKS", 4)
    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_HIGH_WATERMARK_BYTES", 8)
    monkeypatch.setattr("ainrf.api.routes.terminal.TERMINAL_OUTPUT_LOW_WATERMARK_BYTES", 4)
    monkeypatch.setattr("ainrf.terminal.attachments.stop_terminal_bridge", lambda runtime: None)

    def fake_get_running_loop() -> LoopProxy:
        loop_proxy = loop_proxy_holder.get("loop")
        if loop_proxy is None:
            loop_proxy = LoopProxy(real_get_running_loop())
            loop_proxy_holder["loop"] = loop_proxy
        return loop_proxy

    async def delayed_send_json(websocket: WebSocket, data: Any, mode: str = "text") -> None:
        if isinstance(data, dict) and data.get("type") == "output":
            await asyncio.sleep(0.05)
        await original_send_json(websocket, data, mode=mode)

    monkeypatch.setattr("ainrf.api.routes.terminal._get_running_loop", fake_get_running_loop)
    monkeypatch.setattr(WebSocket, "send_json", delayed_send_json)

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
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
            spawn_working_directory=tmp_path,
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ) as ws:
        os.write(write_fd, b"abcdefghijkl")
        os.close(write_fd)

        payloads = [ws.receive_json(), ws.receive_json(), ws.receive_json()]

        assert payloads == [
            {"type": "output", "data": "abcd"},
            {"type": "output", "data": "efgh"},
            {"type": "output", "data": "ijkl"},
        ]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()

    loop_proxy = loop_proxy_holder["loop"]
    assert loop_proxy.add_reader_calls.count(read_fd) >= 2
    assert loop_proxy.remove_reader_calls.count(read_fd) >= 2
    os.close(read_fd)


def test_terminal_attachment_websocket_rejects_bad_token(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker
    attachment = broker.create_attachment(
        "http://testserver/",
        TerminalAttachmentTarget(
            binding_id="binding-1",
            session_id="p-deadbeef10",
            session_name="p-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "p-deadbeef10"),
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
            session_id="a-deadbeef10",
            session_name="a-deadbeef10",
            user_id="daemon",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "a-deadbeef10"),
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


def test_task_attachment_websocket_close_tolerates_missing_task_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_client(tmp_path)
    broker = app.state.terminal_attachment_broker

    monkeypatch.setattr(
        "ainrf.terminal.attachments.stop_terminal_bridge",
        lambda runtime: None,
    )

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
            session_id="@1",
            session_name="a-abcdef1234",
            user_id="browser-user",
            environment_id="env-1",
            environment_alias="gpu-lab",
            target_kind=TERMINAL_LOCAL_TARGET_KIND,
            working_directory="/workspace/project",
            attach_command=("tmux", "attach-session", "-t", "a-abcdef1234"),
            spawn_working_directory=tmp_path,
            readonly=False,
            mode=TerminalAttachmentMode.WRITE,
            window_id="@1",
            window_name="train-task",
            owner_user_id="browser-user",
            task_id="task-1",
            binding_status="taken_over",
        ),
    )

    with client.websocket_connect(
        f"/terminal/attachments/{attachment.attachment_id}/ws?token={attachment.token}"
    ):
        pass

    os.close(read_fd)
    os.close(write_fd)

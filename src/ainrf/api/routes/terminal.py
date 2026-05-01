from __future__ import annotations

import asyncio
import errno
import json
import os
from contextlib import suppress
from typing import Any

from anyio import create_task_group, to_thread
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ainrf.api.schemas import (
    TerminalSessionCreateRequest,
    TerminalSessionResetRequest,
    TerminalSessionResponse,
    TerminalSessionStatus,
    UserSessionPairListResponse,
    UserSessionPairResponse,
)
from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.tasks.service import TaskManager
from ainrf.terminal.attachments import (
    TerminalAttachmentAuthorizationError,
    TerminalAttachmentBroker,
    TerminalAttachmentConflictError,
    TerminalAttachmentExpiredError,
    TerminalAttachmentNotFoundError,
)
from ainrf.terminal.models import (
    TerminalAttachmentMode,
    TerminalSessionRecord,
    UserEnvironmentBinding,
    UserSessionPair,
)
from ainrf.terminal.pty import (
    TERMINAL_OUTPUT_HIGH_WATERMARK_BYTES,
    TERMINAL_OUTPUT_LOW_WATERMARK_BYTES,
    TERMINAL_OUTPUT_QUEUE_MAX_CHUNKS,
    TERMINAL_OUTPUT_READ_CHUNK_BYTES,
    PtyUtf8Decoder,
    resize_terminal,
    write_terminal_input,
)
from ainrf.terminal.sessions import SessionManager, TerminalSessionOperationError

router = APIRouter(prefix="/terminal", tags=["terminal"])
_APP_USER_HEADER = "X-AINRF-User-Id"


def _serialize_session(
    session: TerminalSessionRecord,
) -> dict[str, str | None | TerminalSessionStatus]:
    return {
        "session_id": session.session_id,
        "provider": session.provider,
        "target_kind": session.target_kind,
        "environment_id": session.environment_id,
        "environment_alias": session.environment_alias,
        "working_directory": session.working_directory,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "closed_at": session.closed_at.isoformat() if session.closed_at else None,
        "terminal_ws_url": session.terminal_ws_url,
        "detail": session.detail,
        "binding_id": session.binding_id,
        "session_name": session.session_name,
        "attachment_id": session.attachment_id,
        "attachment_expires_at": session.attachment_expires_at.isoformat()
        if session.attachment_expires_at
        else None,
    }


def _serialize_session_pair(
    binding: UserEnvironmentBinding,
    pair: UserSessionPair,
    environment: EnvironmentRegistryEntry | None,
) -> dict[str, str | None | TerminalSessionStatus]:
    return {
        "binding_id": binding.binding_id,
        "environment_id": binding.environment_id,
        "environment_alias": environment.alias if environment is not None else None,
        "personal_session_name": pair.personal_session_name,
        "agent_session_name": pair.agent_session_name,
        "personal_status": pair.personal_status,
        "agent_status": pair.agent_status,
        "created_at": pair.created_at.isoformat() if pair.created_at is not None else None,
        "updated_at": pair.updated_at.isoformat() if pair.updated_at is not None else None,
        "last_verified_at": pair.last_verified_at.isoformat()
        if pair.last_verified_at is not None
        else None,
        "last_personal_attach_at": pair.last_personal_attach_at.isoformat()
        if pair.last_personal_attach_at is not None
        else None,
        "last_agent_attach_at": pair.last_agent_attach_at.isoformat()
        if pair.last_agent_attach_at is not None
        else None,
        "detail": pair.detail,
    }


def _get_environment_service(request: Request | WebSocket) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _get_session_manager(request: Request | WebSocket) -> SessionManager:
    manager = getattr(request.app.state, "terminal_session_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="terminal session manager not initialized")
    return manager


def _get_attachment_broker(request: Request | WebSocket) -> TerminalAttachmentBroker:
    broker = getattr(request.app.state, "terminal_attachment_broker", None)
    if broker is None:
        raise HTTPException(status_code=500, detail="terminal attachment broker not initialized")
    return broker


def _get_task_manager(request: Request | WebSocket) -> TaskManager | None:
    return getattr(request.app.state, "task_manager", None)


def _require_app_user_id(request: Request) -> str:
    user_id = request.headers.get(_APP_USER_HEADER, "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail=f"Missing required header: {_APP_USER_HEADER}")
    return user_id


def _translate_environment_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EnvironmentNotFoundError):
        return HTTPException(status_code=404, detail="Environment not found")
    return HTTPException(status_code=500, detail="Unexpected terminal environment error")


def _translate_terminal_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TerminalSessionOperationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected terminal runtime error")


def _close_code_for_http_status(status: int) -> int:
    if status == 404:
        return 4404
    if status == 401:
        return 4401
    if status == 503:
        return 4503
    return 4409


def _close_code_for_attachment_error(exc: Exception) -> int:
    if isinstance(exc, TerminalAttachmentNotFoundError):
        return 4404
    if isinstance(exc, (TerminalAttachmentAuthorizationError, TerminalAttachmentExpiredError)):
        return 4401
    if isinstance(exc, TerminalAttachmentConflictError):
        return 4409
    return 4503


def _get_environment_context(
    service: InMemoryEnvironmentService,
    environment_id: str | None,
    state_root: Any,
    project_id: str = "default",
) -> tuple[EnvironmentRegistryEntry | None, str | None]:
    if environment_id is None:
        return None, None
    environment = service.get_environment(environment_id)
    working_directory = service.resolve_effective_workdir(
        project_id,
        environment_id,
        state_root,
    )
    return environment, working_directory


def _get_running_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


@router.get("/session", response_model=TerminalSessionResponse)
async def read_terminal_session(
    request: Request,
    environment_id: str | None = Query(default=None),
    project_id: str = Query(default="default"),
) -> TerminalSessionResponse:
    app_user_id = _require_app_user_id(request)
    service = _get_environment_service(request)
    manager = _get_session_manager(request)
    try:
        environment, working_directory = _get_environment_context(
            service,
            environment_id,
            request.app.state.api_config.state_root,
            project_id=project_id,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc

    session = await to_thread.run_sync(
        manager.get_session_record,
        app_user_id,
        environment,
        working_directory,
    )
    return TerminalSessionResponse.model_validate(_serialize_session(session))


@router.get("/session-pairs", response_model=UserSessionPairListResponse)
async def read_terminal_session_pairs(
    request: Request,
    environment_id: str | None = Query(default=None),
    project_id: str = Query(default="default"),
) -> UserSessionPairListResponse:
    app_user_id = _require_app_user_id(request)
    service = _get_environment_service(request)
    manager = _get_session_manager(request)
    if environment_id is not None:
        try:
            service.get_environment(environment_id)
        except Exception as exc:
            raise _translate_environment_error(exc) from exc

    items = await to_thread.run_sync(manager.list_session_pairs, app_user_id, environment_id)
    return UserSessionPairListResponse(
        items=[
            UserSessionPairResponse.model_validate(
                _serialize_session_pair(binding, pair, environment)
            )
            for binding, pair, environment in items
        ]
    )


@router.post("/session", response_model=TerminalSessionResponse)
async def create_terminal_session(
    payload: TerminalSessionCreateRequest,
    request: Request,
    project_id: str = Query(default="default"),
) -> TerminalSessionResponse:
    app_user_id = _require_app_user_id(request)
    service = _get_environment_service(request)
    manager = _get_session_manager(request)
    broker = _get_attachment_broker(request)
    try:
        environment, working_directory = _get_environment_context(
            service,
            payload.environment_id,
            request.app.state.api_config.state_root,
            project_id=project_id,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    assert environment is not None

    try:
        session, target = await to_thread.run_sync(
            manager.ensure_personal_session,
            app_user_id,
            environment,
            working_directory,
        )
    except Exception as exc:
        raise _translate_terminal_error(exc) from exc

    attachment = broker.create_attachment(str(request.base_url), target)
    await to_thread.run_sync(manager.record_personal_attach, target.binding_id)
    attached_session = broker.attach_record(session, attachment, str(request.base_url))
    return TerminalSessionResponse.model_validate(_serialize_session(attached_session))


@router.delete("/session", response_model=TerminalSessionResponse)
async def delete_terminal_session(
    request: Request,
    environment_id: str | None = Query(default=None),
    attachment_id: str | None = Query(default=None),
    project_id: str = Query(default="default"),
) -> TerminalSessionResponse:
    app_user_id = _require_app_user_id(request)
    service = _get_environment_service(request)
    manager = _get_session_manager(request)
    broker = _get_attachment_broker(request)
    detached_attachment = broker.detach_attachment(attachment_id)
    resolved_environment_id = environment_id or (
        detached_attachment.environment_id if detached_attachment is not None else None
    )
    try:
        environment, working_directory = _get_environment_context(
            service,
            resolved_environment_id,
            request.app.state.api_config.state_root,
            project_id=project_id,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc

    session = await to_thread.run_sync(
        manager.get_session_record,
        app_user_id,
        environment,
        working_directory,
    )
    return TerminalSessionResponse.model_validate(_serialize_session(session))


@router.post("/session/reset", response_model=TerminalSessionResponse)
async def reset_terminal_session(
    payload: TerminalSessionResetRequest,
    request: Request,
    project_id: str = Query(default="default"),
) -> TerminalSessionResponse:
    app_user_id = _require_app_user_id(request)
    service = _get_environment_service(request)
    manager = _get_session_manager(request)
    broker = _get_attachment_broker(request)
    broker.detach_attachment(payload.attachment_id)
    try:
        environment, working_directory = _get_environment_context(
            service,
            payload.environment_id,
            request.app.state.api_config.state_root,
            project_id=project_id,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc
    assert environment is not None

    try:
        session, target = await to_thread.run_sync(
            manager.reset_personal_session,
            app_user_id,
            environment,
            working_directory,
        )
    except Exception as exc:
        raise _translate_terminal_error(exc) from exc

    attachment = broker.create_attachment(str(request.base_url), target)
    await to_thread.run_sync(manager.record_personal_attach, target.binding_id)
    attached_session = broker.attach_record(session, attachment, str(request.base_url))
    return TerminalSessionResponse.model_validate(_serialize_session(attached_session))


@router.websocket("/attachments/{attachment_id}/ws")
async def terminal_attachment_ws(attachment_id: str, token: str, websocket: WebSocket) -> None:
    broker = _get_attachment_broker(websocket)
    task_manager = _get_task_manager(websocket)
    try:
        attachment, runtime = broker.open_runtime(attachment_id, token)
    except Exception as exc:
        await websocket.close(code=_close_code_for_attachment_error(exc))
        return

    await websocket.accept()
    master_fd = runtime.master_fd
    if master_fd is None:
        broker.close_runtime(attachment_id)
        await websocket.close(code=4409)
        return

    loop = _get_running_loop()
    output_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
        maxsize=TERMINAL_OUTPUT_QUEUE_MAX_CHUNKS
    )
    decoder = PtyUtf8Decoder()
    buffered_output_bytes = 0
    reader_paused = False
    reader_closed = False
    output_complete_pending = False
    process_return_code: int | None = None
    empty_read_retry_scheduled = False

    def pause_reader() -> None:
        nonlocal reader_paused
        if reader_paused:
            return
        loop.remove_reader(master_fd)
        reader_paused = True

    def close_reader() -> None:
        nonlocal reader_closed
        if reader_closed:
            return
        reader_closed = True
        pause_reader()

    def try_enqueue_output_complete() -> None:
        nonlocal output_complete_pending
        if not output_complete_pending or output_queue.full():
            return
        output_queue.put_nowait(None)
        output_complete_pending = False

    def mark_output_complete() -> None:
        nonlocal output_complete_pending
        close_reader()
        if output_complete_pending:
            return
        output_complete_pending = True
        try_enqueue_output_complete()

    def maybe_resume_reader() -> None:
        nonlocal reader_paused, empty_read_retry_scheduled
        empty_read_retry_scheduled = False
        if not reader_paused or reader_closed or runtime.master_fd is None:
            return
        if buffered_output_bytes > TERMINAL_OUTPUT_LOW_WATERMARK_BYTES:
            return
        loop.add_reader(master_fd, on_master_ready)
        reader_paused = False

    def on_master_ready() -> None:
        nonlocal buffered_output_bytes, empty_read_retry_scheduled, process_return_code
        if runtime.master_fd is None:
            return
        if output_queue.full():
            pause_reader()
            return
        transient_empty_read = False
        try:
            raw_chunk = os.read(runtime.master_fd, TERMINAL_OUTPUT_READ_CHUNK_BYTES)
        except OSError as exc:
            if exc.errno not in {errno.EIO, errno.EBADF}:
                mark_output_complete()
                return
            transient_empty_read = True
            raw_chunk = b""
        if raw_chunk:
            output_queue.put_nowait(raw_chunk)
            buffered_output_bytes += len(raw_chunk)
            if buffered_output_bytes >= TERMINAL_OUTPUT_HIGH_WATERMARK_BYTES:
                pause_reader()
            return
        if transient_empty_read and process_return_code is None:
            process_return_code = runtime.process.poll()
        if transient_empty_read and process_return_code is None:
            # Some PTY stacks can surface a transient readable/empty state before the
            # attach process has actually exited. Re-arm the reader instead of closing.
            pause_reader()
            if not empty_read_retry_scheduled:
                empty_read_retry_scheduled = True
                loop.call_later(0.25, maybe_resume_reader)
            return
        mark_output_complete()

    loop.add_reader(master_fd, on_master_ready)

    async def forward_input() -> None:
        try:
            while True:
                message = await websocket.receive_text()
                payload = json.loads(message)
                message_type = payload.get("type")
                if message_type == "input":
                    if attachment.readonly or attachment.mode is TerminalAttachmentMode.OBSERVE:
                        if websocket.client_state == WebSocketState.CONNECTED:
                            with suppress(Exception):
                                await websocket.close(code=4409)
                        return
                    data = payload.get("data")
                    if not isinstance(data, str):
                        raise ValueError("input payload must include string data")
                    write_terminal_input(runtime, data)
                    continue
                if message_type == "resize":
                    cols = payload.get("cols")
                    rows = payload.get("rows")
                    if not isinstance(cols, int) or not isinstance(rows, int):
                        raise ValueError("resize payload must include integer cols and rows")
                    resize_terminal(runtime, cols, rows)
                    continue
                raise ValueError(f"Unsupported terminal message type: {message_type!r}")
        except WebSocketDisconnect:
            task_group.cancel_scope.cancel()
        except ValueError:
            if websocket.client_state == WebSocketState.CONNECTED:
                with suppress(Exception):
                    await websocket.close(code=4409)
            task_group.cancel_scope.cancel()

    async def forward_output() -> None:
        nonlocal buffered_output_bytes, process_return_code
        try:
            while True:
                chunk = await output_queue.get()
                if chunk is None:
                    remainder = decoder.flush()
                    if remainder:
                        await websocket.send_json({"type": "output", "data": remainder})
                    if process_return_code is None:
                        process_return_code = runtime.process.poll()
                    if process_return_code is not None:
                        with suppress(Exception):
                            await websocket.send_json(
                                {
                                    "type": "status",
                                    "status": "exited",
                                    "return_code": process_return_code,
                                }
                            )
                    return
                buffered_output_bytes -= len(chunk)
                try_enqueue_output_complete()
                maybe_resume_reader()
                decoded_chunk = decoder.feed(chunk)
                if not decoded_chunk:
                    continue
                await websocket.send_json({"type": "output", "data": decoded_chunk})
        except Exception:
            pass
        finally:
            task_group.cancel_scope.cancel()

    async def watch_process() -> None:
        nonlocal process_return_code
        while True:
            returncode = runtime.process.poll()
            if returncode is not None:
                process_return_code = returncode
                mark_output_complete()
                return
            await asyncio.sleep(0.25)

    try:
        async with create_task_group() as task_group:
            task_group.start_soon(forward_input)
            task_group.start_soon(forward_output)
            task_group.start_soon(watch_process)
    finally:
        loop.remove_reader(master_fd)
        broker.close_runtime(attachment_id)
        if task_manager is not None:
            await to_thread.run_sync(task_manager.handle_task_attachment_disconnect, attachment)
        if (
            websocket.client_state != WebSocketState.DISCONNECTED
            and websocket.application_state != WebSocketState.DISCONNECTED
        ):
            await websocket.close()

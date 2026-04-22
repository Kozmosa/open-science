from __future__ import annotations

from functools import partial
from typing import Any

from anyio import to_thread
from fastapi import APIRouter, HTTPException, Query, Request

from ainrf.api.schemas import (
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
    TaskTerminalBindingResponse,
    TerminalAttachmentResponse,
)
from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.tasks import ManagedTask, TaskManager, TaskOperationError, TaskTerminalBinding
from ainrf.terminal.attachments import TerminalAttachment, TerminalAttachmentBroker
from ainrf.terminal.pty import build_attachment_ws_url

router = APIRouter(prefix="/tasks", tags=["tasks"])
_DEFAULT_PROJECT_ID = "default"


def _get_environment_service(request: Request) -> InMemoryEnvironmentService:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="environment service not initialized")
    return service


def _get_task_manager(request: Request) -> TaskManager:
    manager = getattr(request.app.state, "task_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="task manager not initialized")
    return manager


def _get_attachment_broker(request: Request) -> TerminalAttachmentBroker:
    broker = getattr(request.app.state, "terminal_attachment_broker", None)
    if broker is None:
        raise HTTPException(status_code=500, detail="terminal attachment broker not initialized")
    return broker


def _translate_environment_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EnvironmentNotFoundError):
        return HTTPException(status_code=404, detail="Environment not found")
    return HTTPException(status_code=500, detail="Unexpected task environment error")


def _translate_task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaskOperationError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(status_code=404, detail=message)
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=500, detail="Unexpected task runtime error")


def _serialize_terminal_binding(
    terminal_binding: TaskTerminalBinding,
) -> dict[str, str | bool | None | TaskStatus]:
    return {
        "task_id": terminal_binding.task_id,
        "binding_id": terminal_binding.binding_id,
        "environment_id": terminal_binding.environment_id,
        "agent_session_name": terminal_binding.agent_session_name,
        "window_id": terminal_binding.window_id,
        "window_name": terminal_binding.window_name,
        "status": terminal_binding.status.value,
        "mode": terminal_binding.mode,
        "readonly": terminal_binding.readonly,
        "last_output_at": terminal_binding.last_output_at.isoformat()
        if terminal_binding.last_output_at is not None
        else None,
    }


def _serialize_task(
    task: ManagedTask,
    terminal_binding: TaskTerminalBinding | None,
    *,
    environment_alias: str | None,
) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "binding_id": task.binding_id,
        "environment_id": task.environment_id,
        "environment_alias": environment_alias,
        "title": task.title,
        "command": task.command,
        "working_directory": task.working_directory,
        "status": task.status.value,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at is not None else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at is not None else None,
        "exit_code": task.exit_code,
        "detail": task.detail,
        "terminal": _serialize_terminal_binding(terminal_binding) if terminal_binding is not None else None,
    }


def _serialize_attachment(
    attachment: TerminalAttachment,
    *,
    terminal_ws_url: str,
) -> dict[str, Any]:
    return {
        "attachment_id": attachment.attachment_id,
        "terminal_ws_url": terminal_ws_url,
        "expires_at": attachment.expires_at.isoformat(),
        "binding_id": attachment.binding_id,
        "session_id": attachment.session_id,
        "session_name": attachment.session_name,
        "environment_id": attachment.environment_id,
        "environment_alias": attachment.environment_alias,
        "target_kind": attachment.target_kind,
        "working_directory": attachment.working_directory,
        "readonly": attachment.readonly,
        "mode": attachment.mode,
        "window_id": attachment.window_id,
        "window_name": attachment.window_name,
    }


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    environment_id: str = Query(),
) -> TaskListResponse:
    service = _get_environment_service(request)
    manager = _get_task_manager(request)
    try:
        environment = service.get_environment(environment_id)
    except Exception as exc:
        raise _translate_environment_error(exc) from exc

    try:
        items = await to_thread.run_sync(manager.list_tasks, environment_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    return TaskListResponse(
        items=[
            TaskResponse.model_validate(
                _serialize_task(task, terminal_binding, environment_alias=environment.alias)
            )
            for task, terminal_binding in items
        ]
    )


@router.post("", response_model=TaskResponse)
async def create_task(payload: TaskCreateRequest, request: Request) -> TaskResponse:
    service = _get_environment_service(request)
    manager = _get_task_manager(request)
    try:
        environment = service.get_environment(payload.environment_id)
        default_working_directory = service.resolve_effective_workdir(
            _DEFAULT_PROJECT_ID,
            payload.environment_id,
            request.app.state.api_config.state_root,
        )
    except Exception as exc:
        raise _translate_environment_error(exc) from exc

    try:
        task, terminal_binding = await to_thread.run_sync(
            partial(
                manager.create_task,
                environment,
                title=payload.title,
                command=payload.command,
                working_directory=payload.working_directory or default_working_directory,
            )
        )
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    return TaskResponse.model_validate(
        _serialize_task(task, terminal_binding, environment_alias=environment.alias)
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def read_task(task_id: str, request: Request) -> TaskResponse:
    service = _get_environment_service(request)
    manager = _get_task_manager(request)
    try:
        task, terminal_binding = await to_thread.run_sync(manager.get_task, task_id)
        environment_alias = service.get_environment(task.environment_id).alias
    except EnvironmentNotFoundError:
        environment_alias = None
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    return TaskResponse.model_validate(
        _serialize_task(task, terminal_binding, environment_alias=environment_alias)
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str, request: Request) -> TaskResponse:
    service = _get_environment_service(request)
    manager = _get_task_manager(request)
    try:
        task, terminal_binding = await to_thread.run_sync(manager.cancel_task, task_id)
        environment_alias = service.get_environment(task.environment_id).alias
    except EnvironmentNotFoundError:
        environment_alias = None
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    return TaskResponse.model_validate(
        _serialize_task(task, terminal_binding, environment_alias=environment_alias)
    )


@router.get("/{task_id}/terminal", response_model=TaskTerminalBindingResponse)
async def read_task_terminal(task_id: str, request: Request) -> TaskTerminalBindingResponse:
    manager = _get_task_manager(request)
    try:
        terminal_binding = await to_thread.run_sync(manager.get_task_terminal_binding, task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    return TaskTerminalBindingResponse.model_validate(_serialize_terminal_binding(terminal_binding))


@router.post("/{task_id}/terminal/open", response_model=TerminalAttachmentResponse)
async def open_task_terminal(task_id: str, request: Request) -> TerminalAttachmentResponse:
    manager = _get_task_manager(request)
    broker = _get_attachment_broker(request)
    try:
        _, _, target = await to_thread.run_sync(manager.open_task_terminal, task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    attachment = broker.create_attachment(str(request.base_url), target)
    await to_thread.run_sync(request.app.state.terminal_session_manager.record_agent_attach, target.binding_id)
    terminal_ws_url = build_attachment_ws_url(
        str(request.base_url),
        attachment.attachment_id,
        attachment.token,
    )
    return TerminalAttachmentResponse.model_validate(
        _serialize_attachment(attachment, terminal_ws_url=terminal_ws_url)
    )

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from ainrf.agentic_researcher import (
    AgenticResearcherService,
    HarnessEngineType,
    TaskStatus,
    aris,
    vanilla,
)
from ainrf.agentic_researcher.models import Task, TaskOutputEvent
from ainrf.agentic_researcher.service import TaskNotFoundError, TaskOperationError
from ainrf.projects import ProjectNotFoundError, ProjectRegistryService
from ainrf.api.schemas import (
    MessageItemResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskHealthResponse,
    TaskMessagesResponse,
    TaskOutputItemResponse,
    TaskOutputResponse,
    TaskPauseResponse,
    TaskPromptRequest,
    TaskPromptSendResponse,
    TaskResumeResponse,
    TaskRetryResponse,
    TaskSummaryResponse,
    TaskTokenUsageSummaryResponse,
    TaskUpdateProjectRequest,
    TaskUpdateRequest,
)
from ainrf.auth.permissions import (
    check_resource_ownership,
    get_current_user,
)
from ainrf.domain import DomainPermissionError, TaskApplicationService
from ainrf.domain_control import DomainModelMode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_service(request: Request) -> AgenticResearcherService:
    service = getattr(request.app.state, "agentic_researcher_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="AgenticResearcher service not initialized")
    return service


def _get_project_service(request: Request) -> ProjectRegistryService:
    service = getattr(request.app.state, "project_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Project service not initialized")
    return service


def _get_task_application_service(request: Request) -> TaskApplicationService | None:
    service = getattr(request.app.state, "task_application_service", None)
    domain = getattr(request.app.state, "domain_service", None)
    if (
        service is None
        or domain is None
        or request.app.state.api_config.domain_model_mode is not DomainModelMode.V2
        or not domain.v2_ready()
    ):
        return None
    return service


def _task_list_owner_filter(user: dict) -> str | None:
    if user.get("role") == "admin":
        return None
    user_id = user.get("id")
    return user_id if isinstance(user_id, str) else None


def _task_to_response(
    task: Task,
    service: AgenticResearcherService | None = None,
) -> TaskSummaryResponse:
    runtime = service.get_runtime_summary(task) if service is not None else {}
    working_directory_value = runtime.get("working_directory")
    command_value = runtime.get("command")
    working_directory = (
        working_directory_value if isinstance(working_directory_value, str) else None
    )
    command = [str(item) for item in command_value] if isinstance(command_value, list) else []
    return TaskSummaryResponse(
        task_id=task.task_id,
        project_id=task.project_id,
        workspace_id=task.workspace_id,
        environment_id=task.environment_id,
        researcher_type=task.researcher_type.value,
        harness_engine=task.harness_engine.value,
        status=task.status.value,
        title=task.title,
        prompt=task.prompt,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        owner_user_id=task.owner_user_id,
        latest_output_seq=task.latest_output_seq,
        exit_code=task.exit_code,
        error_summary=task.error_summary,
        working_directory=working_directory,
        command=command,
        token_usage_json=task.token_usage_json,
    )


def _assert_task_owner(request: Request, task_id: str) -> tuple[AgenticResearcherService, Task]:
    user = get_current_user(request)
    service = _get_service(request)
    try:
        task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    check_resource_ownership(user, task.owner_user_id)
    return service, task


def _assert_task_stream_access(
    request: Request,
    task_id: str,
) -> tuple[AgenticResearcherService, Task]:
    service = _get_service(request)
    try:
        task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    user = get_current_user(request)
    # An API key authenticates a principal; it is not a global task-stream
    # capability.  Treat a non-owner stream lookup as non-existent so a key
    # cannot enumerate or subscribe to another tenant's output.
    if user.get("role") != "admin" and user.get("id") != task.owner_user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return service, task


def _parse_output_payload(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"content": content}
    payload = parsed if isinstance(parsed, dict) else {"content": content}
    wrapped_payload = payload.get("payload")
    if isinstance(wrapped_payload, dict) and isinstance(payload.get("event_type"), str):
        return wrapped_payload
    return payload


_SUPPRESSED_SYSTEM_SUBTYPES = {"status", "thinking_tokens"}


def _is_suppressed_system_payload(payload: dict[str, object]) -> bool:
    subtype = payload.get("subtype")
    return isinstance(subtype, str) and subtype in _SUPPRESSED_SYSTEM_SUBTYPES


def _output_item_to_message(
    item: TaskOutputEvent,
    *,
    initial_prompt: str | None = None,
) -> MessageItemResponse | None:
    payload = _parse_output_payload(item.content)

    metadata = {
        "timestamp": item.created_at.isoformat(),
        "sequence": item.seq,
    }
    message_id = f"{item.task_id}-{item.seq}"

    if item.kind == "message":
        content = str(payload.get("content") or "")
        role = payload.get("role")
        message_type = "user" if role == "user" or content == initial_prompt else "assistant"
        return MessageItemResponse(
            id=message_id,
            type=message_type,
            content=content,
            metadata=metadata,
        )
    if item.kind == "thinking":
        return MessageItemResponse(
            id=message_id,
            type="thinking",
            content=str(payload.get("content") or ""),
            metadata={**metadata, "isFolded": True},
        )
    if item.kind == "tool_call":
        return MessageItemResponse(
            id=message_id,
            type="tool_call",
            content={"name": payload.get("name"), "arguments": payload.get("arguments")},
            metadata={**metadata, "isFolded": True},
        )
    if item.kind == "tool_result":
        return MessageItemResponse(
            id=message_id,
            type="tool_result",
            content={"tool_use_id": payload.get("tool_use_id"), "content": payload.get("content")},
            metadata={**metadata, "isFolded": True},
        )
    if item.kind in {"system", "lifecycle"}:
        if _is_suppressed_system_payload(payload):
            return None
        return MessageItemResponse(
            id=message_id,
            type="system_event",
            content=str(payload.get("subtype") or payload.get("content") or item.kind),
            metadata=metadata,
        )
    if item.kind == "stdout":
        return MessageItemResponse(
            id=message_id,
            type="assistant",
            content=str(payload.get("content") or item.content),
            metadata=metadata,
        )
    if item.kind == "stderr":
        return MessageItemResponse(
            id=message_id,
            type="system_event",
            content=f"[stderr] {payload.get('content') or item.content}",
            metadata=metadata,
        )
    return None


def _output_items_to_messages(
    items: list[TaskOutputEvent],
    task: Task,
) -> list[MessageItemResponse]:
    messages: list[MessageItemResponse] = []
    seen_user_content: set[str] = set()
    for item in items:
        message = _output_item_to_message(item, initial_prompt=task.prompt)
        if message is None:
            continue
        if message.type == "assistant" and isinstance(message.content, str):
            if message.content in seen_user_content:
                continue
        if message.type == "user" and isinstance(message.content, str):
            seen_user_content.add(message.content)
        messages.append(message)
    return messages


@router.post("", status_code=201)
async def create_task(request: Request, payload: TaskCreateRequest) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_service(request)

    task_application = _get_task_application_service(request)
    if task_application is not None:
        if not payload.project_id:
            raise HTTPException(
                status_code=409, detail="v2 Task creation requires an explicit Project"
            )
        try:
            created = task_application.create_task(
                user,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                title=payload.title or "Task",
                prompt=payload.prompt,
                researcher_type=payload.researcher_type,
                harness_engine=payload.harness_engine,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
            return _task_to_response(service.get_task(created["task_id"]), service)
        except (DomainPermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    engine_type = HarnessEngineType(payload.harness_engine)
    if payload.researcher_type == "vanilla":
        researcher = vanilla(engine=engine_type, user_skills=payload.skills)
    elif payload.researcher_type == "aris-researcher":
        researcher = aris(engine=engine_type)
    else:
        raise HTTPException(
            status_code=400, detail=f"Unknown researcher type: {payload.researcher_type}"
        )

    project_svc = _get_project_service(request)
    effective_project_id = payload.project_id
    if not effective_project_id:
        # No project bound → route to the user's default project (created on demand).
        default_project = project_svc.get_or_create_user_default(
            username=user["username"],
            owner_user_id=user["id"],
        )
        effective_project_id = default_project.project_id
    else:
        # Reject orphan tasks: an explicitly bound project must exist.
        try:
            project_svc.get_project(effective_project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Project not found: {effective_project_id}",
            ) from exc

    try:
        # Build profile overrides from the optional research agent profile.
        profile_overrides = None
        if payload.research_agent_profile is not None:
            p = payload.research_agent_profile
            profile_overrides = {
                "api_base_url": p.api_base_url,
                "api_key": p.api_key,
                "codex_base_url": p.codex_base_url,
                "codex_api_key": p.codex_api_key,
                "codex_model": p.codex_model,
                "codex_app_server_command": p.codex_app_server_command,
                "codex_approval_policy": p.codex_approval_policy,
            }

        task = service.create_task(
            project_id=effective_project_id,
            workspace_id=payload.workspace_id,
            environment_id=payload.environment_id,
            researcher=researcher,
            prompt=payload.prompt,
            owner_user_id=user["id"],
            title=payload.title,
            profile_overrides=profile_overrides,
        )
        service.schedule_task(task.task_id)
    except Exception as exc:
        logger.exception("task_create_failed", exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info("task_created_via_api task_id=%s project_id=%s", task.task_id, effective_project_id)
    return _task_to_response(task, service)


@router.get("")
async def list_tasks(
    request: Request,
    project_id: str | None = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    sort: str = Query("updated"),
) -> TaskListResponse:
    user = get_current_user(request)
    service = _get_service(request)

    tasks = service.list_tasks(
        project_id=project_id,
        user_id=_task_list_owner_filter(user),
        include_archived=include_archived,
        limit=limit,
        sort=sort,
    )
    return TaskListResponse(
        items=[_task_to_response(t, service) for t in tasks],
        total=len(tasks),
    )


@router.get("/token-usage", response_model=TaskTokenUsageSummaryResponse)
async def get_task_token_usage_summary(
    request: Request,
    include_archived: bool = Query(True),
) -> TaskTokenUsageSummaryResponse:
    user = get_current_user(request)
    service = _get_service(request)
    summary = service.token_usage_summary(
        user_id=_task_list_owner_filter(user),
        include_archived=include_archived,
    )
    return TaskTokenUsageSummaryResponse.model_validate(summary)


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str) -> TaskSummaryResponse:
    _, task = _assert_task_owner(request, task_id)
    return _task_to_response(task, _get_service(request))


@router.get("/{task_id}/health", response_model=TaskHealthResponse)
async def get_task_health(request: Request, task_id: str) -> TaskHealthResponse:
    service, task = _assert_task_owner(request, task_id)
    engine = service.get_engine_for_task(task)
    engine_alive = await engine.is_alive(task_id)
    last_event_at = await engine.last_event_at(task_id)
    inactive_seconds = None
    last_event_at_iso: str | None = None
    if last_event_at is not None:
        last_event_at_iso = datetime.fromtimestamp(last_event_at, tz=timezone.utc).isoformat()
        inactive_seconds = round(time.time() - last_event_at, 1)
    return TaskHealthResponse(
        task_id=task_id,
        status=task.status.value,
        engine_alive=engine_alive,
        last_event_at=last_event_at_iso,
        inactive_seconds=inactive_seconds,
    )


@router.post("/{task_id}/cancel", status_code=204)
async def cancel_task(request: Request, task_id: str) -> None:
    service, _ = _assert_task_owner(request, task_id)

    try:
        await service.cancel_running_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/pause")
async def pause_task(request: Request, task_id: str) -> TaskPauseResponse:
    service, _ = _assert_task_owner(request, task_id)
    try:
        task = await service.pause_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskPauseResponse(task_id=task.task_id, status=task.status.value)


@router.post("/{task_id}/resume")
async def resume_task(request: Request, task_id: str) -> TaskResumeResponse:
    service, _ = _assert_task_owner(request, task_id)
    try:
        task = await service.resume_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskResumeResponse(task_id=task.task_id, status=task.status.value)


@router.post("/{task_id}/prompt")
async def send_task_prompt(
    request: Request,
    task_id: str,
    payload: TaskPromptRequest,
) -> TaskPromptSendResponse:
    service, _ = _assert_task_owner(request, task_id)
    try:
        event = await service.send_prompt(task_id, payload.prompt)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskPromptSendResponse(task_id=task_id, sequence=event.seq)


@router.delete("/{task_id}", status_code=200)
async def archive_task(request: Request, task_id: str) -> TaskSummaryResponse:
    """Archive (cancel) a task."""
    service, _ = _assert_task_owner(request, task_id)
    task_application = _get_task_application_service(request)
    if task_application is not None:
        try:
            task_application.archive_task(
                task_id,
                get_current_user(request),
                reason="user_archived",
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
            return _task_to_response(service.get_task(task_id), service)
        except (DomainPermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    task = service.get_task(task_id)
    try:
        if task.status in {TaskStatus.QUEUED, TaskStatus.STARTING, TaskStatus.RUNNING}:
            archived = await service.cancel_running_task(task_id)
        else:
            archived = service.archive_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _task_to_response(archived, service)


@router.delete("/{task_id}/permanent", status_code=204)
async def delete_task(request: Request, task_id: str) -> None:
    """Permanently delete a task."""
    service, _ = _assert_task_owner(request, task_id)
    service.delete_task(task_id)


@router.patch("/{task_id}/project", response_model=TaskSummaryResponse)
async def update_task_project(
    task_id: str,
    payload: TaskUpdateProjectRequest,
    request: Request,
) -> TaskSummaryResponse:
    """Move a task to a different project."""
    _assert_task_owner(request, task_id)
    service = _get_service(request)
    project_svc = _get_project_service(request)
    try:
        project_svc.get_project(payload.project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    updated = service.update_task_project(task_id, payload.project_id)
    # Edges are project-scoped; orphan any referencing the moved task.
    project_svc.delete_task_edges_for_task(task_id)
    return _task_to_response(updated, service)


@router.patch("/{task_id}", response_model=TaskSummaryResponse)
async def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
) -> TaskSummaryResponse:
    """Update mutable task fields (title, etc.)."""
    service, _ = _assert_task_owner(request, task_id)
    updated = service.update_task(task_id, title=payload.title)
    return _task_to_response(updated, service)


@router.post("/{task_id}/retry", status_code=201)
async def retry_task(request: Request, task_id: str) -> TaskRetryResponse:
    """Retry a failed or cancelled task.

    For agent-sdk tasks, this resumes the same session and resends the last
    user message. For other engines, a new task is created.
    """
    user = get_current_user(request)
    service = _get_service(request)

    try:
        old_task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    check_resource_ownership(user, old_task.owner_user_id)

    task_application = _get_task_application_service(request)
    if task_application is not None:
        try:
            retried = task_application.retry_task(
                task_id, user, idempotency_key=request.headers.get("Idempotency-Key", "")
            )
            new_task = service.get_task(retried["task_id"])
            return TaskRetryResponse(
                new_task=_task_to_response(new_task, service), archived_task_id=None, edge_id=""
            )
        except (DomainPermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        new_task = await service.retry_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Agent-sdk retry returns the same task; other engines create a new one.
    same_task = new_task.task_id == task_id

    if not same_task:
        service.schedule_task(new_task.task_id)

    return TaskRetryResponse(
        new_task=_task_to_response(new_task, service),
        archived_task_id=task_id if not same_task else None,
        edge_id="",
    )


@router.get("/{task_id}/output")
async def get_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(0, ge=0, le=1000, description="Max items to return; 0 means unlimited"),
) -> TaskOutputResponse:
    user = get_current_user(request)
    service = _get_service(request)

    try:
        task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    check_resource_ownership(user, task.owner_user_id)

    items = service.get_output(task_id, after_seq=after_seq)
    if limit > 0:
        has_more = len(items) > limit
        visible = items[:limit]
    else:
        has_more = False
        visible = items
    next_seq = visible[-1].seq if visible else after_seq
    return TaskOutputResponse(
        items=[
            TaskOutputItemResponse(
                task_id=item.task_id,
                kind=item.kind,
                content=item.content,
                seq=item.seq,
                created_at=item.created_at.isoformat(),
            )
            for item in visible
        ],
        has_more=has_more,
        next_seq=next_seq,
    )


@router.get("/{task_id}/messages")
async def get_task_messages(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> TaskMessagesResponse:
    service, task = _assert_task_owner(request, task_id)
    items = service.get_output(task_id, after_seq=after_seq, limit=limit + 1)
    visible_items = items[:limit]
    messages = _output_items_to_messages(visible_items, task)
    return TaskMessagesResponse(
        messages=messages,
        has_more=len(items) > limit,
        next_sequence=visible_items[-1].seq if len(items) > limit and visible_items else None,
    )


@router.get("/{task_id}/stream")
async def stream_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
) -> StreamingResponse:
    service, _ = _assert_task_stream_access(request, task_id)

    async def event_stream():
        cursor = after_seq
        while True:
            if await request.is_disconnected():
                break
            items = service.get_output(task_id, after_seq=cursor)
            for item in items:
                cursor = item.seq
                payload = TaskOutputItemResponse(
                    task_id=item.task_id,
                    kind=item.kind,
                    content=item.content,
                    seq=item.seq,
                    created_at=item.created_at.isoformat(),
                ).model_dump()
                yield f"event: output\ndata: {json.dumps(payload, ensure_ascii=True)}\n\n"
            task = service.get_task(task_id)
            if not items and task.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                yield (
                    "event: done\n"
                    f"data: {json.dumps({'task_id': task_id, 'status': task.status.value})}\n\n"
                )
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

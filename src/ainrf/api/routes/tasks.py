from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from starlette.responses import StreamingResponse
from ainrf.agentic_researcher.models import (
    Task,
    TaskOutputEvent,
)
from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.deprecation import deprecation_headers, mark_deprecated
from ainrf.api.schemas import (
    MessageItemResponse,
    TaskAttemptListResponse,
    TaskAttemptResponse,
    TaskCreateRequest,
    TaskForkRequest,
    TaskListResponse,
    TaskHealthResponse,
    TaskMessagesResponse,
    TaskMoveRequest,
    TaskMutationResponse,
    TaskOutputItemResponse,
    TaskOutputResponse,
    TaskPauseResponse,
    TaskPromptRequest,
    TaskPromptSendResponse,
    TaskRetryRequest,
    TaskResumeResponse,
    TaskRetryResponse,
    TaskSummaryResponse,
    TaskTokenUsageSummaryResponse,
    TaskUpdateProjectRequest,
    TaskUpdateRequest,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import DomainPermissionError, TaskApplicationService, TaskProjectionService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import MaintenanceModeError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_task_application_service(request: Request) -> TaskApplicationService:
    service = getattr(request.app.state, "task_application_service", None)
    if service is None or not service.v2_ready():
        raise HTTPException(status_code=503, detail="Task domain v2 is not ready")
    if not isinstance(service, TaskApplicationService):
        raise HTTPException(status_code=500, detail="Task application service is invalid")
    return service


def _get_task_projection_service(request: Request) -> TaskProjectionService:
    """Return the authoritative SQLite Task projection."""
    _get_task_application_service(request)
    service = getattr(request.app.state, "task_projection_service", None)
    if service is None:
        service = TaskProjectionService(request.app.state.api_config.state_root)
        request.app.state.task_projection_service = service
    if not isinstance(service, TaskProjectionService):
        raise HTTPException(status_code=500, detail="Task projection service is invalid")
    return service


def _idempotency_key(request: Request) -> str:
    """Require the canonical idempotency header."""
    return require_idempotency_key(request)


def _translate_v2_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail="Task permission denied")
    if isinstance(exc, DomainNotFoundError):
        return HTTPException(status_code=404, detail="Task not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected Task domain error")


def _v2_task_summary(
    projection: TaskProjectionService, task_id: str, user: dict[str, object]
) -> TaskSummaryResponse:
    return TaskSummaryResponse.model_validate(projection.task(task_id, user))


def _v2_task_mutation_response(
    projection: TaskProjectionService,
    user: dict[str, object],
    result: dict[str, object] | dict[str, str],
) -> TaskMutationResponse:
    task_id = result.get("task_id")
    attempt_id = result.get("attempt_id")
    if not isinstance(task_id, str) or not isinstance(attempt_id, str):
        raise HTTPException(status_code=500, detail="Task mutation result is incomplete")
    task = _v2_task_summary(projection, task_id, user)
    attempt = TaskAttemptResponse.model_validate(projection.attempt(attempt_id, user))
    dispatch = attempt.dispatch
    if dispatch is None:
        raise HTTPException(status_code=500, detail="Task Attempt has no dispatch summary")
    return TaskMutationResponse(task=task, attempt=attempt, dispatch=dispatch)


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
    item: TaskOutputEvent, *, initial_prompt: str | None = None
) -> MessageItemResponse | None:
    payload = _parse_output_payload(item.content)
    metadata = {"timestamp": item.created_at.isoformat(), "sequence": item.seq}
    message_id = f"{item.task_id}-{item.seq}"
    if item.kind == "message":
        content = str(payload.get("content") or "")
        role = payload.get("role")
        message_type = "user" if role == "user" or content == initial_prompt else "assistant"
        return MessageItemResponse(
            id=message_id, type=message_type, content=content, metadata=metadata
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
    items: list[TaskOutputEvent], task: Task | TaskSummaryResponse
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
async def create_task(request: Request, payload: TaskCreateRequest) -> TaskMutationResponse:
    user = get_current_user(request)
    task_application = _get_task_application_service(request)
    if not payload.project_id:
        raise HTTPException(status_code=409, detail="v2 Task creation requires an explicit Project")
    try:
        created = task_application.create_task(
            user,
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            title=payload.title or "Task",
            prompt=payload.prompt,
            researcher_type=payload.researcher_type,
            harness_engine=payload.harness_engine,
            environment_id=None,
            user_skills=payload.skills,
            user_mcp_servers=payload.mcp_servers,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        result = _v2_task_mutation_response(projection, user, created)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.get("")
async def list_tasks(
    request: Request,
    project_id: str | None = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    sort: str = Query("updated"),
) -> TaskListResponse:
    user = get_current_user(request)
    projection = _get_task_projection_service(request)
    try:
        tasks = projection.list_tasks(
            user, project_id=project_id, include_archived=include_archived, limit=limit, sort=sort
        )
    except Exception as exc:
        raise _translate_v2_error(exc) from exc
    return TaskListResponse(
        items=[TaskSummaryResponse.model_validate(task) for task in tasks], total=len(tasks)
    )


@router.get("/token-usage", response_model=TaskTokenUsageSummaryResponse)
async def get_task_token_usage_summary(
    request: Request, include_archived: bool = Query(True)
) -> TaskTokenUsageSummaryResponse:
    user = get_current_user(request)
    projection = _get_task_projection_service(request)
    try:
        return TaskTokenUsageSummaryResponse.model_validate(
            projection.token_usage_summary(user, include_archived=include_archived)
        )
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str) -> TaskSummaryResponse:
    projection = _get_task_projection_service(request)
    try:
        return _v2_task_summary(projection, task_id, get_current_user(request))
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.get("/{task_id}/attempts", response_model=TaskAttemptListResponse)
async def list_task_attempts(request: Request, task_id: str) -> TaskAttemptListResponse:
    """Return the durable Attempt history for a Task in v2 mode."""
    projection = _get_task_projection_service(request)
    try:
        return TaskAttemptListResponse.model_validate(
            {"items": projection.attempts(task_id, get_current_user(request))}
        )
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post(
    "/{task_id}/attempts/{attempt_id}/resolve-launch-unknown", response_model=TaskAttemptResponse
)
async def resolve_launch_unknown_attempt(
    request: Request, task_id: str, attempt_id: str
) -> TaskAttemptResponse:
    """Close a manually investigated unknown launch without re-launching it."""
    task_application = _get_task_application_service(request)
    try:
        raw_payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422, detail="resolution request must be valid JSON"
        ) from exc
    if not isinstance(raw_payload, dict):
        raise HTTPException(status_code=422, detail="resolution request must be an object")
    reason = raw_payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="resolution reason is required")
    try:
        task_application.resolve_launch_unknown(
            task_id,
            attempt_id,
            get_current_user(request),
            reason=reason,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        return TaskAttemptResponse.model_validate(
            projection.attempt(attempt_id, get_current_user(request))
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.get("/{task_id}/health", response_model=TaskHealthResponse)
async def get_task_health(request: Request, task_id: str) -> TaskHealthResponse:
    projection = _get_task_projection_service(request)
    try:
        health = projection.health(task_id, get_current_user(request))
        last_event_at = health.get("last_event_at")
        last_event_at_iso = last_event_at if isinstance(last_event_at, str) else None
        inactive_seconds = _inactive_seconds(last_event_at_iso)
        return TaskHealthResponse(
            task_id=task_id,
            status=str(health["status"]),
            engine_alive=bool(health["engine_alive"]),
            last_event_at=last_event_at_iso,
            inactive_seconds=inactive_seconds,
        )
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


def _inactive_seconds(last_event_at: str | None) -> float | None:
    """Return a non-negative elapsed duration for a durable activity timestamp."""
    if last_event_at is None:
        return None
    try:
        observed_at = datetime.fromisoformat(last_event_at)
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return max(0.0, round((datetime.now(timezone.utc) - observed_at).total_seconds(), 1))


@router.post("/{task_id}/cancel", status_code=204)
async def cancel_task(request: Request, task_id: str) -> None:
    task_application = _get_task_application_service(request)
    try:
        task_application.cancel_task(
            task_id,
            get_current_user(request),
            reason="user_cancelled",
            idempotency_key=_idempotency_key(request),
        )
        return
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/pause")
async def pause_task(request: Request, task_id: str) -> TaskPauseResponse:
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        task_application.pause_task(task_id, user, idempotency_key=_idempotency_key(request))
        projection = _get_task_projection_service(request)
        task = _v2_task_summary(projection, task_id, user)
        return TaskPauseResponse(task_id=task_id, status=task.status)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/resume")
async def resume_task(request: Request, task_id: str) -> TaskResumeResponse:
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        task_application.resume_task(task_id, user, idempotency_key=_idempotency_key(request))
        projection = _get_task_projection_service(request)
        task = _v2_task_summary(projection, task_id, user)
        return TaskResumeResponse(task_id=task_id, status=task.status)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


async def _continue_task(
    request: Request, task_id: str, payload: TaskPromptRequest
) -> TaskPromptSendResponse:
    task_application = _get_task_application_service(request)
    try:
        result = task_application.continue_task(
            task_id,
            get_current_user(request),
            prompt=payload.prompt,
            idempotency_key=_idempotency_key(request),
        )
        sequence = result.get("message_sequence")
        if not isinstance(sequence, int):
            raise HTTPException(status_code=500, detail="Task continuation result is incomplete")
        return TaskPromptSendResponse(task_id=task_id, sequence=sequence)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/continue")
async def continue_task(
    request: Request, task_id: str, payload: TaskPromptRequest
) -> TaskPromptSendResponse:
    """Append a Task input or create a durable continuation Attempt."""
    return await _continue_task(request, task_id, payload)


async def _archive_task(
    request: Request, task_id: str, *, pending_response: Response | None = None
) -> TaskSummaryResponse:
    """Archive a Task through the v2 application service when enabled."""
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        archive_result = task_application.archive_task(
            task_id, user, reason="user_archived", idempotency_key=_idempotency_key(request)
        )
        if archive_result.get("archive_pending") is True and pending_response is not None:
            pending_response.status_code = status.HTTP_202_ACCEPTED
            pending_response.headers["X-OpenScience-Archive-State"] = "pending"
        projection = _get_task_projection_service(request)
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/archive", status_code=200)
async def archive_task_v2(
    request: Request, task_id: str, response: Response
) -> TaskSummaryResponse:
    """Standard explicit Task archive endpoint."""
    return await _archive_task(request, task_id, pending_response=response)


@router.post("/{task_id}/unarchive", status_code=200)
async def unarchive_task(request: Request, task_id: str) -> TaskSummaryResponse:
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        task_application.unarchive_task(task_id, user, idempotency_key=_idempotency_key(request))
        projection = _get_task_projection_service(request)
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.delete("/{task_id}/permanent", status_code=204)
async def delete_task(request: Request, task_id: str) -> None:
    """Permanently delete a task."""
    projection = _get_task_projection_service(request)
    try:
        projection.task(task_id, get_current_user(request))
    except Exception as exc:
        raise _translate_v2_error(exc) from exc
    raise HTTPException(
        status_code=410,
        detail="Permanent Task deletion is unavailable; archive the Task instead",
        headers=deprecation_headers(
            route="tasks.permanent_delete", replacement=f"POST /tasks/{task_id}/archive"
        ),
    )


@router.patch("/{task_id}/project", response_model=TaskSummaryResponse)
async def update_task_project(
    task_id: str, payload: TaskUpdateProjectRequest, request: Request, response: Response
) -> TaskSummaryResponse:
    """Compatibility alias for the explicit v2 Task move contract."""
    task_application = _get_task_application_service(request)
    mark_deprecated(
        response, route="tasks.update_project", replacement=f"POST /tasks/{task_id}/move"
    )
    if payload.context_version_id is None:
        raise HTTPException(
            status_code=422, detail="context_version_id is required when moving a v2 Task"
        )
    user = get_current_user(request)
    try:
        task_application.move_task(
            task_id,
            user,
            project_id=payload.project_id,
            context_version_id=payload.context_version_id,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        result = _v2_task_summary(projection, task_id, user)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/move", response_model=TaskSummaryResponse)
async def move_task(
    task_id: str, payload: TaskMoveRequest, request: Request
) -> TaskSummaryResponse:
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        task_application.move_task(
            task_id,
            user,
            project_id=payload.project_id,
            context_version_id=payload.context_version_id,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.patch("/{task_id}", response_model=TaskSummaryResponse)
async def update_task(
    task_id: str, payload: TaskUpdateRequest, request: Request
) -> TaskSummaryResponse:
    """Update mutable task fields (title, etc.)."""
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        if payload.title is not None:
            task_application.update_task_title(
                task_id,
                user,
                title=payload.title,
                idempotency_key=_idempotency_key(request),
            )
        projection = _get_task_projection_service(request)
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/fork", status_code=201)
async def fork_task(
    task_id: str, payload: TaskForkRequest, request: Request
) -> TaskMutationResponse:
    task_application = _get_task_application_service(request)
    user = get_current_user(request)
    try:
        created = task_application.fork_task(
            task_id,
            user,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            prompt=payload.prompt,
            title=payload.title,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        return _v2_task_mutation_response(projection, user, created)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/retry", status_code=201)
async def retry_task(
    request: Request, task_id: str, payload: TaskRetryRequest | None = None
) -> TaskRetryResponse:
    """Retry through a new Attempt under the existing Task identity."""
    user = get_current_user(request)
    task_application = _get_task_application_service(request)
    _ = payload
    try:
        projection = _get_task_projection_service(request)
        retried = task_application.retry_task(
            task_id, user, idempotency_key=_idempotency_key(request)
        )
        mutation = _v2_task_mutation_response(projection, user, retried)
        return TaskRetryResponse(
            task=mutation.task,
            attempt=mutation.attempt,
            dispatch=mutation.dispatch,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.get("/{task_id}/output")
async def get_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(0, ge=0, le=1000, description="Max items to return; 0 means unlimited"),
) -> TaskOutputResponse:
    user = get_current_user(request)
    projection = _get_task_projection_service(request)
    try:
        fetch_limit = limit + 1 if limit > 0 else 1000
        items = projection.outputs(task_id, user, after_seq=after_seq, limit=fetch_limit)
    except Exception as exc:
        raise _translate_v2_error(exc) from exc
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
    projection = _get_task_projection_service(request)
    user = get_current_user(request)
    try:
        task = _v2_task_summary(projection, task_id, user)
        items = projection.outputs(task_id, user, after_seq=after_seq, limit=limit + 1)
    except Exception as exc:
        raise _translate_v2_error(exc) from exc
    visible_items = items[:limit]
    return TaskMessagesResponse(
        messages=_output_items_to_messages(visible_items, task),
        has_more=len(items) > limit,
        next_sequence=visible_items[-1].seq if len(items) > limit and visible_items else None,
    )


@router.get("/{task_id}/stream")
async def stream_task_output(
    request: Request, task_id: str, after_seq: int = Query(0, ge=0)
) -> StreamingResponse:
    projection = _get_task_projection_service(request)
    user = get_current_user(request)
    try:
        projection.task(task_id, user)
    except Exception as exc:
        raise _translate_v2_error(exc) from exc

    async def v2_event_stream():
        cursor = after_seq
        terminal_statuses = {
            "succeeded",
            "failed",
            "cancelled",
            "stopped",
            "stopped_by_project_archive",
            "stopped_permission_revoked",
        }
        while True:
            if await request.is_disconnected():
                break
            try:
                items = projection.outputs(task_id, user, after_seq=cursor, limit=1000)
                task = _v2_task_summary(projection, task_id, user)
            except (DomainNotFoundError, DomainPermissionError):
                break
            for item in items:
                cursor = item.seq
                event_payload = TaskOutputItemResponse(
                    task_id=item.task_id,
                    kind=item.kind,
                    content=item.content,
                    seq=item.seq,
                    created_at=item.created_at.isoformat(),
                ).model_dump()
                yield f"event: output\ndata: {json.dumps(event_payload, ensure_ascii=True)}\n\n"
            if not items and task.status in terminal_statuses:
                yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'status': task.status})}\n\n"
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(v2_event_stream(), media_type="text/event-stream")

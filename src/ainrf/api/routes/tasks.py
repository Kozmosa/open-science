from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
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
from ainrf.api.idempotency import require_idempotency_key
from ainrf.projects import ProjectNotFoundError, ProjectRegistryService
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
from ainrf.auth.permissions import (
    check_resource_ownership,
    get_current_user,
)
from ainrf.domain import DomainPermissionError, TaskApplicationService, TaskProjectionService
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import DomainModelMode, MaintenanceModeError

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
    if request.app.state.api_config.domain_model_mode is not DomainModelMode.V2:
        return None
    if service is None or domain is None or not domain.v2_ready():
        # v2 processes intentionally do not initialize the legacy in-process
        # scheduler.  Falling through to the legacy branch would therefore
        # turn a cutover-fuse failure into a misleading 500 (or, worse, a
        # future split-brain write if that service were ever wired again).
        raise HTTPException(status_code=503, detail="Task domain v2 is not ready")
    if not isinstance(service, TaskApplicationService):
        raise HTTPException(status_code=500, detail="Task application service is invalid")
    return service


def _get_task_projection_service(request: Request) -> TaskProjectionService | None:
    """Return the v2 SQLite projection only when Task writes are v2-gated."""

    if _get_task_application_service(request) is None:
        return None
    service = getattr(request.app.state, "task_projection_service", None)
    if service is None:
        service = TaskProjectionService(request.app.state.api_config.state_root)
        request.app.state.task_projection_service = service
    if not isinstance(service, TaskProjectionService):
        raise HTTPException(status_code=500, detail="Task projection service is invalid")
    return service


def _idempotency_key(request: Request, body_key: str | None = None) -> str:
    """Prefer the formal header while accepting the legacy body field safely."""

    return require_idempotency_key(request, body_key)


def _translate_v2_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail="Task permission denied")
    if isinstance(exc, (DomainNotFoundError, TaskNotFoundError)):
        return HTTPException(status_code=404, detail="Task not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected Task domain error")


def _v2_task_summary(
    projection: TaskProjectionService,
    task_id: str,
    user: dict[str, object],
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
    return TaskMutationResponse(
        **task.model_dump(),
        task=task,
        attempt=attempt,
        dispatch=dispatch,
    )


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
    task: Task | TaskSummaryResponse,
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
async def create_task(
    request: Request,
    payload: TaskCreateRequest,
    response: Response,
) -> TaskSummaryResponse | TaskMutationResponse:
    user = get_current_user(request)

    task_application = _get_task_application_service(request)
    if task_application is not None:
        if not payload.project_id:
            raise HTTPException(
                status_code=409, detail="v2 Task creation requires an explicit Project"
            )
        if payload.research_agent_profile is not None:
            raise HTTPException(
                status_code=409,
                detail="v2 Task creation does not accept legacy research_agent_profile overrides",
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
                environment_id=payload.environment_id,
                user_skills=payload.skills,
                user_mcp_servers=payload.mcp_servers,
                idempotency_key=_idempotency_key(request, payload.idempotency_key),
            )
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            result = _v2_task_mutation_response(projection, user, created)
            if payload.environment_id is not None:
                mark_deprecated(
                    response,
                    route="tasks.create.environment_id",
                    replacement="POST /tasks without environment_id",
                )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service = _get_service(request)
    if payload.environment_id is None:
        raise HTTPException(status_code=422, detail="environment_id is required before v2 cutover")

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
    projection = _get_task_projection_service(request)
    if projection is not None:
        try:
            tasks = projection.list_tasks(
                user,
                project_id=project_id,
                include_archived=include_archived,
                limit=limit,
                sort=sort,
            )
        except Exception as exc:
            raise _translate_v2_error(exc) from exc
        return TaskListResponse(
            items=[TaskSummaryResponse.model_validate(task) for task in tasks],
            total=len(tasks),
        )

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
    projection = _get_task_projection_service(request)
    if projection is not None:
        try:
            return TaskTokenUsageSummaryResponse.model_validate(
                projection.token_usage_summary(
                    user,
                    include_archived=include_archived,
                )
            )
        except Exception as exc:
            raise _translate_v2_error(exc) from exc
    service = _get_service(request)
    summary = service.token_usage_summary(
        user_id=_task_list_owner_filter(user),
        include_archived=include_archived,
    )
    return TaskTokenUsageSummaryResponse.model_validate(summary)


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str) -> TaskSummaryResponse:
    projection = _get_task_projection_service(request)
    if projection is not None:
        try:
            return _v2_task_summary(projection, task_id, get_current_user(request))
        except Exception as exc:
            raise _translate_v2_error(exc) from exc
    _, task = _assert_task_owner(request, task_id)
    return _task_to_response(task, _get_service(request))


@router.get("/{task_id}/attempts", response_model=TaskAttemptListResponse)
async def list_task_attempts(request: Request, task_id: str) -> TaskAttemptListResponse:
    """Return the durable Attempt history for a Task in v2 mode."""

    projection = _get_task_projection_service(request)
    if projection is None:
        raise HTTPException(status_code=404, detail="Task Attempt projection is unavailable")
    try:
        return TaskAttemptListResponse.model_validate(
            {"items": projection.attempts(task_id, get_current_user(request))}
        )
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post(
    "/{task_id}/attempts/{attempt_id}/resolve-launch-unknown",
    response_model=TaskAttemptResponse,
)
async def resolve_launch_unknown_attempt(
    request: Request,
    task_id: str,
    attempt_id: str,
) -> TaskAttemptResponse:
    """Close a manually investigated unknown launch without re-launching it."""

    task_application = _get_task_application_service(request)
    if task_application is None:
        raise HTTPException(
            status_code=404,
            detail="launch_unknown resolution is unavailable before v2 cutover",
        )
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
    body_key = raw_payload.get("idempotency_key")
    if body_key is not None and not isinstance(body_key, str):
        raise HTTPException(status_code=422, detail="idempotency_key must be a string")
    try:
        task_application.resolve_launch_unknown(
            task_id,
            attempt_id,
            get_current_user(request),
            reason=reason,
            idempotency_key=_idempotency_key(request, body_key),
        )
        projection = _get_task_projection_service(request)
        if projection is None:
            raise HTTPException(status_code=503, detail="Task projection is unavailable")
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
    if projection is not None:
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
    if task_application is not None:
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

    service, _ = _assert_task_owner(request, task_id)

    try:
        await service.cancel_running_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/pause")
async def pause_task(request: Request, task_id: str) -> TaskPauseResponse:
    task_application = _get_task_application_service(request)
    if task_application is not None:
        user = get_current_user(request)
        try:
            task_application.pause_task(
                task_id,
                user,
                idempotency_key=_idempotency_key(request),
            )
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            task = _v2_task_summary(projection, task_id, user)
            return TaskPauseResponse(task_id=task_id, status=task.status)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service, _ = _assert_task_owner(request, task_id)
    try:
        task = await service.pause_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskPauseResponse(task_id=task.task_id, status=task.status.value)


@router.post("/{task_id}/resume")
async def resume_task(request: Request, task_id: str) -> TaskResumeResponse:
    task_application = _get_task_application_service(request)
    if task_application is not None:
        user = get_current_user(request)
        try:
            task_application.resume_task(
                task_id,
                user,
                idempotency_key=_idempotency_key(request),
            )
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            task = _v2_task_summary(projection, task_id, user)
            return TaskResumeResponse(task_id=task_id, status=task.status)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service, _ = _assert_task_owner(request, task_id)
    try:
        task = await service.resume_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskResumeResponse(task_id=task.task_id, status=task.status.value)


async def _continue_task(
    request: Request,
    task_id: str,
    payload: TaskPromptRequest,
) -> TaskPromptSendResponse:
    task_application = _get_task_application_service(request)
    if task_application is not None:
        try:
            result = task_application.continue_task(
                task_id,
                get_current_user(request),
                prompt=payload.prompt,
                idempotency_key=_idempotency_key(request, payload.idempotency_key),
            )
            sequence = result.get("message_sequence")
            if not isinstance(sequence, int):
                raise HTTPException(
                    status_code=500, detail="Task continuation result is incomplete"
                )
            return TaskPromptSendResponse(task_id=task_id, sequence=sequence)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service, _ = _assert_task_owner(request, task_id)
    try:
        event = await service.send_prompt(task_id, payload.prompt)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskPromptSendResponse(task_id=task_id, sequence=event.seq)


@router.post("/{task_id}/continue")
async def continue_task(
    request: Request,
    task_id: str,
    payload: TaskPromptRequest,
) -> TaskPromptSendResponse:
    """Append a Task input or create a durable continuation Attempt."""

    return await _continue_task(request, task_id, payload)


@router.post("/{task_id}/prompt")
async def send_task_prompt(
    request: Request,
    task_id: str,
    payload: TaskPromptRequest,
    response: Response,
) -> TaskPromptSendResponse:
    result = await _continue_task(request, task_id, payload)
    if _get_task_application_service(request) is not None:
        mark_deprecated(
            response,
            route="tasks.prompt",
            replacement=f"POST /tasks/{task_id}/continue",
        )
    return result


async def _archive_task(
    request: Request,
    task_id: str,
    *,
    pending_response: Response | None = None,
) -> TaskSummaryResponse:
    """Archive a Task through the v2 application service when enabled."""

    task_application = _get_task_application_service(request)
    if task_application is not None:
        user = get_current_user(request)
        try:
            archive_result = task_application.archive_task(
                task_id,
                user,
                reason="user_archived",
                idempotency_key=_idempotency_key(request),
            )
            if archive_result.get("archive_pending") is True and pending_response is not None:
                pending_response.status_code = status.HTTP_202_ACCEPTED
                pending_response.headers["X-OpenScience-Archive-State"] = "pending"
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            return _v2_task_summary(projection, task_id, user)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service, _ = _assert_task_owner(request, task_id)
    task = service.get_task(task_id)
    try:
        if task.status in {TaskStatus.QUEUED, TaskStatus.STARTING, TaskStatus.RUNNING}:
            archived = await service.cancel_running_task(task_id)
        else:
            archived = service.archive_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _task_to_response(archived, service)


@router.post("/{task_id}/archive", status_code=200)
async def archive_task_v2(
    request: Request,
    task_id: str,
    response: Response,
) -> TaskSummaryResponse:
    """Standard explicit Task archive endpoint."""

    return await _archive_task(request, task_id, pending_response=response)


@router.post("/{task_id}/unarchive", status_code=200)
async def unarchive_task(request: Request, task_id: str) -> TaskSummaryResponse:
    task_application = _get_task_application_service(request)
    if task_application is None:
        raise HTTPException(
            status_code=404, detail="Task unarchive is unavailable before v2 cutover"
        )
    user = get_current_user(request)
    try:
        task_application.unarchive_task(
            task_id,
            user,
            idempotency_key=_idempotency_key(request),
        )
        projection = _get_task_projection_service(request)
        if projection is None:
            raise HTTPException(status_code=503, detail="Task projection is unavailable")
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.delete("/{task_id}", status_code=200)
async def archive_task(
    request: Request,
    task_id: str,
    response: Response,
) -> TaskSummaryResponse:
    """Compatibility alias for ``POST /tasks/{task_id}/archive``."""

    result = await _archive_task(request, task_id)
    if _get_task_application_service(request) is not None:
        mark_deprecated(
            response,
            route="tasks.archive.delete",
            replacement=f"POST /tasks/{task_id}/archive",
        )
    return result


@router.delete("/{task_id}/permanent", status_code=204)
async def delete_task(request: Request, task_id: str) -> None:
    """Permanently delete a task."""
    projection = _get_task_projection_service(request)
    if projection is not None:
        try:
            projection.task(task_id, get_current_user(request))
        except Exception as exc:
            raise _translate_v2_error(exc) from exc
        raise HTTPException(
            status_code=410,
            detail="Permanent Task deletion is unavailable; archive the Task instead",
            headers=deprecation_headers(
                route="tasks.permanent_delete",
                replacement=f"POST /tasks/{task_id}/archive",
            ),
        )
    service, _ = _assert_task_owner(request, task_id)
    service.delete_task(task_id)


@router.patch("/{task_id}/project", response_model=TaskSummaryResponse)
async def update_task_project(
    task_id: str,
    payload: TaskUpdateProjectRequest,
    request: Request,
    response: Response,
) -> TaskSummaryResponse:
    """Compatibility alias for the explicit v2 Task move contract."""

    task_application = _get_task_application_service(request)
    if task_application is not None:
        if payload.context_version_id is None:
            raise HTTPException(
                status_code=422,
                detail="context_version_id is required when moving a v2 Task",
            )
        user = get_current_user(request)
        try:
            task_application.move_task(
                task_id,
                user,
                project_id=payload.project_id,
                context_version_id=payload.context_version_id,
                idempotency_key=_idempotency_key(request, payload.idempotency_key),
            )
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            result = _v2_task_summary(projection, task_id, user)
            mark_deprecated(
                response,
                route="tasks.update_project",
                replacement=f"POST /tasks/{task_id}/move",
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

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


@router.post("/{task_id}/move", response_model=TaskSummaryResponse)
async def move_task(
    task_id: str,
    payload: TaskMoveRequest,
    request: Request,
) -> TaskSummaryResponse:
    task_application = _get_task_application_service(request)
    if task_application is None:
        raise HTTPException(status_code=404, detail="Task move is unavailable before v2 cutover")
    user = get_current_user(request)
    try:
        task_application.move_task(
            task_id,
            user,
            project_id=payload.project_id,
            context_version_id=payload.context_version_id,
            idempotency_key=_idempotency_key(request, payload.idempotency_key),
        )
        projection = _get_task_projection_service(request)
        if projection is None:
            raise HTTPException(status_code=503, detail="Task projection is unavailable")
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.patch("/{task_id}", response_model=TaskSummaryResponse)
async def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
) -> TaskSummaryResponse:
    """Update mutable task fields (title, etc.)."""
    task_application = _get_task_application_service(request)
    if task_application is not None:
        user = get_current_user(request)
        try:
            if payload.title is not None:
                task_application.update_task_title(
                    task_id,
                    user,
                    title=payload.title,
                    idempotency_key=_idempotency_key(request, payload.idempotency_key),
                )
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            return _v2_task_summary(projection, task_id, user)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service, _ = _assert_task_owner(request, task_id)
    updated = service.update_task(task_id, title=payload.title)
    return _task_to_response(updated, service)


@router.post("/{task_id}/fork", status_code=201)
async def fork_task(
    task_id: str,
    payload: TaskForkRequest,
    request: Request,
) -> TaskMutationResponse:
    task_application = _get_task_application_service(request)
    if task_application is None:
        raise HTTPException(status_code=404, detail="Task fork is unavailable before v2 cutover")
    user = get_current_user(request)
    try:
        created = task_application.fork_task(
            task_id,
            user,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            prompt=payload.prompt,
            title=payload.title,
            idempotency_key=_idempotency_key(request, payload.idempotency_key),
        )
        projection = _get_task_projection_service(request)
        if projection is None:
            raise HTTPException(status_code=503, detail="Task projection is unavailable")
        return _v2_task_mutation_response(projection, user, created)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/retry", status_code=201)
async def retry_task(
    request: Request,
    task_id: str,
    response: Response,
    payload: TaskRetryRequest | None = None,
) -> TaskRetryResponse:
    """Retry through a new Attempt under the existing Task identity."""
    user = get_current_user(request)

    task_application = _get_task_application_service(request)
    if task_application is not None:
        body = payload or TaskRetryRequest()
        try:
            projection = _get_task_projection_service(request)
            if projection is None:
                raise HTTPException(status_code=503, detail="Task projection is unavailable")
            original = _v2_task_summary(projection, task_id, user)
            if body.task_input is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Retry does not accept task_input; use Task continue instead",
                )
            if body.environment_id is not None and body.environment_id != original.environment_id:
                raise HTTPException(
                    status_code=409,
                    detail="environment_id must equal the Task Workspace derived Environment",
                )
            retried = task_application.retry_task(
                task_id,
                user,
                idempotency_key=_idempotency_key(request, body.idempotency_key),
            )
            mutation = _v2_task_mutation_response(projection, user, retried)
            mark_deprecated(
                response,
                route="tasks.retry.new_task",
                replacement=f"GET /tasks/{task_id}/attempts",
            )
            if body.environment_id is not None:
                mark_deprecated(
                    response,
                    route="tasks.retry.environment_id",
                    replacement="POST /tasks/{task_id}/retry without environment_id",
                )
            return TaskRetryResponse(
                new_task=mutation.task,
                archived_task_id=None,
                edge_id="",
                task=mutation.task,
                attempt=mutation.attempt,
                dispatch=mutation.dispatch,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_v2_error(exc) from exc

    service = _get_service(request)
    try:
        old_task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    check_resource_ownership(user, old_task.owner_user_id)
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
    projection = _get_task_projection_service(request)
    if projection is not None:
        try:
            fetch_limit = limit + 1 if limit > 0 else 1000
            items = projection.outputs(
                task_id,
                user,
                after_seq=after_seq,
                limit=fetch_limit,
            )
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
    projection = _get_task_projection_service(request)
    if projection is not None:
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

    service, task = _assert_task_owner(request, task_id)
    items = service.get_output(task_id, after_seq=after_seq, limit=limit + 1)
    visible_items = items[:limit]
    return TaskMessagesResponse(
        messages=_output_items_to_messages(visible_items, task),
        has_more=len(items) > limit,
        next_sequence=visible_items[-1].seq if len(items) > limit and visible_items else None,
    )


@router.get("/{task_id}/stream")
async def stream_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
) -> StreamingResponse:
    projection = _get_task_projection_service(request)
    if projection is not None:
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
                    yield (
                        f"event: output\ndata: {json.dumps(event_payload, ensure_ascii=True)}\n\n"
                    )
                if not items and task.status in terminal_statuses:
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'task_id': task_id, 'status': task.status})}\n\n"
                    )
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(v2_event_stream(), media_type="text/event-stream")

    service, _ = _assert_task_stream_access(request, task_id)

    async def event_stream():
        cursor = after_seq
        while True:
            if await request.is_disconnected():
                break
            items = service.get_output(task_id, after_seq=cursor)
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

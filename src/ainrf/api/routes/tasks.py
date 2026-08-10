from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.schemas import (
    ConversationTaskMutationResponse,
    TaskCreateRequest,
    TaskForkRequest,
    TaskListResponse,
    TaskHealthResponse,
    TaskMoveRequest,
    TaskSummaryResponse,
    TaskTokenUsageSummaryResponse,
    TaskUpdateRequest,
    TurnSubmissionResponse,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import (
    ConversationApplicationService,
    DomainPermissionError,
    TaskProjectionService,
)
from ainrf.domain.conversation_contracts import ConversationContractError
from ainrf.domain.service import DomainNotFoundError
from ainrf.domain_control import MaintenanceModeError

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_conversation_application_service(request: Request) -> ConversationApplicationService:
    service = getattr(request.app.state, "conversation_application_service", None)
    if service is None or not isinstance(service, ConversationApplicationService):
        raise HTTPException(status_code=503, detail="Conversation Module is unavailable")
    if not service.ready():
        raise HTTPException(status_code=503, detail="Conversation Module is not ready")
    return service


def _get_task_projection_service(request: Request) -> TaskProjectionService:
    """Return the authoritative SQLite Task projection."""
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
    if isinstance(exc, ConversationContractError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected Task domain error")


def _v2_task_summary(
    projection: TaskProjectionService, task_id: str, user: dict[str, object]
) -> TaskSummaryResponse:
    return TaskSummaryResponse.model_validate(projection.task(task_id, user))


@router.post("", status_code=202)
async def create_task(
    request: Request, payload: TaskCreateRequest
) -> ConversationTaskMutationResponse:
    user = get_current_user(request)
    conversation = _get_conversation_application_service(request)
    if not payload.project_id:
        raise HTTPException(status_code=409, detail="v2 Task creation requires an explicit Project")
    try:
        created = conversation.create_task(
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
        task = _v2_task_summary(
            _get_task_projection_service(request), str(created["task_id"]), user
        )
        return ConversationTaskMutationResponse(
            task=task,
            submission=TurnSubmissionResponse.model_validate(created),
        )
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
    conversation = _get_conversation_application_service(request)
    try:
        conversation.cancel_task(
            task_id,
            get_current_user(request),
            idempotency_key=_idempotency_key(request),
        )
        return
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/complete", response_model=TaskSummaryResponse)
async def complete_task(request: Request, task_id: str) -> TaskSummaryResponse:
    """Mark Task business work complete and return its canonical projection."""

    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        conversation.complete_task(
            task_id,
            user,
            idempotency_key=_idempotency_key(request),
        )
        return _v2_task_summary(_get_task_projection_service(request), task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/reopen", response_model=TaskSummaryResponse)
async def reopen_task(request: Request, task_id: str) -> TaskSummaryResponse:
    """Reopen a completed or cancelled Task and return its canonical projection."""

    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        conversation.reopen_task(
            task_id,
            user,
            idempotency_key=_idempotency_key(request),
        )
        return _v2_task_summary(_get_task_projection_service(request), task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


async def _archive_task(
    request: Request, task_id: str, *, pending_response: Response | None = None
) -> TaskSummaryResponse:
    """Archive a Task through the v2 application service when enabled."""
    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        archive_result = conversation.archive_task(
            task_id, user, idempotency_key=_idempotency_key(request)
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
    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        conversation.unarchive_task(task_id, user, idempotency_key=_idempotency_key(request))
        projection = _get_task_projection_service(request)
        return _v2_task_summary(projection, task_id, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc


@router.post("/{task_id}/move", response_model=TaskSummaryResponse)
async def move_task(
    task_id: str, payload: TaskMoveRequest, request: Request
) -> TaskSummaryResponse:
    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        conversation.move_task(
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
    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    try:
        if payload.title is not None:
            conversation.update_task_title(
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


@router.post("/{task_id}/fork", status_code=202)
async def fork_task_compatibility(
    task_id: str, payload: TaskForkRequest, request: Request
) -> ConversationTaskMutationResponse:
    """Map the legacy one-shot fork transport to a new Conversation Task admission."""

    conversation = _get_conversation_application_service(request)
    user = get_current_user(request)
    projection = _get_task_projection_service(request)
    try:
        source = projection.task(task_id, user)
        created = conversation.create_task(
            user,
            project_id=payload.project_id or str(source["project_id"]),
            workspace_id=payload.workspace_id or str(source["workspace_id"]),
            title=payload.title or f"Fork of {source['title']}",
            prompt=payload.prompt or str(source["prompt"]),
            researcher_type=str(source["researcher_type"]),
            harness_engine=str(source["harness_engine"]),
            idempotency_key=_idempotency_key(request),
        )
        task = _v2_task_summary(projection, str(created["task_id"]), user)
        return ConversationTaskMutationResponse(
            task=task,
            submission=TurnSubmissionResponse.model_validate(created),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_v2_error(exc) from exc

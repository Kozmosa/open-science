from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from ainrf.agentic_researcher import (
    AgenticResearcherService,
    HarnessEngineType,
    TaskStatus,
    aris,
    vanilla,
)
from ainrf.agentic_researcher.service import TaskNotFoundError, TaskOperationError
from ainrf.api.schemas import (
    TaskCreateRequest,
    TaskListResponse,
    TaskOutputItemResponse,
    TaskOutputResponse,
    TaskPauseResponse,
    TaskPromptRequest,
    TaskPromptSendResponse,
    TaskResumeResponse,
    TaskRetryResponse,
    TaskSummaryResponse,
)
from ainrf.auth.permissions import (
    check_resource_ownership,
    get_current_user,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_service(request: Request) -> AgenticResearcherService:
    service = getattr(request.app.state, "agentic_researcher_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="AgenticResearcher service not initialized")
    return service


def _task_to_response(task) -> TaskSummaryResponse:
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
    )


def _assert_task_owner(request: Request, task_id: str):
    user = get_current_user(request)
    service = _get_service(request)
    try:
        task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    check_resource_ownership(user, task.owner_user_id)
    return service, task


@router.post("", status_code=201)
async def create_task(request: Request, payload: TaskCreateRequest) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_service(request)

    engine_type = HarnessEngineType(payload.harness_engine)
    if payload.researcher_type == "vanilla":
        researcher = vanilla(engine=engine_type, user_skills=payload.skills)
    elif payload.researcher_type == "aris-researcher":
        researcher = aris(engine=engine_type)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown researcher type: {payload.researcher_type}")

    try:
        task = service.create_task(
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            environment_id=payload.environment_id,
            researcher=researcher,
            prompt=payload.prompt,
            owner_user_id=user["id"],
            title=payload.title,
        )
        service.schedule_task(task.task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _task_to_response(task)


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
        user_id=user["id"],
        include_archived=include_archived,
        limit=limit,
        sort=sort,
    )
    return TaskListResponse(
        items=[_task_to_response(t) for t in tasks],
        total=len(tasks),
    )


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str) -> TaskSummaryResponse:
    _, task = _assert_task_owner(request, task_id)
    return _task_to_response(task)


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

    try:
        cancelled = await service.cancel_running_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _task_to_response(cancelled)


@router.delete("/{task_id}/permanent", status_code=204)
async def delete_task(request: Request, task_id: str) -> None:
    """Permanently delete a task."""
    service, _ = _assert_task_owner(request, task_id)
    service.delete_task(task_id)


@router.post("/{task_id}/retry", status_code=201)
async def retry_task(request: Request, task_id: str) -> TaskRetryResponse:
    """Retry a failed or cancelled task by creating a new copy."""
    user = get_current_user(request)
    service = _get_service(request)

    try:
        old_task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    check_resource_ownership(user, old_task.owner_user_id)

    try:
        new_task = service.retry_task(task_id)
    except TaskOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return TaskRetryResponse(
        new_task=_task_to_response(new_task),
        archived_task_id=task_id,
        edge_id="",
    )


@router.get("/{task_id}/output")
async def get_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
) -> TaskOutputResponse:
    user = get_current_user(request)
    service = _get_service(request)

    try:
        task = service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    check_resource_ownership(user, task.owner_user_id)

    items = service.get_output(task_id, after_seq=after_seq)
    next_seq = items[-1].seq if items else after_seq
    return TaskOutputResponse(
        items=[
            TaskOutputItemResponse(
                task_id=item.task_id,
                kind=item.kind,
                content=item.content,
                seq=item.seq,
                created_at=item.created_at.isoformat(),
            )
            for item in items
        ],
        next_seq=next_seq,
    )


@router.get("/{task_id}/stream")
async def stream_task_output(
    request: Request,
    task_id: str,
    after_seq: int = Query(0, ge=0),
) -> StreamingResponse:
    service, _ = _assert_task_owner(request, task_id)

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

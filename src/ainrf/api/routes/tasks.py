from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ainrf.api.schemas import (
    TaskCreateRequest,
    TaskDetailResponse,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
    TaskListResponse,
    TaskOutputEventResponse,
    TaskOutputListResponse,
    TaskSummaryResponse,
)
from ainrf.task_harness import (
    TaskDetail,
    TaskHarnessError,
    TaskHarnessNotFoundError,
    TaskHarnessService,
    TaskListItem,
    TaskOutputPage,
)
from ainrf.workspaces import WorkspaceNotFoundError

router = APIRouter(prefix="/tasks", tags=["tasks"])
task_edges_router = APIRouter(tags=["task-edges"])


def _get_task_harness_service(request: Request) -> TaskHarnessService:
    service = getattr(request.app.state, "task_harness_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="task harness service not initialized")
    return service


def _translate_task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaskHarnessNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=404, detail="Workspace not found")
    if exc.__class__.__name__ == "EnvironmentNotFoundError":
        return HTTPException(status_code=404, detail="Environment not found")
    if isinstance(exc, TaskHarnessError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected task harness error")


def _serialize_task_summary(task: TaskListItem) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "title": task.title,
        "task_profile": task.task_profile,
        "status": task.status.value,
        "workspace_summary": asdict(task.workspace_summary),
        "environment_summary": asdict(task.environment_summary),
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at is not None else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at is not None else None,
        "error_summary": task.error_summary,
        "latest_output_seq": task.latest_output_seq,
        "execution_engine": task.execution_engine,
    }


def _serialize_task_detail(task: TaskDetail) -> dict[str, Any]:
    payload = _serialize_task_summary(
        TaskListItem(
            task_id=task.task_id,
            project_id=task.project_id,
            title=task.title,
            task_profile=task.task_profile,
            status=task.status,
            workspace_summary=task.workspace_summary,
            environment_summary=task.environment_summary,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            error_summary=task.error_summary,
            latest_output_seq=task.latest_output_seq,
            execution_engine=task.execution_engine,
        )
    )
    payload["binding"] = asdict(task.binding) if task.binding is not None else None
    payload["prompt"] = (
        {
            "rendered_prompt": task.prompt.rendered_prompt,
            "layer_order": task.prompt.layer_order,
            "layers": [asdict(layer) for layer in task.prompt.layers],
            "manifest_path": task.prompt.manifest_path,
        }
        if task.prompt is not None
        else None
    )
    payload["runtime"] = asdict(task.runtime) if task.runtime is not None else None
    payload["result"] = {
        "exit_code": task.result.exit_code,
        "failure_category": task.result.failure_category,
        "error_summary": task.result.error_summary,
        "completed_at": task.result.completed_at.isoformat()
        if task.result.completed_at is not None
        else None,
    }
    payload["execution_engine"] = task.execution_engine
    payload["research_agent_profile"] = (
        asdict(task.research_agent_profile) if task.research_agent_profile is not None else None
    )
    payload["task_configuration"] = (
        asdict(task.task_configuration) if task.task_configuration is not None else None
    )
    return payload


def _serialize_output_page(page: TaskOutputPage) -> dict[str, Any]:
    return {
        "items": [
            {
                "task_id": item.task_id,
                "seq": item.seq,
                "kind": item.kind.value,
                "content": item.content,
                "created_at": item.created_at.isoformat(),
            }
            for item in page.items
        ],
        "next_seq": page.next_seq,
    }


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    include_archived: bool = Query(default=False),
) -> TaskListResponse:
    service = _get_task_harness_service(request)
    try:
        items = service.list_tasks(include_archived=include_archived)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskListResponse.model_validate(
        {
            "items": [
                TaskSummaryResponse.model_validate(_serialize_task_summary(item)) for item in items
            ]
        }
    )


@router.post("", response_model=TaskSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreateRequest, request: Request) -> TaskSummaryResponse:
    service = _get_task_harness_service(request)
    try:
        task = service.create_task(
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            environment_id=payload.environment_id,
            task_profile=payload.task_profile,
            task_input=payload.task_input,
            title=payload.title,
            execution_engine=payload.execution_engine,
            auto_connect=payload.auto_connect,
            research_agent_profile=payload.research_agent_profile.model_dump()
            if payload.research_agent_profile is not None
            else None,
            task_configuration=payload.task_configuration.model_dump()
            if payload.task_configuration is not None
            else None,
        )
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def read_task(task_id: str, request: Request) -> TaskDetailResponse:
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskDetailResponse.model_validate(_serialize_task_detail(task))


@router.get("/{task_id}/output", response_model=TaskOutputListResponse)
async def read_task_output(
    task_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
) -> TaskOutputListResponse:
    service = _get_task_harness_service(request)
    try:
        page = service.get_output(task_id, after_seq=after_seq)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskOutputListResponse.model_validate(_serialize_output_page(page))


@router.get("/{task_id}/stream")
async def stream_task_output(
    task_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    service = _get_task_harness_service(request)
    try:
        service.get_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    async def event_stream() -> Any:
        next_seq = after_seq
        while True:
            if await request.is_disconnected():
                return
            page = service.get_output(task_id, after_seq=next_seq)
            if page.items:
                for item in page.items:
                    payload = TaskOutputEventResponse.model_validate(
                        {
                            "task_id": item.task_id,
                            "seq": item.seq,
                            "kind": item.kind.value,
                            "content": item.content,
                            "created_at": item.created_at.isoformat(),
                        }
                    )
                    yield f"id: {item.seq}\ndata: {payload.model_dump_json()}\n\n"
                next_seq = page.next_seq
                continue
            task = service.get_task(task_id)
            if task.status.value in {"succeeded", "failed"} and next_seq >= task.latest_output_seq:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/{task_id}", response_model=TaskSummaryResponse)
async def archive_task(task_id: str, request: Request) -> TaskSummaryResponse:
    service = _get_task_harness_service(request)
    try:
        task = service.archive_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.post("/{task_id}/cancel", response_model=TaskSummaryResponse)
async def cancel_task(task_id: str, request: Request) -> TaskSummaryResponse:
    service = _get_task_harness_service(request)
    try:
        task = await service.cancel_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@task_edges_router.get("/projects/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_task_edges(project_id: str, request: Request) -> TaskEdgeListResponse:
    service = _get_task_harness_service(request)
    try:
        edges = service.get_task_edges(project_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeListResponse.model_validate(
        {
            "items": [
                {
                    "edge_id": edge.edge_id,
                    "project_id": edge.project_id,
                    "source_task_id": edge.source_task_id,
                    "target_task_id": edge.target_task_id,
                    "created_at": edge.created_at.isoformat(),
                }
                for edge in edges
            ]
        }
    )


@task_edges_router.post(
    "/projects/{project_id}/task-edges",
    response_model=TaskEdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_edge(
    project_id: str, payload: TaskEdgeCreateRequest, request: Request
) -> TaskEdgeResponse:
    service = _get_task_harness_service(request)
    try:
        edge = service.create_task_edge(
            project_id=project_id,
            source_task_id=payload.source_task_id,
            target_task_id=payload.target_task_id,
        )
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeResponse.model_validate(
        {
            "edge_id": edge.edge_id,
            "project_id": edge.project_id,
            "source_task_id": edge.source_task_id,
            "target_task_id": edge.target_task_id,
            "created_at": edge.created_at.isoformat(),
        }
    )


@task_edges_router.delete("/task-edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request) -> None:
    service = _get_task_harness_service(request)
    try:
        service.delete_task_edge(edge_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc


@task_edges_router.get("/projects/{project_id}/tasks", response_model=TaskListResponse)
async def list_project_tasks(
    project_id: str,
    request: Request,
    include_archived: bool = Query(default=False),
) -> TaskListResponse:
    service = _get_task_harness_service(request)
    try:
        items = service.list_project_tasks(project_id, include_archived=include_archived)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskListResponse.model_validate(
        {
            "items": [
                TaskSummaryResponse.model_validate(_serialize_task_summary(item)) for item in items
            ]
        }
    )

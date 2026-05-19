from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse

from ainrf.auth.permissions import check_resource_owner, get_current_user, is_admin
from ainrf.api.schemas import (
    TaskCreateRequest,
    TaskDetailResponse,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
    TaskListResponse,
    TaskMessagesResponse,
    TaskOutputEventResponse,
    TaskOutputListResponse,
    TaskPromptRequest,
    TaskPromptSendResponse,
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
        "session_id": task.session_id,
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


def _convert_output_event_to_message(item: Any) -> dict[str, Any] | None:
    import json

    try:
        payload = (
            json.loads(item.content) if item.content.startswith("{") else {"content": item.content}
        )
    except json.JSONDecodeError:
        payload = {"content": item.content}

    msg_id = f"{item.task_id}-{item.seq}"
    kind = item.kind.value if hasattr(item.kind, "value") else str(item.kind)

    if kind == "message":
        role = payload.get("role", "assistant")
        return {
            "id": msg_id,
            "type": role,
            "content": payload.get("content", ""),
            "metadata": {"timestamp": item.created_at.isoformat(), "sequence": item.seq},
        }
    elif kind == "thinking":
        return {
            "id": msg_id,
            "type": "thinking",
            "content": payload.get("content", ""),
            "metadata": {
                "timestamp": item.created_at.isoformat(),
                "sequence": item.seq,
                "isFolded": True,
            },
        }
    elif kind == "tool_call":
        return {
            "id": msg_id,
            "type": "tool_call",
            "content": {"name": payload.get("name"), "arguments": payload.get("arguments")},
            "metadata": {
                "timestamp": item.created_at.isoformat(),
                "sequence": item.seq,
                "isFolded": True,
            },
        }
    elif kind == "tool_result":
        return {
            "id": msg_id,
            "type": "tool_result",
            "content": {
                "tool_use_id": payload.get("tool_use_id"),
                "content": payload.get("content"),
            },
            "metadata": {
                "timestamp": item.created_at.isoformat(),
                "sequence": item.seq,
                "isFolded": True,
            },
        }
    elif kind in ("system", "lifecycle"):
        return {
            "id": msg_id,
            "type": "system_event",
            "content": payload.get("subtype") or payload.get("content", kind),
            "metadata": {
                "timestamp": item.created_at.isoformat(),
                "sequence": item.seq,
                "payload": payload,
            },
        }
    elif kind == "stdout":
        return {
            "id": msg_id,
            "type": "assistant",
            "content": payload.get("content", item.content),
            "metadata": {"timestamp": item.created_at.isoformat(), "sequence": item.seq},
        }
    elif kind == "stderr":
        return {
            "id": msg_id,
            "type": "system_event",
            "content": f"[stderr] {payload.get('content', item.content)}",
            "metadata": {"timestamp": item.created_at.isoformat(), "sequence": item.seq},
        }

    return None


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    include_archived: bool = Query(default=False),
) -> TaskListResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        if is_admin(user):
            items = service.list_tasks(include_archived=include_archived)
        else:
            items = service.list_tasks(include_archived=include_archived, owner_user_id=user["id"])
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
    user = get_current_user(request)
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
            session_id=payload.session_id,
            owner_user_id=user["id"],
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
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskDetailResponse.model_validate(_serialize_task_detail(task))


@router.get("/{task_id}/output", response_model=TaskOutputListResponse)
async def read_task_output(
    task_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
) -> TaskOutputListResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
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
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
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
            if (
                task.status.value in {"succeeded", "failed", "cancelled"}
                and next_seq >= task.latest_output_seq
            ):
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/{task_id}", response_model=TaskSummaryResponse)
async def archive_task(task_id: str, request: Request) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        task = service.archive_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.delete("/{task_id}/permanent", status_code=204)
async def delete_task(task_id: str, request: Request) -> Response:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        service.delete_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return Response(status_code=204)


@router.post("/{task_id}/cancel", response_model=TaskSummaryResponse)
async def cancel_task(task_id: str, request: Request) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        task = await service.cancel_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.post("/{task_id}/pause", response_model=TaskSummaryResponse)
async def pause_task(task_id: str, request: Request) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        task = await service.pause_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.post("/{task_id}/resume", response_model=TaskSummaryResponse)
async def resume_task(task_id: str, request: Request) -> TaskSummaryResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        task = await service.resume_task(task_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskSummaryResponse.model_validate(_serialize_task_summary(task))


@router.post("/{task_id}/prompt", response_model=TaskPromptSendResponse)
async def send_task_prompt(
    task_id: str, payload: TaskPromptRequest, request: Request
) -> TaskPromptSendResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        seq = await service.send_prompt(task_id, payload.prompt)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskPromptSendResponse(task_id=task_id, sequence=seq)


@router.get("/{task_id}/messages", response_model=TaskMessagesResponse)
async def get_task_messages(
    task_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> TaskMessagesResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        task = service.get_task(task_id)
        if not check_resource_owner(user, task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        page = service.get_output(task_id, after_seq=after_seq, limit=limit)
    except Exception as exc:
        raise _translate_task_error(exc) from exc

    messages = []
    for item in page.items:
        msg = _convert_output_event_to_message(item)
        if msg is not None:
            messages.append(msg)

    return TaskMessagesResponse(
        messages=messages,
        has_more=page.has_more,
        next_sequence=page.next_seq if page.has_more else None,
    )


@task_edges_router.get("/projects/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_task_edges(project_id: str, request: Request) -> TaskEdgeListResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    if not is_admin(user):
        auth_svc = getattr(request.app.state, "auth_service", None)
        if auth_svc is not None:
            user_project_ids = auth_svc.get_user_project_ids(user["id"])
            if project_id not in user_project_ids and project_id != "default":
                raise HTTPException(status_code=404, detail="Project not found")
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
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    if not is_admin(user):
        auth_svc = getattr(request.app.state, "auth_service", None)
        if auth_svc is not None:
            user_project_ids = auth_svc.get_user_project_ids(user["id"])
            if project_id not in user_project_ids and project_id != "default":
                raise HTTPException(status_code=404, detail="Project not found")
    # Verify the user can access both source and target tasks
    try:
        source_task = service.get_task(payload.source_task_id)
        if not check_resource_owner(user, source_task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        target_task = service.get_task(payload.target_task_id)
        if not check_resource_owner(user, target_task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task not found")
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
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        edge = service.get_task_edge(edge_id)
        source_task = service.get_task(edge.source_task_id)
        if not check_resource_owner(user, source_task.owner_user_id):
            raise HTTPException(status_code=404, detail="Task edge not found")
        service.delete_task_edge(edge_id)
    except TaskHarnessNotFoundError:
        raise HTTPException(status_code=404, detail="Task edge not found")
    except Exception as exc:
        raise _translate_task_error(exc) from exc


@task_edges_router.get("/projects/{project_id}/tasks", response_model=TaskListResponse)
async def list_project_tasks(
    project_id: str,
    request: Request,
    include_archived: bool = Query(default=False),
) -> TaskListResponse:
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    try:
        if is_admin(user):
            items = service.list_project_tasks(project_id, include_archived=include_archived)
        else:
            items = service.list_project_tasks(
                project_id, include_archived=include_archived, owner_user_id=user["id"]
            )
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskListResponse.model_validate(
        {
            "items": [
                TaskSummaryResponse.model_validate(_serialize_task_summary(item)) for item in items
            ]
        }
    )

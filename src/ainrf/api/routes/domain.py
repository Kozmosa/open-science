"""Mode-gated v2 adapters; legacy routes remain authoritative until B7."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ainrf.api.schemas import (
    ProjectContextCandidateCreateRequest,
    ProjectContextCandidateRejectRequest,
    ProjectContextDraftRequest,
    ProjectContextFragmentCreateRequest,
    TaskContextConfirmRequest,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import (
    DomainPermissionError,
    DomainService,
    ProjectContextService,
    TaskApplicationService,
)
from ainrf.domain_control import DomainModelMode

router = APIRouter(prefix="/domain", tags=["domain-v2"])


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    service = getattr(request.app.state, "domain_service", None)
    mode = request.app.state.api_config.domain_model_mode
    ready = mode is DomainModelMode.V2 and isinstance(service, DomainService) and service.v2_ready()
    context_ready = ready and isinstance(
        getattr(request.app.state, "project_context_service", None), ProjectContextService
    )
    task_ready = ready and isinstance(
        getattr(request.app.state, "task_application_service", None), TaskApplicationService
    )
    workspace_links_ready = ready and all(
        callable(getattr(service, name, None))
        for name in ("attach_workspace", "detach_workspace", "set_primary_workspace")
    )
    return {
        "domain_contract_version": 2 if ready else 1,
        "mode": mode.value,
        "standard_task_create": task_ready,
        "project_context": context_ready,
        "workspace_links": workspace_links_ready,
        "task_attempts": task_ready,
        # B9/B10 have not yet established their durable saga/scheduler
        # contracts.  Existing read helpers do not make those capabilities
        # ready for the frontend.
        "literature_research_task": False,
        "overview_snapshot": False,
    }


@router.get("/overview/today")
async def today_overview(request: Request) -> dict[str, object]:
    _service(request)
    user = get_current_user(request)
    snapshot_service = getattr(request.app.state, "overview_snapshot_service", None)
    if snapshot_service is None:
        raise HTTPException(status_code=500, detail="Overview snapshot service not initialized")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Authenticated user ID is required")
    payload = snapshot_service.latest(user_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No overview snapshot is available")
    return payload


def _service(request: Request) -> DomainService:
    service = getattr(request.app.state, "domain_service", None)
    if service is None or request.app.state.api_config.domain_model_mode is not DomainModelMode.V2:
        raise HTTPException(status_code=404, detail="Domain v2 is unavailable")
    if not service.v2_ready():
        raise HTTPException(status_code=503, detail="Domain v2 cutover is not ready")
    return service


def _context_service(request: Request) -> ProjectContextService:
    _service(request)
    service = getattr(request.app.state, "project_context_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Project Context service is not initialized")
    return service


def _task_application_service(request: Request) -> TaskApplicationService:
    _service(request)
    service = getattr(request.app.state, "task_application_service", None)
    if not isinstance(service, TaskApplicationService):
        raise HTTPException(status_code=503, detail="Task application service is not initialized")
    return service


def _idempotency_key(request: Request, body_key: str | None = None) -> str:
    header_key = request.headers.get("Idempotency-Key")
    if header_key and body_key and header_key != body_key:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key header and body field must match",
        )
    key = header_key or body_key
    if not key:
        raise HTTPException(status_code=409, detail="Idempotency-Key is required")
    return key


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail="Domain permission denied")
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Domain resource not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


@router.post("/projects")
async def create_project(request: Request, payload: dict[str, object]) -> dict[str, object]:
    try:
        description_value = payload.get("description")
        description = description_value if isinstance(description_value, str) else None
        return _service(request).create_project(
            get_current_user(request),
            name=str(payload["name"]),
            description=description,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/workspaces")
async def create_workspace(request: Request, payload: dict[str, object]) -> dict[str, object]:
    try:
        return _service(request).create_workspace(
            get_current_user(request),
            environment_id=str(payload["environment_id"]),
            canonical_path=str(payload["canonical_path"]),
            label=str(payload["label"]),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/workspaces/{workspace_id}")
async def attach_workspace(
    project_id: str, workspace_id: str, request: Request
) -> dict[str, object]:
    try:
        return _service(request).attach_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/projects/{project_id}/primary-workspace/{workspace_id}")
async def set_primary_workspace(
    project_id: str, workspace_id: str, request: Request
) -> dict[str, object]:
    try:
        return _service(request).set_primary_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context")
async def get_project_context(project_id: str, request: Request) -> dict[str, object]:
    try:
        return _context_service(request).get_context(project_id, get_current_user(request))
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/projects/{project_id}/context/draft")
async def save_project_context_draft(
    project_id: str,
    payload: ProjectContextDraftRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return _context_service(request).save_draft(
            project_id, payload.content, get_current_user(request)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/publish")
async def publish_project_context(project_id: str, request: Request) -> dict[str, object]:
    try:
        return _context_service(request).publish(
            project_id,
            get_current_user(request),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context/versions")
async def list_project_context_versions(project_id: str, request: Request) -> dict[str, object]:
    try:
        return {
            "items": _context_service(request).list_versions(project_id, get_current_user(request))
        }
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context/versions/{context_version_id}")
async def get_project_context_version(
    project_id: str, context_version_id: str, request: Request
) -> dict[str, object]:
    try:
        return _context_service(request).get_version(
            project_id, context_version_id, get_current_user(request)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context/versions/{context_version_id}/diff")
async def diff_project_context_version(
    project_id: str,
    context_version_id: str,
    request: Request,
    against: str = Query(..., min_length=1),
) -> dict[str, object]:
    try:
        return _context_service(request).diff_versions(
            project_id,
            against,
            context_version_id,
            get_current_user(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context/candidates")
async def list_project_context_candidates(project_id: str, request: Request) -> dict[str, object]:
    try:
        return {
            "items": _context_service(request).list_candidates(
                project_id, get_current_user(request)
            )
        }
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/candidates")
async def create_project_context_candidate(
    project_id: str,
    payload: ProjectContextCandidateCreateRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return _context_service(request).create_candidate(
            project_id,
            payload.content,
            get_current_user(request),
            source_metadata=payload.source_metadata,
            source_task_id=payload.source_task_id,
            source_attempt_id=payload.source_attempt_id,
            source_message_start_seq=payload.source_message_start_seq,
            source_message_end_seq=payload.source_message_end_seq,
            source_output_start_seq=payload.source_output_start_seq,
            source_output_end_seq=payload.source_output_end_seq,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/candidates/{candidate_id}/accept")
async def accept_project_context_candidate(
    project_id: str, candidate_id: str, request: Request
) -> dict[str, object]:
    try:
        return _context_service(request).accept_candidate(
            project_id, candidate_id, get_current_user(request)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/candidates/{candidate_id}/reject")
async def reject_project_context_candidate(
    project_id: str,
    candidate_id: str,
    payload: ProjectContextCandidateRejectRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return _context_service(request).reject_candidate(
            project_id,
            candidate_id,
            get_current_user(request),
            reason=payload.reason,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/context/fragments")
async def list_project_context_fragments(project_id: str, request: Request) -> dict[str, object]:
    try:
        return {
            "items": _context_service(request).list_fragments(project_id, get_current_user(request))
        }
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/fragments")
async def create_project_context_fragment(
    project_id: str,
    payload: ProjectContextFragmentCreateRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return _context_service(request).create_fragment(
            project_id,
            payload.content,
            get_current_user(request),
            source_type=payload.source_type,
            source_metadata=payload.source_metadata,
            source_version=payload.source_version,
            sort_order=payload.sort_order,
            byte_budget=payload.byte_budget,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/tasks/{task_id}/context")
async def get_task_context(task_id: str, request: Request) -> dict[str, object]:
    try:
        return _context_service(request).task_context(task_id, get_current_user(request))
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/tasks/{task_id}/context/preview")
async def preview_task_context_update(task_id: str, request: Request) -> dict[str, object]:
    project_id = request.query_params.get("project_id")
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    try:
        return _task_application_service(request).preview_task_context_update(
            task_id, project_id, get_current_user(request)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/tasks/{task_id}/context/confirm")
async def confirm_task_context_update(
    task_id: str,
    payload: TaskContextConfirmRequest,
    request: Request,
) -> dict[str, object]:
    project_id = request.query_params.get("project_id")
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    try:
        return _task_application_service(request).confirm_task_context_update(
            task_id,
            project_id,
            payload.preview_id,
            get_current_user(request),
            idempotency_key=_idempotency_key(request, payload.idempotency_key),
        )
    except Exception as exc:
        raise _translate(exc) from exc

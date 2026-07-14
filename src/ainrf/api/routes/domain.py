"""Mode-gated v2 adapters; legacy routes remain authoritative until B7."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from ainrf.api.domain_schemas import (
    DomainProjectListResponse,
    DomainProjectSummaryResponse,
    DomainWorkspaceListResponse,
    DomainWorkspaceResponse,
)
from ainrf.api.idempotency import require_idempotency_key
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
from ainrf.domain.overview_jobs import OverviewSnapshotService
from ainrf.domain_control import DomainMaintenanceService, DomainModelMode
from ainrf.literature.task_saga import LiteratureTaskSagaService

router = APIRouter(prefix="/domain", tags=["domain-v2"])


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    service = getattr(request.app.state, "domain_service", None)
    mode = request.app.state.api_config.domain_model_mode
    ready = mode is DomainModelMode.V2 and isinstance(service, DomainService) and service.v2_ready()
    context_ready = ready and isinstance(
        getattr(request.app.state, "project_context_service", None), ProjectContextService
    )
    task_service_ready = ready and isinstance(
        getattr(request.app.state, "task_application_service", None), TaskApplicationService
    )
    maintenance = getattr(request.app.state, "domain_maintenance_service", None)
    dispatcher_readiness: dict[str, object] = {
        "participant_type": "task-dispatcher",
        "ready": False,
        "maintenance_active": False,
        "maintenance_epoch": None,
        "stale_after_seconds": 30.0,
        "registered_participant_ids": [],
        "active_participant_ids": [],
        "fresh_participant_ids": [],
        "stale_participant_ids": [],
    }
    if isinstance(maintenance, DomainMaintenanceService):
        dispatcher_readiness = maintenance.participant_readiness("task-dispatcher")
    task_ready = task_service_ready and bool(dispatcher_readiness.get("ready"))
    workspace_links_ready = ready and all(
        callable(getattr(service, name, None))
        for name in ("attach_workspace", "detach_workspace", "set_primary_workspace")
    )
    overview_service = getattr(request.app.state, "overview_snapshot_service", None)
    overview_readiness: dict[str, object] = {
        "job_store_ready": False,
        "planner_ready": False,
        "planner_status": "unavailable",
    }
    if isinstance(overview_service, OverviewSnapshotService):
        overview_readiness = overview_service.planner_readiness()
    overview_ready = (
        ready
        and bool(overview_readiness.get("job_store_ready"))
        and bool(overview_readiness.get("planner_ready"))
    )
    literature_saga = getattr(request.app.state, "literature_task_saga_service", None)
    literature_ready = (
        ready
        and task_ready
        and isinstance(literature_saga, LiteratureTaskSagaService)
        and literature_saga.v2_ready()
    )
    return {
        "domain_contract_version": 2 if ready else 1,
        "mode": mode.value,
        "standard_task_create": task_ready,
        "project_context": context_ready,
        "workspace_links": workspace_links_ready,
        "task_attempts": task_ready,
        "task_dispatcher": dispatcher_readiness,
        # Each capability reports its own runtime evidence rather than being
        # inferred from the common contract version alone.
        "literature_research_task": literature_ready,
        "overview_snapshot": overview_ready,
        "overview_snapshot_job_store": bool(overview_readiness.get("job_store_ready")),
        "overview_snapshot_planner": overview_readiness,
    }


@router.get("/overview/today")
async def today_overview(request: Request) -> dict[str, object]:
    snapshot_service = _overview_service(request)
    user = get_current_user(request)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Authenticated user ID is required")
    payload = snapshot_service.latest(user_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No overview snapshot is available")
    return payload


@router.post("/overview/today/refresh", status_code=status.HTTP_202_ACCEPTED)
async def request_today_overview_refresh(request: Request) -> dict[str, object]:
    """Enqueue (or reuse) the caller's durable manual refresh job."""

    snapshot_service = _overview_service(request)
    user = get_current_user(request)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Authenticated user ID is required")
    try:
        return snapshot_service.request_refresh(user_id, trigger="manual")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/overview/refresh/{job_id}")
async def get_today_overview_refresh(job_id: str, request: Request) -> dict[str, object]:
    """Return one caller-owned refresh job without exposing other users' work."""

    snapshot_service = _overview_service(request)
    user = get_current_user(request)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Authenticated user ID is required")
    job = snapshot_service.get_job(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Overview refresh job not found")
    return job


def _service(request: Request) -> DomainService:
    service = getattr(request.app.state, "domain_service", None)
    if service is None or request.app.state.api_config.domain_model_mode is not DomainModelMode.V2:
        raise HTTPException(status_code=404, detail="Domain v2 is unavailable")
    if not service.v2_ready():
        raise HTTPException(status_code=503, detail="Domain v2 cutover is not ready")
    return service


def _overview_service(request: Request) -> OverviewSnapshotService:
    _service(request)
    service = getattr(request.app.state, "overview_snapshot_service", None)
    if not isinstance(service, OverviewSnapshotService):
        raise HTTPException(status_code=503, detail="Overview snapshot service is not initialized")
    if not service.job_store_ready():
        raise HTTPException(status_code=503, detail="Overview refresh job store is not ready")
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
            idempotency_key=require_idempotency_key(request, payload.get("idempotency_key")),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects", response_model=DomainProjectListResponse)
async def list_domain_projects(
    request: Request,
    include_archived: bool = Query(False),
) -> DomainProjectListResponse:
    try:
        return DomainProjectListResponse.model_validate(
            {
                "items": _service(request).project_console_summaries(
                    get_current_user(request), include_archived=include_archived
                )
            }
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}", response_model=DomainProjectSummaryResponse)
async def get_domain_project(project_id: str, request: Request) -> DomainProjectSummaryResponse:
    try:
        return DomainProjectSummaryResponse.model_validate(
            _service(request).project_console_summary(project_id, get_current_user(request))
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
            idempotency_key=require_idempotency_key(request, payload.get("idempotency_key")),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/workspaces", response_model=DomainWorkspaceListResponse)
async def list_domain_workspaces(
    request: Request,
    include_unregistered: bool = Query(False),
) -> DomainWorkspaceListResponse:
    try:
        return DomainWorkspaceListResponse.model_validate(
            {
                "items": _service(request).workspace_console_entries(
                    get_current_user(request), include_unregistered=include_unregistered
                )
            }
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/workspaces/{workspace_id}", response_model=DomainWorkspaceResponse)
async def get_domain_workspace(workspace_id: str, request: Request) -> DomainWorkspaceResponse:
    try:
        return DomainWorkspaceResponse.model_validate(
            _service(request).workspace_console_entry(workspace_id, get_current_user(request))
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
            idempotency_key=require_idempotency_key(request),
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
            idempotency_key=require_idempotency_key(request),
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
            project_id,
            payload.content,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/publish")
async def publish_project_context(project_id: str, request: Request) -> dict[str, object]:
    try:
        return _context_service(request).publish(
            project_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
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
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/context/candidates/{candidate_id}/accept")
async def accept_project_context_candidate(
    project_id: str, candidate_id: str, request: Request
) -> dict[str, object]:
    try:
        return _context_service(request).accept_candidate(
            project_id,
            candidate_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
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
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
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
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
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
            idempotency_key=require_idempotency_key(request, payload.idempotency_key),
        )
    except Exception as exc:
        raise _translate(exc) from exc

"""Authoritative v2 domain routes."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from fastapi import APIRouter, HTTPException, Query, Request, status

from ainrf.api.domain_schemas import (
    DomainProjectListResponse,
    DomainProjectSummaryResponse,
    DomainWorkspaceListResponse,
    DomainWorkspaceResponse,
)
from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.domain_presenters import (
    auth_service,
    environment_connection,
    environment_connection_from_create,
    latest_environment_detection,
    serialize_environment,
    serialize_project_member,
)
from ainrf.api.workspace_preflight import validate_workspace_registration_path
from ainrf.api.schemas import (
    EnvironmentCreateRequest,
    EnvironmentListResponse,
    EnvironmentResponse,
    EnvironmentUpdateRequest,
    ProjectEnvironmentReferenceListResponse,
    ProjectEnvironmentReferenceCreateRequest,
    ProjectEnvironmentReferenceResponse,
    ProjectEnvironmentReferenceUpdateRequest,
    ProjectMemberListResponse,
    ProjectMemberRequest,
    ProjectMemberResponse,
    ProjectUsageSummaryResponse,
    ProjectUpdateRequest,
    ProjectContextCandidateCreateRequest,
    ProjectContextCandidateRejectRequest,
    ProjectContextDraftRequest,
    ProjectContextFragmentCreateRequest,
    TaskContextConfirmRequest,
    TaskRelationshipCreateRequest,
    TaskRelationshipListResponse,
    TaskRelationshipResponse,
    WorkspaceUpdateRequest,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import (
    DomainPermissionError,
    EnvironmentModule,
    ProjectModule,
    ProjectContextService,
    TaskProjectionService,
    WorkspaceModule,
)
from ainrf.domain.overview_jobs import OverviewSnapshotService
from ainrf.domain_control import DomainMaintenanceService
from ainrf.literature.task_saga import LiteratureTaskSagaService


class _WorkspaceUpdateKwargs(TypedDict):
    label: NotRequired[str | None]
    description: NotRequired[str | None]
    canonical_path: NotRequired[str]
    workspace_prompt: NotRequired[str | None]


router = APIRouter(prefix="/domain", tags=["domain-v2"])


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    project_module = getattr(request.app.state, "project_module", None)
    workspace_module = getattr(request.app.state, "workspace_module", None)
    ready = (
        isinstance(project_module, ProjectModule)
        and project_module.ready()
        and isinstance(workspace_module, WorkspaceModule)
        and workspace_module.ready()
    )
    context_ready = ready and isinstance(
        getattr(request.app.state, "project_context_service", None), ProjectContextService
    )
    conversation_service = getattr(request.app.state, "conversation_application_service", None)
    task_service_ready = ready and conversation_service is not None and conversation_service.ready()
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
        callable(getattr(workspace_module, name, None))
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
        and literature_saga.ready()
    )
    return {
        "domain_contract_version": 2 if ready else 1,
        "mode": "v2",
        "standard_task_create": task_ready,
        "project_context": context_ready,
        "workspace_links": workspace_links_ready,
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
        return snapshot_service.request_refresh(
            user_id,
            trigger="manual",
            idempotency_key=require_idempotency_key(request),
        )
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


def _project_module(request: Request) -> ProjectModule:
    service = getattr(request.app.state, "project_module", None)
    if not isinstance(service, ProjectModule):
        raise HTTPException(status_code=404, detail="Domain is unavailable")
    if not service.ready():
        raise HTTPException(status_code=503, detail="Domain is not ready for current writes")
    return service


def _workspace_module(request: Request) -> WorkspaceModule:
    service = getattr(request.app.state, "workspace_module", None)
    if not isinstance(service, WorkspaceModule):
        raise HTTPException(status_code=404, detail="Domain is unavailable")
    if not service.ready():
        raise HTTPException(status_code=503, detail="Domain is not ready for current writes")
    return service


def _environment_module(request: Request) -> EnvironmentModule:
    service = getattr(request.app.state, "environment_module", None)
    if not isinstance(service, EnvironmentModule) or not service.ready():
        raise HTTPException(status_code=503, detail="Domain is not ready for current writes")
    return service


def _overview_service(request: Request) -> OverviewSnapshotService:
    _project_module(request)
    service = getattr(request.app.state, "overview_snapshot_service", None)
    if not isinstance(service, OverviewSnapshotService):
        raise HTTPException(status_code=503, detail="Overview snapshot service is not initialized")
    if not service.job_store_ready():
        raise HTTPException(status_code=503, detail="Overview refresh job store is not ready")
    return service


def _context_service(request: Request) -> ProjectContextService:
    service = getattr(request.app.state, "project_context_service", None)
    if service is None or not service.ready():
        raise HTTPException(status_code=503, detail="Project Context service is not initialized")
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
        if "idempotency_key" in payload:
            raise HTTPException(status_code=422, detail="Use the Idempotency-Key header")
        description_value = payload.get("description")
        description = description_value if isinstance(description_value, str) else None
        return _project_module(request).create_project(
            get_current_user(request),
            name=str(payload["name"]),
            description=description,
            idempotency_key=require_idempotency_key(request),
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
                "items": _project_module(request).project_console_summaries(
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
            _project_module(request).project_console_summary(project_id, get_current_user(request))
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/projects/{project_id}/task-relationships",
    response_model=TaskRelationshipListResponse,
)
async def list_project_task_relationships(
    project_id: str, request: Request
) -> TaskRelationshipListResponse:
    try:
        items = _project_module(request).list_task_relationships(
            project_id, get_current_user(request)
        )
        return TaskRelationshipListResponse.model_validate({"items": items})
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/projects/{project_id}/task-relationships",
    response_model=TaskRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_task_relationship(
    project_id: str, payload: TaskRelationshipCreateRequest, request: Request
) -> TaskRelationshipResponse:
    try:
        result = _project_module(request).create_task_relationship(
            project_id,
            get_current_user(request),
            source_task_id=payload.source_task_id,
            target_task_id=payload.target_task_id,
            idempotency_key=require_idempotency_key(request),
        )
        return TaskRelationshipResponse.model_validate(result)
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete(
    "/projects/{project_id}/task-relationships/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_task_relationship(
    project_id: str, relationship_id: str, request: Request
) -> None:
    try:
        module = _project_module(request)
        user = get_current_user(request)
        module.require_project_editor(project_id, user)
        relationships = module.list_task_relationships(project_id, user)
        if not any(item["relationship_id"] == relationship_id for item in relationships):
            raise HTTPException(status_code=404, detail="Task relationship not found")
        module.delete_task_relationship(
            relationship_id,
            user,
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/projects/{project_id}/usage-summary",
    response_model=ProjectUsageSummaryResponse,
)
async def get_project_usage_summary(
    project_id: str, request: Request
) -> ProjectUsageSummaryResponse:
    try:
        user = get_current_user(request)
        _project_module(request).project(project_id, user)
        projection = getattr(request.app.state, "task_projection_service", None)
        if not isinstance(projection, TaskProjectionService):
            projection = TaskProjectionService(request.app.state.api_config.state_root)
            request.app.state.task_projection_service = projection
        summary = projection.project_usage_summary(project_id, user)
        return ProjectUsageSummaryResponse.model_validate(summary)
    except Exception as exc:
        raise _translate(exc) from exc


@router.patch("/projects/{project_id}", response_model=DomainProjectSummaryResponse)
async def update_domain_project(
    project_id: str, payload: ProjectUpdateRequest, request: Request
) -> DomainProjectSummaryResponse:
    try:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValueError("Project update requires at least one mutable field")
        if set(changes).difference({"name", "description"}):
            raise ValueError("Workspace selection must use the Primary Workspace endpoint")
        module = _project_module(request)
        user = get_current_user(request)
        module.update_project(
            project_id,
            user,
            idempotency_key=require_idempotency_key(request),
            **changes,
        )
        return DomainProjectSummaryResponse.model_validate(
            module.project_console_summary(project_id, user)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_domain_project(project_id: str, request: Request) -> None:
    try:
        user = get_current_user(request)
        _project_module(request).require_project_owner(project_id, user)
        _project_module(request).archive_project(
            project_id,
            user,
            reason="user archived project",
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_domain_project(project_id: str, request: Request) -> None:
    try:
        user = get_current_user(request)
        _project_module(request).require_project_owner(project_id, user)
        _project_module(request).unarchive_project(
            project_id, user, idempotency_key=require_idempotency_key(request)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/members", response_model=ProjectMemberListResponse)
async def list_domain_project_members(
    project_id: str, request: Request
) -> ProjectMemberListResponse:
    try:
        module = _project_module(request)
        return ProjectMemberListResponse(
            items=[
                serialize_project_member(member, auth_service(request))
                for member in module.list_project_members(project_id, get_current_user(request))
            ]
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/projects/{project_id}/members/{member_user_id}", response_model=ProjectMemberResponse)
async def upsert_domain_project_member(
    project_id: str,
    member_user_id: str,
    payload: ProjectMemberRequest,
    request: Request,
) -> ProjectMemberResponse:
    try:
        module = _project_module(request)
        user = get_current_user(request)
        module.add_member(
            project_id,
            member_user_id,
            payload.role,
            payload.can_publish,
            user,
            idempotency_key=require_idempotency_key(request),
        )
        member = next(
            (
                item
                for item in module.list_project_members(project_id, user)
                if item.get("user_id") == member_user_id
            ),
            None,
        )
        if member is None:
            raise RuntimeError("Updated Project member could not be read")
        return serialize_project_member(member, auth_service(request))
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete(
    "/projects/{project_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_domain_project_member(
    project_id: str, member_user_id: str, request: Request
) -> None:
    try:
        _project_module(request).remove_member(
            project_id,
            member_user_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/workspaces")
async def create_workspace(request: Request, payload: dict[str, object]) -> dict[str, object]:
    try:
        if "idempotency_key" in payload:
            raise HTTPException(status_code=422, detail="Use the Idempotency-Key header")
        service = _project_module(request)
        user = get_current_user(request)
        user_id = user.get("id")
        if not isinstance(user_id, str):
            raise ValueError("Authenticated user ID is required")
        environment_id = str(payload["environment_id"])
        canonical_path = service.canonical_workspace_path(str(payload["canonical_path"]))
        label = str(payload["label"])
        idempotency_key = require_idempotency_key(request)
        replay = service.workspace_create_replay(
            user,
            environment_id=environment_id,
            canonical_path=canonical_path,
            label=label,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        await validate_workspace_registration_path(
            request,
            environment_id=environment_id,
            canonical_path=canonical_path,
            user_id=user_id,
        )
        return service.create_workspace(
            user,
            environment_id=environment_id,
            canonical_path=canonical_path,
            label=label,
            idempotency_key=idempotency_key,
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
                "items": _workspace_module(request).workspace_console_entries(
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
            _workspace_module(request).workspace_console_entry(
                workspace_id, get_current_user(request)
            )
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.patch("/workspaces/{workspace_id}", response_model=DomainWorkspaceResponse)
async def update_domain_workspace(
    workspace_id: str, payload: WorkspaceUpdateRequest, request: Request
) -> DomainWorkspaceResponse:
    try:
        fields = payload.model_fields_set
        if not fields:
            raise ValueError("Workspace update requires at least one mutable field")
        if "project_id" in fields:
            raise ValueError("Workspace attachment must use the Project Workspace endpoint")
        kwargs: _WorkspaceUpdateKwargs = {}
        if "label" in fields:
            kwargs["label"] = payload.label
        if "description" in fields:
            kwargs["description"] = payload.description
        if "default_workdir" in fields and payload.default_workdir is not None:
            kwargs["canonical_path"] = payload.default_workdir
        if "workspace_prompt" in fields:
            kwargs["workspace_prompt"] = payload.workspace_prompt
        module = _workspace_module(request)
        user = get_current_user(request)
        module.update_workspace(
            workspace_id,
            user,
            idempotency_key=require_idempotency_key(request),
            **kwargs,
        )
        return DomainWorkspaceResponse.model_validate(
            module.workspace_console_entry(workspace_id, user)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/workspaces/{workspace_id}/unregister", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_domain_workspace(workspace_id: str, request: Request) -> None:
    try:
        _workspace_module(request).unregister_workspace(
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/projects/{project_id}/workspaces/{workspace_id}")
async def attach_workspace(
    project_id: str, workspace_id: str, request: Request
) -> dict[str, object]:
    try:
        return _workspace_module(request).attach_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete(
    "/projects/{project_id}/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_domain_workspace(
    project_id: str,
    workspace_id: str,
    request: Request,
    allow_no_primary: bool = Query(False),
) -> None:
    try:
        _workspace_module(request).detach_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
            allow_no_primary=allow_no_primary,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/projects/{project_id}/primary-workspace/{workspace_id}")
async def set_primary_workspace(
    project_id: str,
    workspace_id: str,
    request: Request,
    previous_workspace_id: str | None = Query(None),
) -> dict[str, object]:
    try:
        module = _project_module(request)
        if previous_workspace_id is not None:
            return module.replace_primary_workspace(
                project_id,
                previous_workspace_id,
                workspace_id,
                get_current_user(request),
                idempotency_key=require_idempotency_key(request),
            )
        return module.set_primary_workspace(
            project_id,
            workspace_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/environments", response_model=EnvironmentListResponse)
async def list_domain_environments(request: Request) -> EnvironmentListResponse:
    try:
        return EnvironmentListResponse(
            items=[
                serialize_environment(
                    environment,
                    latest_detection=latest_environment_detection(
                        request, str(environment["environment_id"])
                    ),
                )
                for environment in _environment_module(request).list_environments(
                    get_current_user(request)
                )
            ]
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED
)
async def create_domain_environment(
    payload: EnvironmentCreateRequest, request: Request
) -> EnvironmentResponse:
    try:
        environment = _environment_module(request).create_environment(
            get_current_user(request),
            alias=payload.alias,
            display_name=payload.display_name,
            description=payload.description,
            connection=environment_connection_from_create(payload),
            idempotency_key=require_idempotency_key(request),
        )
        return serialize_environment(environment)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/environments/{environment_id}", response_model=EnvironmentResponse)
async def get_domain_environment(environment_id: str, request: Request) -> EnvironmentResponse:
    try:
        return serialize_environment(
            _environment_module(request).environment(
                environment_id, get_current_user(request), include_disabled=False
            ),
            latest_detection=latest_environment_detection(request, environment_id),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.patch("/environments/{environment_id}", response_model=EnvironmentResponse)
async def update_domain_environment(
    environment_id: str,
    payload: EnvironmentUpdateRequest,
    request: Request,
) -> EnvironmentResponse:
    try:
        module = _environment_module(request)
        user = get_current_user(request)
        current = module.environment(environment_id, user)
        fields = payload.model_fields_set
        connection = environment_connection(current.get("connection_json"))
        for name in (
            "host",
            "port",
            "user",
            "identity_file",
            "proxy_jump",
            "proxy_command",
            "ssh_options",
            "default_workdir",
            "preferred_python",
            "preferred_env_manager",
            "preferred_runtime_notes",
            "task_harness_profile",
            "tags",
        ):
            if name in fields:
                connection[name] = getattr(payload, name)
        if "auth_kind" in fields:
            connection["auth_kind"] = (
                payload.auth_kind.value if payload.auth_kind is not None else None
            )
        kwargs: dict[str, object] = {"connection": connection}
        for name in ("alias", "display_name", "description"):
            if name in fields:
                kwargs[name] = getattr(payload, name)
        environment = module.update_environment(
            environment_id,
            user,
            idempotency_key=require_idempotency_key(request),
            **kwargs,
        )
        return serialize_environment(
            environment, latest_detection=latest_environment_detection(request, environment_id)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete("/environments/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_domain_environment(environment_id: str, request: Request) -> None:
    try:
        _environment_module(request).disable_environment(
            environment_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/environments/{environment_id}/detect", response_model=EnvironmentResponse)
async def detect_domain_environment(environment_id: str, request: Request) -> EnvironmentResponse:
    try:
        user = get_current_user(request)
        environment = _environment_module(request).environment(
            environment_id, user, include_disabled=False
        )
        observations = getattr(request.app.state, "environment_observation_service", None)
        detect = getattr(observations, "detect_environment", None)
        if not callable(detect):
            raise HTTPException(
                status_code=500, detail="Environment observation service is unavailable"
            )
        snapshot = await detect(
            environment_id,
            app_user_id=user.get("id") if isinstance(user.get("id"), str) else None,
            terminal_session_manager=getattr(request.app.state, "terminal_session_manager", None),
        )
        return serialize_environment(environment, latest_detection=snapshot)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/projects/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceListResponse,
)
async def list_domain_project_environment_refs(
    project_id: str, request: Request
) -> ProjectEnvironmentReferenceListResponse:
    try:
        project = _project_module(request).project_console_summary(
            project_id, get_current_user(request)
        )
        primary = project.get("primary_workspace")
        environment_id = primary.get("environment_id") if isinstance(primary, dict) else None
        return ProjectEnvironmentReferenceListResponse(
            items=[
                ProjectEnvironmentReferenceResponse(environment_id=environment_id, is_default=True)
            ]
            if isinstance(environment_id, str)
            else []
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/projects/{project_id}/environment-refs",
    response_model=ProjectEnvironmentReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_domain_project_environment_ref(
    project_id: str,
    payload: ProjectEnvironmentReferenceCreateRequest,
    request: Request,
) -> ProjectEnvironmentReferenceResponse:
    _ = payload
    try:
        _project_module(request).require_project_editor(project_id, get_current_user(request))
    except Exception as exc:
        raise _translate(exc) from exc
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Project environments are managed through explicit Workspace links",
    )


@router.patch(
    "/projects/{project_id}/environment-refs/{environment_id}",
    response_model=ProjectEnvironmentReferenceResponse,
)
async def update_domain_project_environment_ref(
    project_id: str,
    environment_id: str,
    payload: ProjectEnvironmentReferenceUpdateRequest,
    request: Request,
) -> ProjectEnvironmentReferenceResponse:
    _ = (environment_id, payload)
    try:
        _project_module(request).require_project_editor(project_id, get_current_user(request))
    except Exception as exc:
        raise _translate(exc) from exc
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Project environments are managed through explicit Workspace links",
    )


@router.delete(
    "/projects/{project_id}/environment-refs/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_domain_project_environment_ref(
    project_id: str, environment_id: str, request: Request
) -> None:
    _ = environment_id
    try:
        _project_module(request).require_project_editor(project_id, get_current_user(request))
    except Exception as exc:
        raise _translate(exc) from exc
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Project environments are managed through explicit Workspace links",
    )


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
            idempotency_key=require_idempotency_key(request),
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
            source_message_start_seq=payload.source_message_start_seq,
            source_message_end_seq=payload.source_message_end_seq,
            source_output_start_seq=payload.source_output_start_seq,
            source_output_end_seq=payload.source_output_end_seq,
            idempotency_key=require_idempotency_key(request),
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
            idempotency_key=require_idempotency_key(request),
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
            idempotency_key=require_idempotency_key(request),
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
        return _context_service(request).preview_task_context_update(
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
        return _context_service(request).confirm_task_context_update(
            task_id,
            project_id,
            payload.preview_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _translate(exc) from exc

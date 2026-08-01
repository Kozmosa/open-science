"""Literature tracking API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ainrf.api.idempotency import require_idempotency_key
from ainrf.auth.permissions import get_current_user
from ainrf.domain.service import DomainConflictError, DomainNotFoundError, DomainPermissionError
from ainrf.domain_control import DomainCutoverError, MaintenanceModeError
from ainrf.api.literature_presenters import (
    present,
    present_check_list,
    present_legacy_subscription,
    present_research_task_list,
    present_topic_list,
    present_version_list,
)
from ainrf.api.literature_schemas import (
    LegacyLiteratureFetchResponse,
    LegacyLiteratureFetchStatusResponse,
    LegacyLiteratureReadRequest,
    LegacyLiteratureSubscriptionListResponse,
    LegacyLiteratureSubscriptionRequest,
    LegacyLiteratureSubscriptionResponse,
    LegacyLiteratureSubscriptionUpdateRequest,
    LiteratureCheckListResponse,
    LiteratureCheckRequest,
    LiteratureCheckResponse,
    LiteratureOverviewResponse,
    LiteraturePaperDetailResponse,
    LiteraturePaperListResponse,
    LiteraturePaperStateRequest,
    LiteraturePaperVersionListResponse,
    LiteratureResearchTaskListResponse,
    LiteratureResearchTaskRequest,
    LiteratureResearchTaskResponse,
    LiteratureSummaryRequest,
    LiteratureSummaryResponse,
    LiteratureTopicListResponse,
    LiteratureTopicPreviewResponse,
    LiteratureTopicRequest,
    LiteratureTopicResponse,
    LiteratureTopicUpdateRequest,
)
from ainrf.literature.task_saga import (
    LiteratureTaskSagaService,
    ResearchTaskIdempotencyConflictError,
    ResearchTaskPaperNotFoundError,
    ResearchTaskPresetError,
    ResearchTaskWorkspaceRequiredError,
)
from ainrf.literature.tracking import (
    LiteratureIdempotencyConflictError,
    LiteratureTrackingService,
)

router = APIRouter(prefix="/literature", tags=["literature"])


def _get_tracking_service(request: Request) -> LiteratureTrackingService:
    service = getattr(request.app.state, "literature_tracking_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Literature tracking service not initialized")
    service.initialize()
    return service


def _get_research_task_saga(request: Request) -> LiteratureTaskSagaService:
    """Return the formal saga only after the committed v2 fuse is live."""

    service = getattr(request.app.state, "literature_task_saga_service", None)
    if not isinstance(service, LiteratureTaskSagaService) or not service.v2_ready():
        raise HTTPException(status_code=503, detail="Literature Task saga service is not ready")
    return service


def _get_user_id(request: Request) -> str:
    return get_current_user(request)["id"]


def _tracking_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, LiteratureIdempotencyConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def _research_task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ResearchTaskPaperNotFoundError, DomainNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DomainCutoverError):
        return HTTPException(status_code=503, detail="Domain cutover fuse is not writable")
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(
        exc,
        (
            DomainConflictError,
            ResearchTaskWorkspaceRequiredError,
            ResearchTaskIdempotencyConflictError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (ResearchTaskPresetError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def _new_research_task(
    request: Request,
    *,
    paper_id: str,
    body: LiteratureResearchTaskRequest,
    subscription_id: str | None = None,
) -> dict[str, object]:
    saga = _get_research_task_saga(request)
    user = get_current_user(request)
    try:
        return saga.create_research_task(
            user,
            paper_id=paper_id,
            subscription_id=subscription_id,
            project_id=body.project_id,
            workspace_id=body.workspace_id,
            task_preset=body.task_preset,
            title=body.title,
            idempotency_key=require_idempotency_key(request),
        )
    except Exception as exc:
        raise _research_task_error(exc) from exc


def _research_task_response_status(result: dict[str, object]) -> int:
    return 201 if result.get("status") == "completed" else 202


@router.get("/overview", response_model=LiteratureOverviewResponse)
async def literature_overview(request: Request) -> LiteratureOverviewResponse:
    return present(
        LiteratureOverviewResponse,
        _get_tracking_service(request).overview(_get_user_id(request)),
    )


@router.get("/topics", response_model=LiteratureTopicListResponse)
async def list_topics(request: Request) -> LiteratureTopicListResponse:
    return present_topic_list(_get_tracking_service(request).list_topics(_get_user_id(request)))


@router.post("/topics", status_code=201, response_model=LiteratureTopicResponse)
async def create_topic(body: LiteratureTopicRequest, request: Request) -> LiteratureTopicResponse:
    try:
        return present(
            LiteratureTopicResponse,
            _get_tracking_service(request).create_topic(
                user_id=_get_user_id(request),
                label=body.label,
                include_terms=body.include_terms,
                exclude_terms=body.exclude_terms,
                categories=body.categories,
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/topics/{topic_id}", response_model=LiteratureTopicResponse)
async def get_topic(topic_id: str, request: Request) -> LiteratureTopicResponse:
    try:
        return present(
            LiteratureTopicResponse,
            _get_tracking_service(request).get_topic(_get_user_id(request), topic_id),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.patch("/topics/{topic_id}", response_model=LiteratureTopicResponse)
async def patch_topic(
    topic_id: str, body: LiteratureTopicUpdateRequest, request: Request
) -> LiteratureTopicResponse:
    try:
        return present(
            LiteratureTopicResponse,
            _get_tracking_service(request).update_topic(
                _get_user_id(request), topic_id, body.model_dump(exclude_none=True)
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.delete("/topics/{topic_id}", status_code=204, response_model=None)
async def remove_topic(topic_id: str, request: Request) -> None:
    try:
        _get_tracking_service(request).delete_topic(_get_user_id(request), topic_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/topics/preview", response_model=LiteratureTopicPreviewResponse)
async def preview_topic(
    body: LiteratureTopicRequest, request: Request
) -> LiteratureTopicPreviewResponse:
    try:
        return present(
            LiteratureTopicPreviewResponse,
            _get_tracking_service(request).preview_topic(_get_user_id(request), body.model_dump()),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/checks", status_code=202, response_model=LiteratureCheckResponse)
async def create_literature_check(
    body: LiteratureCheckRequest, request: Request
) -> LiteratureCheckResponse:
    try:
        return present(
            LiteratureCheckResponse,
            _get_tracking_service(request).create_check(
                user_id=_get_user_id(request),
                topic_ids=body.topic_ids,
                trigger="manual",
                idempotency_key=require_idempotency_key(request),
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/checks/current", response_model=LiteratureCheckResponse | None)
async def current_literature_check(request: Request) -> LiteratureCheckResponse | None:
    result = _get_tracking_service(request).overview(_get_user_id(request))["active_check"]
    return present(LiteratureCheckResponse, result) if result else None


@router.get("/checks", response_model=LiteratureCheckListResponse)
async def list_literature_checks(
    request: Request, limit: int = Query(default=30, ge=1, le=100)
) -> LiteratureCheckListResponse:
    return present_check_list(
        _get_tracking_service(request).list_checks(_get_user_id(request), limit)
    )


@router.get("/checks/{check_id}", response_model=LiteratureCheckResponse)
async def get_literature_check(check_id: str, request: Request) -> LiteratureCheckResponse:
    try:
        return present(
            LiteratureCheckResponse,
            _get_tracking_service(request).get_check(_get_user_id(request), check_id),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/subscriptions", response_model=LegacyLiteratureSubscriptionListResponse)
async def list_subscriptions(request: Request) -> LegacyLiteratureSubscriptionListResponse:
    topics = _get_tracking_service(request).list_topics(_get_user_id(request))
    return LegacyLiteratureSubscriptionListResponse(
        items=[present_legacy_subscription(topic) for topic in topics]
    )


@router.post("/subscriptions", status_code=201, response_model=LegacyLiteratureSubscriptionResponse)
async def create_subscription(
    body: LegacyLiteratureSubscriptionRequest, request: Request
) -> LegacyLiteratureSubscriptionResponse:
    user_id = _get_user_id(request)
    topic = _get_tracking_service(request).create_topic(
        user_id=user_id,
        label=body.label,
        include_terms=body.keywords,
        exclude_terms=[],
        categories=body.arxiv_categories,
    )
    return present_legacy_subscription(topic)


@router.put("/subscriptions/{subscription_id}", response_model=LegacyLiteratureSubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    body: LegacyLiteratureSubscriptionUpdateRequest,
    request: Request,
) -> LegacyLiteratureSubscriptionResponse:
    user_id = _get_user_id(request)
    changes: dict[str, object] = {}
    if body.label is not None:
        changes["label"] = body.label
    if body.keywords is not None:
        changes["include_terms"] = body.keywords
    if body.arxiv_categories is not None:
        changes["categories"] = body.arxiv_categories
    if body.is_active is not None:
        changes["is_active"] = body.is_active
    try:
        updated = _get_tracking_service(request).update_topic(user_id, subscription_id, changes)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc
    return present_legacy_subscription(updated)


@router.delete("/subscriptions/{subscription_id}", status_code=204, response_model=None)
async def delete_subscription(subscription_id: str, request: Request) -> None:
    try:
        _get_tracking_service(request).delete_topic(_get_user_id(request), subscription_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/papers", response_model=LiteraturePaperListResponse)
async def list_papers(
    request: Request,
    view: Literal["today", "unread", "saved", "updated", "all"] = "today",
    topic_id: str | None = None,
    category: str | None = None,
    summary_status: str | None = None,
    has_research_task: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> LiteraturePaperListResponse:
    try:
        return present(
            LiteraturePaperListResponse,
            _get_tracking_service(request).list_papers(
                _get_user_id(request),
                view=view,
                topic_id=topic_id,
                category=category,
                summary_status=summary_status,
                has_research_task=has_research_task,
                cursor=cursor,
                limit=limit,
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/papers/{paper_id}", response_model=LiteraturePaperDetailResponse)
async def get_literature_paper(paper_id: str, request: Request) -> LiteraturePaperDetailResponse:
    try:
        return present(
            LiteraturePaperDetailResponse,
            _get_tracking_service(request).get_paper(_get_user_id(request), paper_id),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/papers/{paper_id}/versions", response_model=LiteraturePaperVersionListResponse)
async def list_literature_paper_versions(
    paper_id: str, request: Request
) -> LiteraturePaperVersionListResponse:
    try:
        detail = _get_tracking_service(request).get_paper(_get_user_id(request), paper_id)
        return present_version_list(detail["versions"])
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.patch("/papers/{paper_id}/state", response_model=LiteraturePaperDetailResponse)
async def patch_literature_paper_state(
    paper_id: str, body: LiteraturePaperStateRequest, request: Request
) -> LiteraturePaperDetailResponse:
    try:
        return present(
            LiteraturePaperDetailResponse,
            _get_tracking_service(request).update_paper_state(
                _get_user_id(request),
                paper_id,
                body.model_dump(exclude_none=True),
                idempotency_key=require_idempotency_key(request),
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/papers/{paper_id}/summary", response_model=LiteratureSummaryResponse)
async def get_literature_summary(paper_id: str, request: Request) -> LiteratureSummaryResponse:
    try:
        return present(
            LiteratureSummaryResponse,
            _get_tracking_service(request).get_summary(_get_user_id(request), paper_id),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post(
    "/papers/{paper_id}/summary", status_code=202, response_model=LiteratureSummaryResponse
)
async def request_literature_summary(
    paper_id: str, body: LiteratureSummaryRequest, request: Request
) -> LiteratureSummaryResponse:
    try:
        return present(
            LiteratureSummaryResponse,
            _get_tracking_service(request).request_summary(
                _get_user_id(request),
                paper_id,
                body.language,
                idempotency_key=require_idempotency_key(request),
            ),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/papers/{paper_id}/read", status_code=204, response_model=None)
async def mark_read(paper_id: str, body: LegacyLiteratureReadRequest, request: Request) -> None:
    try:
        _get_tracking_service(request).update_paper_state(
            _get_user_id(request), paper_id, {"is_read": True}
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post(
    "/papers/{paper_id}/research-task",
    status_code=202,
    response_model=LiteratureResearchTaskResponse,
)
async def create_research_task(
    paper_id: str,
    body: LiteratureResearchTaskRequest,
    request: Request,
    response: Response,
) -> LiteratureResearchTaskResponse:
    """Create/recover a constrained standard Task through the durable saga."""

    result = _new_research_task(request, paper_id=paper_id, body=body)
    response.status_code = _research_task_response_status(result)
    return present(LiteratureResearchTaskResponse, result)


@router.get("/papers/{paper_id}/research-tasks", response_model=LiteratureResearchTaskListResponse)
async def list_research_tasks(
    paper_id: str, request: Request
) -> LiteratureResearchTaskListResponse:
    saga = _get_research_task_saga(request)
    try:
        return present_research_task_list(
            saga.list_research_tasks(get_current_user(request), paper_id=paper_id)
        )
    except Exception as exc:
        raise _research_task_error(exc) from exc


@router.get(
    "/subscriptions/{subscription_id}/fetch-status",
    response_model=LegacyLiteratureFetchStatusResponse,
)
async def get_fetch_status(
    subscription_id: str, request: Request
) -> LegacyLiteratureFetchStatusResponse:
    """Return manual fetch status for a subscription."""
    try:
        _get_tracking_service(request).get_topic(_get_user_id(request), subscription_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc
    checks = _get_tracking_service(request).list_checks(_get_user_id(request), limit=1)
    if not checks:
        return LegacyLiteratureFetchStatusResponse(status="idle", error=None)
    check = checks[0]
    legacy_status = {
        "planned": "running",
        "checking": "running",
        "completed": "completed",
        "failed": "failed",
    }
    return LegacyLiteratureFetchStatusResponse(
        status=legacy_status.get(check["status"], check["status"]), error=check["error"]
    )


@router.post(
    "/subscriptions/{subscription_id}/fetch",
    status_code=202,
    response_model=LegacyLiteratureFetchResponse,
)
async def trigger_fetch(subscription_id: str, request: Request) -> LegacyLiteratureFetchResponse:
    """Manually trigger paper fetching for a subscription."""
    try:
        _get_tracking_service(request).get_topic(_get_user_id(request), subscription_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc
    try:
        check = _get_tracking_service(request).create_check(
            user_id=_get_user_id(request), topic_ids=[subscription_id], trigger="manual"
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc
    return LegacyLiteratureFetchResponse(
        status="fetch_started",
        subscription_id=subscription_id,
        check_id=str(check["check_id"]),
    )

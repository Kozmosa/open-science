"""Literature tracking API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ainrf.api.deprecation import deprecation_headers
from ainrf.api.idempotency import require_idempotency_key
from ainrf.auth.permissions import get_current_user
from ainrf.domain.service import DomainConflictError, DomainNotFoundError, DomainPermissionError
from ainrf.domain_control import DomainCutoverError, DomainModelMode, MaintenanceModeError
from ainrf.literature.models import LiteratureSubscription
from ainrf.literature.service import LiteratureService
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


def _get_service(request: Request) -> LiteratureService:
    service = getattr(request.app.state, "literature_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Literature service not initialized")
    return service


def _get_tracking_service(request: Request) -> LiteratureTrackingService:
    service = getattr(request.app.state, "literature_tracking_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Literature tracking service not initialized")
    service.initialize()
    return service


def _get_research_task_saga(request: Request) -> LiteratureTaskSagaService:
    """Return the formal saga only after the committed v2 fuse is live."""

    service = getattr(request.app.state, "literature_task_saga_service", None)
    domain = getattr(request.app.state, "domain_service", None)
    if (
        request.app.state.api_config.domain_model_mode is not DomainModelMode.V2
        or domain is None
        or not domain.v2_ready()
    ):
        raise HTTPException(
            status_code=409,
            detail="Literature research Tasks require a committed domain v2 cutover",
        )
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


def _text_field(
    body: dict[str, object],
    name: str,
    *,
    required: bool = False,
) -> str | None:
    value = body.get(name)
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail=f"{name} is required")
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name} must be a string")
    return value


async def _json_object(request: Request, *, label: str) -> dict[str, object]:
    try:
        payload: object = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be an object")
    return {str(key): value for key, value in payload.items()}


def _research_task_idempotency_key(request: Request, body: dict[str, object]) -> str:
    body_key = _text_field(body, "idempotency_key")
    return require_idempotency_key(request, body_key)


def _research_task_request(body: dict[str, object]) -> dict[str, str | None]:
    """Validate the constrained Literature subset of Task create input."""

    if "environment_id" in body:
        raise HTTPException(
            status_code=400,
            detail="environment_id is derived from workspace_id and is not accepted",
        )
    return {
        "project_id": _text_field(body, "project_id", required=True),
        "workspace_id": _text_field(body, "workspace_id"),
        "task_preset": _text_field(body, "task_preset") or "structured-research-default",
        "title": _text_field(body, "title"),
    }


def _new_research_task(
    request: Request,
    *,
    paper_id: str,
    body: dict[str, object],
    subscription_id: str | None = None,
) -> dict[str, object]:
    payload = _research_task_request(body)
    saga = _get_research_task_saga(request)
    user = get_current_user(request)
    try:
        return saga.create_research_task(
            user,
            paper_id=paper_id,
            subscription_id=subscription_id,
            project_id=str(payload["project_id"]),
            workspace_id=payload["workspace_id"],
            task_preset=str(payload["task_preset"]),
            title=payload["title"],
            idempotency_key=_research_task_idempotency_key(request, body),
        )
    except Exception as exc:
        raise _research_task_error(exc) from exc


def _research_task_response_status(result: dict[str, object]) -> int:
    return 201 if result.get("status") == "completed" else 202


@router.get("/overview")
async def literature_overview(request: Request):
    return _get_tracking_service(request).overview(_get_user_id(request))


@router.get("/topics")
async def list_topics(request: Request):
    return {"items": _get_tracking_service(request).list_topics(_get_user_id(request))}


@router.post("/topics", status_code=201)
async def create_topic(request: Request):
    body = await request.json()
    try:
        return _get_tracking_service(request).create_topic(
            user_id=_get_user_id(request),
            label=str(body.get("label", "")),
            include_terms=body.get("include_terms", []),
            exclude_terms=body.get("exclude_terms", []),
            categories=body.get("categories", []),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/topics/{topic_id}")
async def get_topic(topic_id: str, request: Request):
    try:
        return _get_tracking_service(request).get_topic(_get_user_id(request), topic_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.patch("/topics/{topic_id}")
async def patch_topic(topic_id: str, request: Request):
    try:
        return _get_tracking_service(request).update_topic(
            _get_user_id(request), topic_id, await request.json()
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.delete("/topics/{topic_id}", status_code=204)
async def remove_topic(topic_id: str, request: Request):
    try:
        _get_tracking_service(request).delete_topic(_get_user_id(request), topic_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/topics/preview")
async def preview_topic(request: Request):
    try:
        return _get_tracking_service(request).preview_topic(
            _get_user_id(request), await request.json()
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/checks", status_code=202)
async def create_literature_check(request: Request):
    body = await request.json()
    topic_ids = body.get("topic_ids")
    if topic_ids is not None and not isinstance(topic_ids, list):
        raise HTTPException(status_code=400, detail="topic_ids must be a list")
    try:
        return _get_tracking_service(request).create_check(
            user_id=_get_user_id(request),
            topic_ids=topic_ids,
            trigger="manual",
            idempotency_key=require_idempotency_key(request),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/checks/current")
async def current_literature_check(request: Request):
    return _get_tracking_service(request).overview(_get_user_id(request))["active_check"]


@router.get("/checks")
async def list_literature_checks(request: Request, limit: int = Query(default=30, le=100)):
    return {"items": _get_tracking_service(request).list_checks(_get_user_id(request), limit)}


@router.get("/checks/{check_id}")
async def get_literature_check(check_id: str, request: Request):
    try:
        return _get_tracking_service(request).get_check(_get_user_id(request), check_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


def _validate_max_results(value) -> int:
    try:
        max_results = int(value or 50)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="max_results must be an integer")
    if not 1 <= max_results <= 100:
        raise HTTPException(status_code=400, detail="max_results must be between 1 and 100")
    return max_results


def _get_user_subscription(
    request: Request, subscription_id: str
) -> tuple[LiteratureService, LiteratureSubscription]:
    user_id = _get_user_id(request)
    service = _get_service(request)
    sub = service.get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return service, sub


@router.get("/subscriptions")
async def list_subscriptions(request: Request):
    user_id = _get_user_id(request)
    subs = _get_service(request).list_subscriptions(user_id)
    return {"items": [s.to_dict() for s in subs]}


@router.post("/subscriptions", status_code=201)
async def create_subscription(request: Request):
    user_id = _get_user_id(request)
    body = await request.json()
    service = _get_service(request)
    sub = service.create_subscription(
        user_id=user_id,
        label=body.get("label", ""),
        keywords=body.get("keywords", []),
        arxiv_categories=body.get("arxiv_categories", []),
        frequency=body.get("frequency", "daily"),
        max_results=_validate_max_results(body.get("max_results", 50)),
    )
    _get_tracking_service(request).sync_legacy_topic(
        topic_id=sub.subscription_id,
        user_id=user_id,
        label=sub.label,
        include_terms=sub.keywords,
        categories=sub.arxiv_categories,
        is_active=sub.is_active,
    )
    return sub.to_dict()


@router.put("/subscriptions/{subscription_id}")
async def update_subscription(subscription_id: str, request: Request):
    user_id = _get_user_id(request)
    service = _get_service(request)
    sub = service.get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    body = await request.json()
    max_results_raw = body.get("max_results")
    max_results = _validate_max_results(max_results_raw) if max_results_raw is not None else None
    updated = service.update_subscription(
        subscription_id,
        label=body.get("label"),
        keywords=body.get("keywords"),
        arxiv_categories=body.get("arxiv_categories"),
        frequency=body.get("frequency"),
        max_results=max_results,
        is_active=body.get("is_active"),
    )
    _get_tracking_service(request).sync_legacy_topic(
        topic_id=updated.subscription_id,
        user_id=user_id,
        label=updated.label,
        include_terms=updated.keywords,
        categories=updated.arxiv_categories,
        is_active=updated.is_active,
    )
    return updated.to_dict()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: str, request: Request):
    user_id = _get_user_id(request)
    sub = _get_service(request).get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    _get_service(request).delete_subscription(subscription_id)
    try:
        _get_tracking_service(request).delete_topic(user_id, subscription_id)
    except KeyError:
        pass


@router.get("/papers")
async def list_papers(
    request: Request,
    subscription_id: str | None = None,
    unread_only: bool = False,
    view: str | None = None,
    topic_id: str | None = None,
    category: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    user_id = _get_user_id(request)
    if view is not None:
        try:
            return _get_tracking_service(request).list_papers(
                user_id,
                view=view,
                topic_id=topic_id,
                category=category,
                cursor=cursor,
                limit=limit,
            )
        except (KeyError, ValueError) as exc:
            raise _tracking_error(exc) from exc
    papers = _get_service(request).list_papers(user_id, subscription_id, unread_only, limit, offset)
    return {"items": [p.to_dict() for p in papers]}


@router.get("/papers/{paper_id}")
async def get_literature_paper(paper_id: str, request: Request):
    try:
        return _get_tracking_service(request).get_paper(_get_user_id(request), paper_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.patch("/papers/{paper_id}/state")
async def patch_literature_paper_state(paper_id: str, request: Request):
    try:
        return _get_tracking_service(request).update_paper_state(
            _get_user_id(request),
            paper_id,
            await request.json(),
            idempotency_key=require_idempotency_key(request),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.get("/papers/{paper_id}/summary")
async def get_literature_summary(paper_id: str, request: Request):
    try:
        return _get_tracking_service(request).get_summary(_get_user_id(request), paper_id)
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/papers/{paper_id}/summary", status_code=202)
async def request_literature_summary(paper_id: str, request: Request):
    body = await request.json()
    try:
        return _get_tracking_service(request).request_summary(
            _get_user_id(request),
            paper_id,
            str(body.get("language", "zh")),
            idempotency_key=require_idempotency_key(request),
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc


@router.post("/papers/{paper_id}/read", status_code=204)
async def mark_read(paper_id: str, request: Request):
    user_id = _get_user_id(request)
    svc = _get_service(request)
    if not svc.user_owns_paper(user_id, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        body = await request.json()
        subscription_id = body.get("subscription_id") if body else None
    except Exception:
        subscription_id = None
    svc.mark_read(paper_id, subscription_id)


@router.post("/papers/{paper_id}/research-task", status_code=202)
async def create_research_task(paper_id: str, request: Request, response: Response):
    """Create/recover a constrained standard Task through the durable saga."""

    body = await _json_object(request, label="Research Task request")
    result = _new_research_task(request, paper_id=paper_id, body=body)
    response.status_code = _research_task_response_status(result)
    return result


@router.get("/papers/{paper_id}/research-tasks")
async def list_research_tasks(paper_id: str, request: Request):
    saga = _get_research_task_saga(request)
    try:
        return {"items": saga.list_research_tasks(get_current_user(request), paper_id=paper_id)}
    except Exception as exc:
        raise _research_task_error(exc) from exc


@router.get("/papers/{paper_id}/research-task")
async def get_research_task(
    paper_id: str,
    request: Request,
    idempotency_key: str = Query(..., min_length=1),
):
    saga = _get_research_task_saga(request)
    try:
        return saga.get_research_task(
            get_current_user(request),
            paper_id=paper_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _research_task_error(exc) from exc


@router.post("/papers/{paper_id}/convert", status_code=202)
async def convert_to_task(paper_id: str, request: Request, response: Response):
    """Deprecated proxy for the validated research-task intent API.

    A legacy caller can retain its path during the compatibility window, but
    it cannot attach a paper to an arbitrary external Task ID anymore.
    """

    replacement = f"/literature/papers/{paper_id}/research-task"
    headers = deprecation_headers(route="literature.convert", replacement=replacement)
    try:
        body = await _json_object(request, label="Convert request")
        if "task_id" in body:
            raise HTTPException(
                status_code=400,
                detail="task_id is no longer accepted; use the research-task intent contract",
            )
        subscription_id = _text_field(body, "subscription_id")
        result = _new_research_task(
            request,
            paper_id=paper_id,
            body=body,
            subscription_id=subscription_id,
        )
    except HTTPException as exc:
        merged_headers = dict(headers)
        if exc.headers is not None:
            merged_headers.update(exc.headers)
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
            headers=merged_headers,
        ) from exc
    response.headers.update(headers)
    response.status_code = _research_task_response_status(result)
    return result


@router.get("/subscriptions/{subscription_id}/fetch-status")
async def get_fetch_status(subscription_id: str, request: Request):
    """Return manual fetch status for a subscription."""
    _service, _sub = _get_user_subscription(request, subscription_id)
    checks = _get_tracking_service(request).list_checks(_get_user_id(request), limit=1)
    if not checks:
        return {"status": "idle", "error": None}
    check = checks[0]
    legacy_status = {
        "planned": "running",
        "checking": "running",
        "completed": "completed",
        "failed": "failed",
    }
    return {"status": legacy_status.get(check["status"], check["status"]), "error": check["error"]}


@router.post("/subscriptions/{subscription_id}/fetch", status_code=202)
async def trigger_fetch(subscription_id: str, request: Request):
    """Manually trigger paper fetching for a subscription."""
    _service, _sub = _get_user_subscription(request, subscription_id)
    try:
        check = _get_tracking_service(request).create_check(
            user_id=_get_user_id(request), topic_ids=[subscription_id], trigger="manual"
        )
    except (KeyError, ValueError) as exc:
        raise _tracking_error(exc) from exc
    return {
        "status": "fetch_started",
        "subscription_id": subscription_id,
        "check_id": check["check_id"],
    }

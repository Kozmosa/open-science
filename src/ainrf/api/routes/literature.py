"""Literature tracking API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ainrf.auth.permissions import get_current_user
from ainrf.literature.models import LiteratureSubscription
from ainrf.literature.service import LiteratureService
from ainrf.literature.tracking import LiteratureTrackingService

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


def _get_user_id(request: Request) -> str:
    return get_current_user(request)["id"]


def _tracking_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


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
            user_id=_get_user_id(request), topic_ids=topic_ids, trigger="manual"
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
            _get_user_id(request), paper_id, await request.json()
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
            _get_user_id(request), paper_id, str(body.get("language", "zh"))
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


@router.post("/papers/{paper_id}/convert", status_code=201)
async def convert_to_task(paper_id: str, request: Request):
    user_id = _get_user_id(request)
    body = await request.json()
    task_id = body.get("task_id")
    subscription_id = body.get("subscription_id")
    svc = _get_service(request)
    if not svc.user_owns_paper(user_id, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    if not task_id:
        project_id = body.get("project_id")
        workspace_id = body.get("workspace_id")
        if (
            not isinstance(subscription_id, str)
            or not isinstance(project_id, str)
            or not isinstance(workspace_id, str)
        ):
            raise HTTPException(
                status_code=400, detail="subscription_id, project_id, and workspace_id are required"
            )
        saga = getattr(request.app.state, "literature_task_saga_service", None)
        if saga is None:
            raise HTTPException(
                status_code=500, detail="Literature Task saga service not initialized"
            )
        try:
            return saga.convert(
                {
                    "id": user_id,
                    "role": getattr(request.state, "current_user", {}).get("role", "member"),
                },
                paper_id=paper_id,
                subscription_id=subscription_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Paper not found") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    paper = svc.convert_to_task(paper_id, task_id, subscription_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found for this subscription")
    return paper.to_dict()


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

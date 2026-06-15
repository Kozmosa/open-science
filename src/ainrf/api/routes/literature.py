"""Literature tracking API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request

from ainrf.auth.permissions import get_current_user
from ainrf.literature.models import LiteratureSubscription
from ainrf.literature.scheduler import LiteratureScheduler
from ainrf.literature.service import LiteratureService

router = APIRouter(prefix="/literature", tags=["literature"])

logger = logging.getLogger(__name__)


def _get_service(request: Request) -> LiteratureService:
    service = getattr(request.app.state, "literature_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Literature service not initialized")
    return service


def _get_scheduler(request: Request) -> LiteratureScheduler:
    scheduler = getattr(request.app.state, "literature_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=500, detail="Literature scheduler not initialized")
    return scheduler


def _get_user_id(request: Request) -> str:
    return get_current_user(request)["id"]


def _validate_max_results(value) -> int:
    try:
        max_results = int(value or 50)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="max_results must be an integer")
    if not 1 <= max_results <= 100:
        raise HTTPException(status_code=400, detail="max_results must be between 1 and 100")
    return max_results


def _get_fetch_tasks(request: Request) -> dict[str, tuple[asyncio.Task, dict[str, str | None]]]:
    if not hasattr(request.app.state, "_literature_tasks"):
        request.app.state._literature_tasks = {}
    return request.app.state._literature_tasks


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
    try:
        _get_scheduler(request).schedule_subscription(sub)
    except Exception:
        logger.exception("failed to schedule subscription=%s", sub.subscription_id)
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
    try:
        _get_scheduler(request).reschedule_subscription(updated)
    except Exception:
        logger.exception("failed to reschedule subscription=%s", subscription_id)
    return updated.to_dict()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: str, request: Request):
    user_id = _get_user_id(request)
    sub = _get_service(request).get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    _get_service(request).delete_subscription(subscription_id)
    try:
        _get_scheduler(request).remove_subscription(subscription_id)
    except Exception:
        logger.exception("failed to remove subscription schedule=%s", subscription_id)


@router.get("/papers")
async def list_papers(
    request: Request,
    subscription_id: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    user_id = _get_user_id(request)
    papers = _get_service(request).list_papers(user_id, subscription_id, unread_only, limit, offset)
    return {"items": [p.to_dict() for p in papers]}


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
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    svc = _get_service(request)
    if not svc.user_owns_paper(user_id, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    paper = svc.convert_to_task(paper_id, task_id, subscription_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found for this subscription")
    return paper.to_dict()


@router.get("/subscriptions/{subscription_id}/fetch-status")
async def get_fetch_status(subscription_id: str, request: Request):
    """Return manual fetch status for a subscription."""
    _service, _sub = _get_user_subscription(request, subscription_id)
    task_entry = _get_fetch_tasks(request).get(subscription_id)
    if task_entry is None:
        return {"status": "idle", "error": None}
    _task, task_status = task_entry
    return {"status": task_status["status"], "error": task_status["error"]}


@router.post("/subscriptions/{subscription_id}/fetch", status_code=202)
async def trigger_fetch(subscription_id: str, request: Request):
    """Manually trigger paper fetching for a subscription."""
    svc, sub = _get_user_subscription(request, subscription_id)
    scheduler = _get_scheduler(request)

    existing = _get_fetch_tasks(request).get(subscription_id)
    if existing is not None and existing[1]["status"] == "running":
        return {"status": "fetch_running", "subscription_id": subscription_id}

    task_status = {"status": "running", "error": None}

    async def _fetch_and_store():
        try:
            result = await scheduler.fetch_subscription(sub.subscription_id)
            task_status["status"] = "completed"
            logger.info(
                "manual fetch complete: subscription=%s papers=%d new=%d",
                subscription_id,
                result.get("paper_count", 0),
                result.get("new_count", 0),
            )
        except RuntimeError as exc:
            # Lock already held by another fetch.
            task_status["status"] = "fetch_running"
            task_status["error"] = str(exc)
            logger.warning("manual fetch already running: subscription=%s", subscription_id)
        except Exception as exc:
            task_status["status"] = "failed"
            task_status["error"] = str(exc)
            logger.error("manual fetch failed: subscription=%s error=%s", subscription_id, exc)

    task = asyncio.create_task(_fetch_and_store())
    _get_fetch_tasks(request)[subscription_id] = (task, task_status)

    return {"status": "fetch_started", "subscription_id": subscription_id}

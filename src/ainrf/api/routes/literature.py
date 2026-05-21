"""Literature tracking API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ainrf.auth.permissions import get_current_user
from ainrf.literature.service import LiteratureService

router = APIRouter(prefix="/literature", tags=["literature"])


def _get_service(request: Request) -> LiteratureService:
    service = getattr(request.app.state, "literature_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Literature service not initialized")
    return service


def _get_user_id(request: Request) -> str:
    return get_current_user(request)["id"]


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
    )
    return sub.to_dict()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: str, request: Request):
    user_id = _get_user_id(request)
    sub = _get_service(request).get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    _get_service(request).delete_subscription(subscription_id)


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
    svc.mark_read(paper_id)


@router.post("/papers/{paper_id}/convert", status_code=201)
async def convert_to_task(paper_id: str, request: Request):
    user_id = _get_user_id(request)
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    svc = _get_service(request)
    if not svc.user_owns_paper(user_id, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    paper = svc.convert_to_task(paper_id, task_id)
    return paper.to_dict()


@router.post("/subscriptions/{subscription_id}/fetch", status_code=202)
async def trigger_fetch(subscription_id: str, request: Request):
    """Manually trigger paper fetching for a subscription."""
    import asyncio

    user_id = _get_user_id(request)
    svc = _get_service(request)
    sub = svc.get_subscription(subscription_id)
    if sub is None or sub.user_id != user_id:
        raise HTTPException(status_code=404, detail="Subscription not found")

    api_key = getattr(request.app.state, "api_config", None)
    base_url = "http://127.0.0.1:8000"  # self-referencing for Claude calls

    from ainrf.literature.fetcher import fetch_for_subscription

    asyncio.create_task(fetch_for_subscription(sub, api_key or "", base_url))
    return {"status": "fetch_started"}

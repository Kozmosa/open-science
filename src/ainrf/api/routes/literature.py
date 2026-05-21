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


@router.get("/subscriptions")
async def list_subscriptions(request: Request):
    user = get_current_user(request)
    service = _get_service(request)
    subs = service.list_subscriptions(user["id"])
    return {"items": [s.to_dict() for s in subs]}


@router.post("/subscriptions", status_code=201)
async def create_subscription(request: Request):
    user = get_current_user(request)
    body = await request.json()
    service = _get_service(request)
    sub = service.create_subscription(
        user_id=user["id"],
        label=body.get("label", ""),
        keywords=body.get("keywords", []),
        arxiv_categories=body.get("arxiv_categories", []),
        frequency=body.get("frequency", "daily"),
    )
    return sub.to_dict()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: str, request: Request):
    _get_current_user(request)
    _get_service(request).delete_subscription(subscription_id)


def _get_current_user(request: Request):
    from ainrf.auth.permissions import get_current_user as gcu
    return gcu(request)


@router.get("/papers")
async def list_papers(
    request: Request,
    subscription_id: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    user = _get_current_user(request)
    papers = _get_service(request).list_papers(user["id"], subscription_id, unread_only, limit, offset)
    return {"items": [p.to_dict() for p in papers]}


@router.post("/papers/{paper_id}/read", status_code=204)
async def mark_read(paper_id: str, request: Request):
    _get_current_user(request)
    _get_service(request).mark_read(paper_id)


@router.post("/papers/{paper_id}/convert", status_code=201)
async def convert_to_task(paper_id: str, request: Request):
    _get_current_user(request)
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    paper = _get_service(request).convert_to_task(paper_id, task_id)
    return paper.to_dict()

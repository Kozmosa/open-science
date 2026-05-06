from __future__ import annotations

from fastapi import APIRouter, Request

from ainrf.monitor.models import ResourcesResponse

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=ResourcesResponse)
async def get_resources(request: Request) -> ResourcesResponse:
    monitor_service = getattr(request.app.state, "resource_monitor_service", None)
    if monitor_service is None:
        return ResourcesResponse(items=[])

    snapshots = monitor_service.get_snapshots()
    return ResourcesResponse(items=list(snapshots.values()))

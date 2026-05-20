from __future__ import annotations

from fastapi import APIRouter, Request

from ainrf.auth.permissions import get_current_user, is_admin
from ainrf.monitor.models import ResourcesResponse

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=ResourcesResponse)
async def get_resources(request: Request) -> ResourcesResponse:
    user = get_current_user(request)
    monitor_service = getattr(request.app.state, "resource_monitor_service", None)
    if monitor_service is None:
        return ResourcesResponse(items=[])

    snapshots = monitor_service.get_snapshots()
    if is_admin(user):
        return ResourcesResponse(items=list(snapshots.values()))

    # Non-admin: only return resources for environments the user can access
    auth_svc = getattr(request.app.state, "auth_service", None)
    if auth_svc is not None:
        accessible_ids = set(auth_svc.get_user_environment_ids(user["id"]))
    else:
        accessible_ids = set()
    filtered = [s for s in snapshots.values() if s.environment_id in accessible_ids]
    return ResourcesResponse(items=filtered)

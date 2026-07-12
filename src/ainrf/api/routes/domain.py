"""Mode-gated v2 adapters; legacy routes remain authoritative until B7."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.auth.permissions import get_current_user
from ainrf.domain import DomainPermissionError, DomainService
from ainrf.domain_control import DomainModelMode

router = APIRouter(prefix="/domain", tags=["domain-v2"])


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    service = getattr(request.app.state, "domain_service", None)
    mode = request.app.state.api_config.domain_model_mode
    ready = service is not None and service.v2_ready()
    return {
        "domain_contract_version": 2 if ready else 1,
        "mode": mode.value,
        "standard_task_create": ready,
        "project_context": ready,
        "workspace_links": ready,
        "task_attempts": ready,
    }


def _service(request: Request) -> DomainService:
    service = getattr(request.app.state, "domain_service", None)
    if service is None or request.app.state.api_config.domain_model_mode is not DomainModelMode.V2:
        raise HTTPException(status_code=404, detail="Domain v2 is unavailable")
    if not service.v2_ready():
        raise HTTPException(status_code=503, detail="Domain v2 cutover is not ready")
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
            idempotency_key=request.headers.get("Idempotency-Key", ""),
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
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
    except Exception as exc:
        raise _translate(exc) from exc

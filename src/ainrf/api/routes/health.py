from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from ainrf.api.schemas import ApiStatus, HealthResponse
from ainrf.execution import SSHExecutor

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> JSONResponse | HealthResponse:
    api_config = request.app.state.api_config
    payload = api_config.as_public_health_payload()
    container_config = api_config.container_config
    if container_config is None:
        return HealthResponse(status=ApiStatus.OK, **payload)

    executor = SSHExecutor(container_config)
    health = await executor.ping()
    response = HealthResponse(
        status=ApiStatus.OK if health.ssh_ok else ApiStatus.DEGRADED,
        container_health={
            "ssh_ok": health.ssh_ok,
            "claude_ok": health.claude_ok,
            "project_dir_writable": health.project_dir_writable,
            "claude_version": health.claude_version,
            "gpu_models": health.gpu_models,
            "cuda_version": health.cuda_version,
            "disk_free_bytes": health.disk_free_bytes,
            "warnings": health.warnings,
        },
        detail=None if health.ssh_ok else "Container connectivity degraded",
        **payload,
    )
    if health.ssh_ok:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(mode="json"),
    )

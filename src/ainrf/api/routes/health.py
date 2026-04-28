from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from ainrf.api.schemas import ApiStatus, HealthResponse
from ainrf.execution import SSHExecutor
from ainrf.runtime.readiness import check_runtime_readiness

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> JSONResponse | HealthResponse:
    api_config = request.app.state.api_config
    environment_service = request.app.state.environment_service
    localhost = environment_service.get_environment("env-localhost")
    public_payload = api_config.as_public_health_payload()
    runtime_readiness = getattr(request.app.state, "runtime_readiness", None)
    if runtime_readiness is None:
        runtime_readiness = cast(
            dict[str, object],
            check_runtime_readiness(localhost.code_server_path).as_public_payload(),
        )
    container_config = api_config.container_config
    if container_config is None:
        return HealthResponse(
            status=ApiStatus.OK,
            state_root=str(public_payload["state_root"]),
            startup_cwd=str(public_payload["startup_cwd"]),
            default_workspace_dir=str(public_payload["default_workspace_dir"]),
            container_configured=bool(public_payload["container_configured"]),
            runtime_readiness=runtime_readiness,
        )

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
        state_root=str(public_payload["state_root"]),
        startup_cwd=str(public_payload["startup_cwd"]),
        default_workspace_dir=str(public_payload["default_workspace_dir"]),
        container_configured=bool(public_payload["container_configured"]),
        runtime_readiness=runtime_readiness,
    )
    if health.ssh_ok:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(mode="json"),
    )

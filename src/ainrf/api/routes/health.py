from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Request

from ainrf.api.schemas import ApiStatus, HealthResponse
from ainrf.execution import SSHExecutor
from ainrf.runtime.readiness import check_runtime_readiness

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> JSONResponse | HealthResponse:
    api_config = request.app.state.api_config
    public_payload = api_config.as_public_health_payload()
    runtime_readiness = getattr(request.app.state, "runtime_readiness", None)
    if runtime_readiness is None:
        runtime_readiness = cast(
            dict[str, object],
            check_runtime_readiness().as_public_payload(),
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

    async with SSHExecutor(container_config) as executor:
        health = await executor.ping(timeout=2)
        return HealthResponse(
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
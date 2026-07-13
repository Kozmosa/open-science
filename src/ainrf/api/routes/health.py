"""Health check endpoint with component-level probes.

Exposes ``GET /health`` returning:
  - Overall status (``ok`` / ``degraded``)
  - Per-component health (database, Litefuse, filesystem, runtime)
  - Process uptime
  - Container health (when container is configured)
"""

from __future__ import annotations

import logging
import sqlite3
import time as _time
from typing import cast

from fastapi import APIRouter, Request

from ainrf.api.schemas import ApiStatus, ComponentHealth, HealthResponse
from ainrf.execution import SSHExecutor
from ainrf.runtime.readiness import check_runtime_readiness

logger = logging.getLogger(__name__)

router = APIRouter()

# Process start time for uptime calculation.
_START_TIME = _time.monotonic()


def _probe_database(state_root: str) -> ComponentHealth:
    """Probe SQLite database connectivity."""
    import os as _os

    start = _time.monotonic()
    try:
        db_path = _os.path.join(state_root, "runtime", "agentic_researcher.sqlite3")
        if not _os.path.exists(db_path):
            return ComponentHealth(
                status="ok",
                latency_ms=round((_time.monotonic() - start) * 1000, 1),
                error=None,
            )
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return ComponentHealth(
            status="ok",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
        )
    except Exception as exc:
        return ComponentHealth(
            status="unhealthy",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
            error=str(exc),
        )


def _probe_litefuse(request: Request) -> ComponentHealth:
    """Probe Litefuse observability backend connectivity."""
    start = _time.monotonic()
    reporter = getattr(request.app.state, "observability_reporter", None)
    if reporter is None:
        return ComponentHealth(
            status="degraded",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
            error="Observability reporter not configured",
        )
    try:
        # LitefuseReporter wraps the SafeReporter; check the inner reporter.
        inner = getattr(reporter, "_inner", reporter)
        if hasattr(inner, "is_healthy") and not inner.is_healthy():
            return ComponentHealth(
                status="degraded",
                latency_ms=round((_time.monotonic() - start) * 1000, 1),
                error="Litefuse backend unreachable",
            )
    except Exception as exc:
        return ComponentHealth(
            status="degraded",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
            error=str(exc),
        )
    return ComponentHealth(
        status="ok",
        latency_ms=round((_time.monotonic() - start) * 1000, 1),
    )


def _probe_filesystem(state_root: str) -> ComponentHealth:
    """Probe filesystem writability."""
    import os as _os
    import tempfile

    start = _time.monotonic()
    try:
        test_dir = _os.path.join(state_root, "health_check")
        _os.makedirs(test_dir, exist_ok=True)
        with tempfile.TemporaryFile(dir=test_dir) as f:
            f.write(b"ok")
        return ComponentHealth(
            status="ok",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
        )
    except Exception as exc:
        return ComponentHealth(
            status="unhealthy",
            latency_ms=round((_time.monotonic() - start) * 1000, 1),
            error=str(exc),
        )


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    api_config = request.app.state.api_config
    public_payload = api_config.as_public_health_payload()
    runtime_readiness = getattr(request.app.state, "runtime_readiness", None)
    if runtime_readiness is None:
        runtime_readiness = cast(
            dict[str, object],
            check_runtime_readiness().as_public_payload(),
        )

    # ── Component probes ──────────────────────────────────────────
    state_root = str(public_payload["state_root"])
    checks: dict[str, ComponentHealth] = {}
    checks["database"] = _probe_database(state_root)
    checks["litefuse"] = _probe_litefuse(request)
    checks["filesystem"] = _probe_filesystem(state_root)
    checks["runtime"] = ComponentHealth(
        status="ok" if runtime_readiness.get("all_ready") else "degraded",
        error=(
            None
            if runtime_readiness.get("all_ready")
            else "Some runtime binaries not found on PATH (expected in test/dev)"
        ),
    )

    # Overall: unhealthy if any critical component is unhealthy.
    # "degraded" components are advisory only — they do not force the
    # overall status to degraded (e.g., runtime binaries not found in a
    # test environment is expected).
    overall = ApiStatus.OK
    for check in checks.values():
        if check.status == "unhealthy":
            overall = ApiStatus.DEGRADED
            break

    uptime_seconds = _time.monotonic() - _START_TIME

    container_config = api_config.container_config
    if container_config is None or not api_config.runtime_reconciliation_enabled:
        return HealthResponse(
            status=overall,
            state_root=str(public_payload["state_root"]),
            startup_cwd=str(public_payload["startup_cwd"]),
            default_workspace_dir=str(public_payload["default_workspace_dir"]),
            container_configured=bool(public_payload["container_configured"]),
            runtime_readiness=runtime_readiness,
            detail=(
                "Remote runtime probes disabled by configuration"
                if container_config is not None and not api_config.runtime_reconciliation_enabled
                else None
            ),
            uptime_seconds=round(uptime_seconds, 1),
            checks=checks,
        )

    async with SSHExecutor(container_config) as executor:
        health = await executor.ping(timeout=2)
        container_status = ApiStatus.OK if health.ssh_ok else ApiStatus.DEGRADED
        if container_status == ApiStatus.DEGRADED and overall == ApiStatus.OK:
            overall = ApiStatus.DEGRADED
        return HealthResponse(
            status=overall,
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
            uptime_seconds=round(uptime_seconds, 1),
            checks=checks,
        )

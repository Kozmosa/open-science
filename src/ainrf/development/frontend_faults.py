from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path

from fastapi import Request
from starlette.responses import JSONResponse, Response

from ainrf.development.frontend_profiles import FRONTEND_DEV_FIXTURE_VERSION


_PROFILE_MARKER_NAME = "frontend-dev-fixture.json"
_FAULT_HEADER = "X-OpenScience-Dev-Fault"
_PROFILE_HEADER = "X-OpenScience-Dev-Fault-Profile"


class FrontendDevFaultProfile(StrEnum):
    NONE = "none"
    LATENCY = "latency"
    TRANSIENT = "transient"
    RESOURCES = "resources"
    OFFLINE = "offline"


def normalize_frontend_dev_fault_profile(
    value: FrontendDevFaultProfile | str,
) -> FrontendDevFaultProfile:
    if isinstance(value, FrontendDevFaultProfile):
        return value
    try:
        return FrontendDevFaultProfile(value.strip().lower())
    except ValueError as exc:
        choices = ", ".join(profile.value for profile in FrontendDevFaultProfile)
        raise ValueError(f"unknown frontend fault profile; expected one of: {choices}") from exc


def configured_frontend_dev_fault_profile(
    state_root: Path,
    *,
    production: bool,
) -> FrontendDevFaultProfile:
    if production:
        return FrontendDevFaultProfile.NONE
    marker_path = state_root / "runtime" / _PROFILE_MARKER_NAME
    if not marker_path.is_file():
        return FrontendDevFaultProfile.NONE
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("frontend fixture marker is malformed")
    if payload.get("fixture_version") != FRONTEND_DEV_FIXTURE_VERSION:
        raise ValueError("frontend fixture marker version is unsupported")
    value = payload.get("fault_profile", FrontendDevFaultProfile.NONE.value)
    if not isinstance(value, str):
        raise ValueError("frontend fixture fault profile is malformed")
    return normalize_frontend_dev_fault_profile(value)


def build_frontend_dev_fault_middleware(
    state_root: Path,
    *,
    production: bool,
    latency_seconds: float = 0.75,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    profile = configured_frontend_dev_fault_profile(state_root, production=production)
    if latency_seconds < 0:
        raise ValueError("frontend fault latency must be non-negative")
    seen_transient_requests: set[tuple[str, str]] = set()
    transient_lock = asyncio.Lock()

    async def frontend_dev_fault_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        normalized_path = _normalized_api_path(request.url.path)
        if profile is FrontendDevFaultProfile.NONE or _is_exempt(normalized_path):
            return await call_next(request)

        fault: str | None = None
        if profile is FrontendDevFaultProfile.LATENCY:
            await asyncio.sleep(latency_seconds)
            fault = f"latency:{latency_seconds:g}s"
        elif profile is FrontendDevFaultProfile.TRANSIENT and request.method in {"GET", "HEAD"}:
            key = (request.method, normalized_path)
            async with transient_lock:
                if key not in seen_transient_requests:
                    seen_transient_requests.add(key)
                    return _fault_response(profile, "transient:first-request")
        elif (
            profile is FrontendDevFaultProfile.RESOURCES
            and request.method in {"GET", "HEAD"}
            and normalized_path in {"/resources", "/tasks/token-usage"}
        ):
            return _fault_response(profile, "resources:unavailable")
        elif profile is FrontendDevFaultProfile.OFFLINE:
            return _fault_response(profile, "offline:unavailable")

        response = await call_next(request)
        response.headers[_PROFILE_HEADER] = profile.value
        if fault is not None:
            response.headers[_FAULT_HEADER] = fault
        return response

    return frontend_dev_fault_middleware


def _normalized_api_path(path: str) -> str:
    for prefix in ("/api", "/v1"):
        if path == prefix:
            return "/"
        if path.startswith(f"{prefix}/"):
            return path[len(prefix) :]
    return path


def _is_exempt(path: str) -> bool:
    return path == "/health" or path.startswith(("/auth/", "/docs", "/openapi", "/redoc"))


def _fault_response(profile: FrontendDevFaultProfile, fault: str) -> JSONResponse:
    return JSONResponse(
        {
            "detail": "Synthetic frontend development fault",
            "fault_profile": profile.value,
            "fault": fault,
        },
        status_code=503,
        headers={_PROFILE_HEADER: profile.value, _FAULT_HEADER: fault},
    )

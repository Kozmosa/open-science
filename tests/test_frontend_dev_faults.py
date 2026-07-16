"""Deterministic request-fault profiles for managed frontend fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.development import frontend_faults as fault_module
from ainrf.development.frontend_faults import build_frontend_dev_fault_middleware
from ainrf.development.frontend_profiles import FRONTEND_DEV_FIXTURE_VERSION


pytestmark = [pytest.mark.unit]


def _write_marker(state_root: Path, fault_profile: str) -> None:
    marker = state_root / "runtime" / "frontend-dev-fixture.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "artifact_sha": "a" * 64,
                "fixture_version": FRONTEND_DEV_FIXTURE_VERSION,
                "profile": "full",
                "fault_profile": fault_profile,
            }
        ),
        encoding="utf-8",
    )


def _app(state_root: Path, *, production: bool = False) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(build_frontend_dev_fault_middleware(state_root, production=production))

    @app.get("/{path:path}")
    async def echo(path: str) -> dict[str, str]:
        return {"path": path}

    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


def test_fault_middleware_requires_managed_marker_and_never_runs_in_production(
    tmp_path: Path,
) -> None:
    unmarked = asyncio.run(_get(_app(tmp_path / "unmarked"), "/api/domain/projects"))
    _write_marker(tmp_path / "marked", "offline")
    production = asyncio.run(
        _get(_app(tmp_path / "marked", production=True), "/api/domain/projects")
    )

    assert unmarked.status_code == 200
    assert production.status_code == 200
    assert "X-OpenScience-Dev-Fault" not in production.headers


def test_resources_fault_is_endpoint_scoped_and_auth_health_stay_available(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "fixture"
    _write_marker(state_root, "resources")
    app = _app(state_root)

    resources = asyncio.run(_get(app, "/api/resources"))
    usage = asyncio.run(_get(app, "/api/tasks/token-usage?include_archived=true"))
    projects = asyncio.run(_get(app, "/api/domain/projects"))
    health = asyncio.run(_get(app, "/api/health"))

    assert resources.status_code == 503
    assert usage.status_code == 503
    assert resources.headers["X-OpenScience-Dev-Fault"] == "resources:unavailable"
    assert projects.status_code == 200
    assert health.status_code == 200


def test_transient_fault_fails_each_read_path_once_then_recovers(tmp_path: Path) -> None:
    state_root = tmp_path / "fixture"
    _write_marker(state_root, "transient")
    app = _app(state_root)

    first = asyncio.run(_get(app, "/api/domain/projects"))
    second = asyncio.run(_get(app, "/api/domain/projects"))
    another = asyncio.run(_get(app, "/api/domain/workspaces"))

    assert first.status_code == 503
    assert first.headers["X-OpenScience-Dev-Fault"] == "transient:first-request"
    assert second.status_code == 200
    assert second.headers["X-OpenScience-Dev-Fault-Profile"] == "transient"
    assert another.status_code == 503


def test_latency_fault_is_deterministic_without_delaying_exempt_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "fixture"
    _write_marker(state_root, "latency")
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(fault_module.asyncio, "sleep", fake_sleep)
    app = _app(state_root)

    response = asyncio.run(_get(app, "/api/domain/projects"))
    auth = asyncio.run(_get(app, "/api/auth/check"))

    assert response.status_code == 200
    assert response.headers["X-OpenScience-Dev-Fault"] == "latency:0.75s"
    assert auth.status_code == 200
    assert delays == [0.75]

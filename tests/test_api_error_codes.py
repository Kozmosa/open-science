"""Stable error-code contract for user-reachable domain errors."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from tests.testutil import CURRENT_ARTIFACT_SHA, prepare_current_test_state, seed_user

pytestmark = [pytest.mark.api]


def _app(state_root: Path) -> FastAPI:
    prepare_current_test_state(state_root)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("error-codes-key")}),
            state_root=state_root,
            domain_artifact_sha=CURRENT_ARTIFACT_SHA,
        )
    )


def _headers(app: FastAPI, username: str, user_id: str, role: str = "member") -> dict[str, str]:
    auth = app.state.auth_service
    seed_user(auth, username, "error-codes-password", role=role, user_id=user_id)
    token = auth.login(username=username, password="error-codes-password")
    return {"Authorization": f"Bearer {token['access_token']}"}


@pytest.mark.anyio
async def test_task_creation_without_idempotency_key_carries_stable_code(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root)
    headers = _headers(app, "codes-owner", "codes-owner")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/tasks",
            headers=headers,
            json={
                "title": "Task",
                "prompt": "Prompt",
                "project_id": "project-irrelevant",
                "workspace_id": "workspace-irrelevant",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
            },
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "idempotency_key_required"
    assert detail["message"] == "Idempotency-Key is required"


@pytest.mark.anyio
async def test_task_creation_denial_for_invisible_project_keeps_plain_detail(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root)
    headers = _headers(app, "codes-outsider", "codes-outsider")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/tasks",
            headers={**headers, "Idempotency-Key": "invisible-project"},
            json={
                "title": "Task",
                "prompt": "Prompt",
                "project_id": "project-invisible",
                "workspace_id": "workspace-invisible",
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@pytest.mark.anyio
async def test_context_publish_denial_carries_stable_code(state_root: Path, tmp_path: Path) -> None:
    app = _app(state_root)
    owner_headers = _headers(app, "codes-owner", "codes-owner")
    editor_headers = _headers(app, "codes-editor", "codes-editor")
    project = app.state.project_module.create_project(
        {"id": "codes-owner", "role": "member"}, name="Codes project"
    )
    project_id = str(project["project_id"])
    app.state.project_module.add_member(
        project_id,
        "codes-editor",
        "editor",
        False,
        {"id": "codes-owner", "role": "member"},
        idempotency_key="member",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/domain/projects/{project_id}/context/publish",
            headers={**editor_headers, "Idempotency-Key": "publish-denied"},
        )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "project_publish_required"
    assert detail["message"] == "Project publish permission is required"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        allowed = await client.post(
            f"/api/domain/projects/{project_id}/context/publish",
            headers={**owner_headers, "Idempotency-Key": "publish-owner"},
        )
    assert allowed.status_code == 200


@pytest.mark.anyio
async def test_environment_alias_conflict_carries_stable_code(
    state_root: Path, tmp_path: Path
) -> None:
    app = _app(state_root)
    admin_headers = _headers(app, "codes-admin", "codes-admin", role="admin")
    app.state.environment_module.create_environment(
        {"id": "codes-admin", "role": "admin"},
        alias="codes-host",
        display_name="Codes host",
        connection={"host": "127.0.0.1"},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/domain/environments",
            headers={**admin_headers, "Idempotency-Key": "env-alias"},
            json={"alias": "codes-host", "display_name": "Duplicate", "host": "127.0.0.2"},
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "environment_alias_exists"
    assert detail["message"] == "Environment alias already exists"

"""Canonical Project and Workspace read contracts for the frontend phases."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain import ProjectContextService, TaskApplicationService
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover


pytestmark = [pytest.mark.api]

_API_KEY = "frontend-contract-key"
_API_USER = {"id": "api-key-user", "role": "user"}
_ADMIN = {"id": "admin", "role": "admin"}


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )


def _seed_frontend_contract(app: FastAPI, state_root: Path) -> dict[str, str]:
    domain = app.state.domain_service
    auth = AuthService(state_root=state_root)
    auth.initialize()

    primary_environment = domain.create_environment(
        _ADMIN,
        alias="frontend-primary",
        display_name="Frontend primary",
        connection={"default_workdir": "/tmp/frontend-primary"},
    )
    blocked_environment = domain.create_environment(
        _ADMIN,
        alias="frontend-blocked",
        display_name="Frontend blocked",
        connection={"default_workdir": "/tmp/frontend-blocked"},
    )
    primary_environment_id = str(primary_environment["environment_id"])
    blocked_environment_id = str(blocked_environment["environment_id"])
    for environment_id in (primary_environment_id, blocked_environment_id):
        auth.grant_environment(
            env_id=environment_id,
            user_id="api-key-user",
            max_tasks=None,
            granted_by="admin",
            reason="frontend contract fixture",
        )

    project = domain.create_project(_API_USER, name="Executable project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        _API_USER,
        environment_id=primary_environment_id,
        canonical_path="/tmp/frontend-primary/workspace",
        label="Primary workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(
        project_id,
        workspace_id,
        _API_USER,
        idempotency_key="frontend-workspace-link",
    )
    domain.set_primary_workspace(
        project_id,
        workspace_id,
        _API_USER,
        idempotency_key="frontend-primary-link",
    )

    blocked_workspace = domain.create_workspace(
        _API_USER,
        environment_id=blocked_environment_id,
        canonical_path="/tmp/frontend-blocked/workspace",
        label="Blocked workspace",
    )
    blocked_workspace_id = str(blocked_workspace["workspace_id"])
    auth.revoke_environment(
        blocked_environment_id,
        "api-key-user",
        revoked_by="admin",
        reason="exercise no-execute projection",
    )

    empty_project = domain.create_project(_API_USER, name="Needs workspace")
    empty_project_id = str(empty_project["project_id"])

    context: ProjectContextService = app.state.project_context_service
    context.save_draft(project_id, "Frontend contract context", _API_USER)
    context.publish(project_id, _API_USER)
    TaskApplicationService(state_root, artifact_sha=V2_ARTIFACT_SHA).create_task(
        _API_USER,
        project_id=project_id,
        workspace_id=workspace_id,
        title="Queued frontend task",
        prompt="Exercise the frontend projection",
        researcher_type="vanilla",
        harness_engine="claude-code",
        idempotency_key="frontend-contract-task",
    )

    return {
        "project_id": project_id,
        "empty_project_id": empty_project_id,
        "workspace_id": workspace_id,
        "blocked_workspace_id": blocked_workspace_id,
        "primary_environment_id": primary_environment_id,
    }


@pytest.mark.anyio
async def test_frontend_project_contract_exposes_role_activity_and_attention(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/domain/projects", headers={"X-API-Key": _API_KEY})
        detail = await client.get(
            f"/domain/projects/{ids['project_id']}", headers={"X-API-Key": _API_KEY}
        )

    assert response.status_code == 200
    assert detail.status_code == 200
    items = cast(list[dict[str, object]], response.json()["items"])
    project = next(item for item in items if item["project_id"] == ids["project_id"])
    empty = next(item for item in items if item["project_id"] == ids["empty_project_id"])

    assert project["current_user_role"] == "owner"
    assert project["workspace_count"] == 1
    assert project["executable_workspace_count"] == 1
    assert project["task_count"] == 1
    assert project["active_task_count"] == 1
    assert project["attention_required"] is False
    assert cast(dict[str, object], project["permissions"])["can_create_task"] is True
    primary = cast(dict[str, object], project["primary_workspace"])
    assert primary["workspace_id"] == ids["workspace_id"]
    assert primary["environment_id"] == ids["primary_environment_id"]
    assert primary["can_execute"] is True

    assert empty["attention_required"] is True
    assert empty["attention_reasons"] == ["no_workspace"]
    assert cast(dict[str, object], empty["permissions"])["can_create_task"] is False
    assert detail.json() == project


@pytest.mark.anyio
async def test_frontend_workspace_contract_distinguishes_execution_access(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/domain/workspaces", headers={"X-API-Key": _API_KEY})
        detail = await client.get(
            f"/domain/workspaces/{ids['workspace_id']}", headers={"X-API-Key": _API_KEY}
        )
        missing = await client.get(
            "/domain/workspaces/not-visible", headers={"X-API-Key": _API_KEY}
        )

    assert response.status_code == 200
    assert detail.status_code == 200
    assert missing.status_code == 404
    items = cast(list[dict[str, object]], response.json()["items"])
    workspace = next(item for item in items if item["workspace_id"] == ids["workspace_id"])
    blocked = next(item for item in items if item["workspace_id"] == ids["blocked_workspace_id"])

    assert workspace["can_execute"] is True
    assert workspace["active_task_count"] == 1
    assert (
        cast(dict[str, object], workspace["environment"])["environment_id"]
        == ids["primary_environment_id"]
    )
    links = cast(list[dict[str, object]], workspace["project_links"])
    assert links == [
        {
            "project_id": ids["project_id"],
            "project_name": "Executable project",
            "project_status": "active",
            "current_user_role": "owner",
            "link_status": "active",
            "is_primary": True,
            "can_execute": True,
            "cannot_execute_reason": None,
        }
    ]
    assert workspace["git_status"] == {
        "state": "not_collected",
        "branch": None,
        "is_dirty": None,
        "observed_at": None,
    }
    assert detail.json() == workspace

    assert blocked["can_execute"] is False
    assert blocked["cannot_execute_reason"] == "environment_grant_required"
    assert blocked["project_links"] == []

"""v2 compatibility coverage for Project, Workspace, and Environment routes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import seed_user

pytestmark = [pytest.mark.api]


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    """Create a v2 application behind the real committed-cutover fuse."""

    prepare_committed_v2_cutover(state_root, tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("resource-adapter-key")}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )
    return app


def _headers(app: FastAPI, username: str, user_id: str, role: str) -> dict[str, str]:
    auth = app.state.auth_service
    seed_user(auth, username, "resource-adapter-password", role=role, user_id=user_id)
    token = auth.login(username=username, password="resource-adapter-password")
    return {"Authorization": f"Bearer {token['access_token']}"}


def _project_with_primary(
    app: FastAPI,
    state_root: Path,
    owner: dict[str, object],
) -> tuple[str, str]:
    domain = app.state.domain_service
    environment = domain.create_environment(
        {"id": "admin", "role": "admin"},
        alias="resource-adapter-host",
        display_name="Resource adapter host",
        connection={"default_workdir": str(state_root / "workspaces")},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id=str(owner["id"]),
        max_tasks=None,
        granted_by="admin",
        reason="resource adapter test",
    )
    project = domain.create_project(owner, name="Adapter Project")
    project_id = str(project["project_id"])
    primary = domain.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path=str(state_root / "primary-workspace"),
        label="Primary",
        legacy_project_id=project_id,
    )
    domain.set_primary_workspace(
        project_id,
        str(primary["workspace_id"]),
        owner,
        idempotency_key="resource-adapter-primary",
    )
    return project_id, environment_id


@pytest.mark.anyio
async def test_v2_project_adapter_preserves_visibility_and_deprecation_headers(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner: dict[str, object] = {"id": "owner-id", "role": "member"}
    owner_headers = _headers(app, "adapter-owner", "owner-id", "member")
    viewer_headers = _headers(app, "adapter-viewer", "viewer-id", "member")
    outsider_headers = _headers(app, "adapter-outsider", "outsider-id", "member")
    project_id, _ = _project_with_primary(app, state_root, owner)
    app.state.domain_service.add_member(project_id, "viewer-id", "viewer", False, owner)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner_read = await client.get(f"/projects/{project_id}", headers=owner_headers)
        viewer_write = await client.patch(
            f"/projects/{project_id}", headers=viewer_headers, json={"name": "Denied"}
        )
        outsider_read = await client.get(f"/projects/{project_id}", headers=outsider_headers)
        refs = await client.get(f"/projects/{project_id}/environment-refs", headers=owner_headers)

    assert owner_read.status_code == 200
    assert owner_read.headers["Deprecation"] == "true"
    assert owner_read.json()["default_workspace_id"]
    assert viewer_write.status_code == 403
    assert outsider_read.status_code == 404
    assert refs.status_code == 200
    assert refs.json()["items"][0]["is_default"] is True


@pytest.mark.anyio
async def test_v2_workspace_delete_unregisters_without_deleting_directory(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner: dict[str, object] = {"id": "workspace-owner", "role": "member"}
    headers = _headers(app, "workspace-owner", "workspace-owner", "member")
    project_id, _ = _project_with_primary(app, state_root, owner)
    workspace_path = state_root / "retained-workspace"
    workspace_path.mkdir()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/workspaces",
            headers=headers,
            json={
                "project_id": project_id,
                "label": "Retained",
                "default_workdir": str(workspace_path),
                "workspace_prompt": "Keep the directory.",
            },
        )
        workspace_id = created.json()["workspace_id"]
        deleted = await client.delete(f"/workspaces/{workspace_id}", headers=headers)
        hidden = await client.get(f"/workspaces/{workspace_id}", headers=headers)

    assert created.status_code == 200
    assert created.headers["Deprecation"] == "true"
    assert deleted.status_code == 204
    assert deleted.headers["Deprecation"] == "true"
    assert workspace_path.is_dir()
    assert hidden.status_code == 404
    assert app.state.domain_service.workspace(workspace_id, owner)["status"] == "unregistered"


@pytest.mark.anyio
async def test_v2_environment_delete_disables_the_durable_environment(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    headers = _headers(app, "adapter-admin", "admin", "admin")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/environments",
            headers=headers,
            json={"alias": "disable-me", "display_name": "Disable me", "host": "localhost"},
        )
        environment_id = created.json()["id"]
        deleted = await client.delete(f"/environments/{environment_id}", headers=headers)
        hidden = await client.get(f"/environments/{environment_id}", headers=headers)

    assert created.status_code == 201
    assert created.headers["Deprecation"] == "true"
    assert deleted.status_code == 204
    assert deleted.headers["Deprecation"] == "true"
    assert hidden.status_code == 404
    assert (
        app.state.domain_service.environment(environment_id, {"id": "admin", "role": "admin"})[
            "status"
        ]
        == "disabled"
    )

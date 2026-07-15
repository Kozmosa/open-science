"""v2 compatibility coverage for Project, Workspace, and Environment routes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain.environment_facade import PersistentEnvironmentFacade
from ainrf.domain_control import DomainModelMode
from ainrf.environments.models import (
    DetectionSnapshot,
    DetectionStatus,
    EnvironmentRegistryEntry,
    utc_now,
)
from ainrf.environments.probing import EnvironmentProbeOutcome
from ainrf.monitor.service import ResourceMonitorService
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


def _write_headers(headers: dict[str, str], idempotency_key: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": idempotency_key}


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
    )
    domain.attach_workspace(
        project_id,
        str(primary["workspace_id"]),
        owner,
        idempotency_key="resource-adapter-attach",
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
            f"/projects/{project_id}",
            headers=_write_headers(viewer_headers, "viewer-project-update"),
            json={"name": "Denied"},
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
            headers=_write_headers(headers, "workspace-create"),
            json={
                "project_id": project_id,
                "label": "Retained",
                "default_workdir": str(workspace_path),
                "workspace_prompt": "Keep the directory.",
            },
        )
        workspace_id = created.json()["workspace_id"]
        deleted = await client.delete(
            f"/workspaces/{workspace_id}",
            headers=_write_headers(headers, "workspace-delete"),
        )
        hidden = await client.get(f"/workspaces/{workspace_id}", headers=headers)

    assert created.status_code == 200
    assert created.headers["Deprecation"] == "true"
    assert deleted.status_code == 204
    assert deleted.headers["Deprecation"] == "true"
    assert workspace_path.is_dir()
    assert hidden.status_code == 404
    assert app.state.domain_service.workspace(workspace_id, owner)["status"] == "unregistered"


@pytest.mark.anyio
async def test_v2_workspace_registration_rejects_an_unusable_path_without_persisting(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner: dict[str, object] = {"id": "workspace-preflight-owner", "role": "member"}
    headers = _headers(app, "workspace-preflight-owner", "workspace-preflight-owner", "member")
    _, environment_id = _project_with_primary(app, state_root, owner)
    before = app.state.domain_service.list_workspaces(owner)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        rejected = await client.post(
            "/domain/workspaces",
            headers=_write_headers(headers, "workspace-preflight-create"),
            json={
                "environment_id": environment_id,
                "canonical_path": str(state_root / "missing-workspace"),
                "label": "Missing",
            },
        )

    assert rejected.status_code == 409
    assert "existing directory" in rejected.json()["detail"]
    assert app.state.domain_service.list_workspaces(owner) == before


@pytest.mark.anyio
async def test_v2_workspace_registration_replays_before_rechecking_the_path(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner: dict[str, object] = {"id": "workspace-replay-owner", "role": "member"}
    headers = _headers(app, "workspace-replay-owner", "workspace-replay-owner", "member")
    _, environment_id = _project_with_primary(app, state_root, owner)
    workspace_path = state_root / "replay-workspace"
    workspace_path.mkdir()
    payload = {
        "environment_id": environment_id,
        "canonical_path": str(workspace_path),
        "label": "Replay",
    }
    write_headers = _write_headers(headers, "workspace-preflight-replay")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post("/domain/workspaces", headers=write_headers, json=payload)
        workspace_path.rmdir()
        replayed = await client.post("/domain/workspaces", headers=write_headers, json=payload)

    assert created.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json() == created.json()


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
            headers=_write_headers(headers, "environment-create"),
            json={"alias": "disable-me", "display_name": "Disable me", "host": "localhost"},
        )
        environment_id = created.json()["id"]
        deleted = await client.delete(
            f"/environments/{environment_id}",
            headers=_write_headers(headers, "environment-delete"),
        )
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


@pytest.mark.anyio
async def test_v2_environment_mutation_hides_ungranted_resources_but_denies_visible_grantees(
    state_root: Path,
    tmp_path: Path,
) -> None:
    """Environment mutation preserves the domain 404/403 visibility boundary."""

    app = _v2_app(state_root, tmp_path)
    admin_headers = _headers(app, "visibility-admin", "admin", "admin")
    grantee_headers = _headers(app, "visibility-grantee", "grantee-id", "member")
    outsider_headers = _headers(app, "visibility-outsider", "outsider-id", "member")
    environment = app.state.domain_service.create_environment(
        {"id": "admin", "role": "admin"},
        alias="visibility-boundary",
        display_name="Visibility boundary",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    app.state.auth_service.grant_environment(
        env_id=environment_id,
        user_id="grantee-id",
        max_tasks=None,
        granted_by="admin",
        reason="visible without registry management",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        outsider_update = await client.patch(
            f"/environments/{environment_id}",
            headers=_write_headers(outsider_headers, "outsider-environment-update"),
            json={"display_name": "Must remain hidden"},
        )
        outsider_delete = await client.delete(
            f"/environments/{environment_id}",
            headers=_write_headers(outsider_headers, "outsider-environment-delete"),
        )
        grantee_update = await client.patch(
            f"/environments/{environment_id}",
            headers=_write_headers(grantee_headers, "grantee-environment-update"),
            json={"display_name": "Cannot manage"},
        )
        grantee_delete = await client.delete(
            f"/environments/{environment_id}",
            headers=_write_headers(grantee_headers, "grantee-environment-delete"),
        )
        admin_update = await client.patch(
            f"/environments/{environment_id}",
            headers=_write_headers(admin_headers, "admin-environment-update"),
            json={"display_name": "Admin update"},
        )

    assert outsider_update.status_code == 404
    assert outsider_delete.status_code == 404
    assert grantee_update.status_code == 403
    assert grantee_delete.status_code == 403
    assert admin_update.status_code == 200
    assert admin_update.json()["display_name"] == "Admin update"


@pytest.mark.anyio
async def test_v2_project_write_requires_a_stable_idempotency_transport(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    headers = _headers(app, "idempotency-owner", "idempotency-owner", "member")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.post("/projects", headers=headers, json={"name": "Missing"})
        conflict = await client.post(
            "/projects",
            headers=_write_headers(headers, "header-key"),
            json={"name": "Conflict", "idempotency_key": "body-key"},
        )
        first = await client.post(
            "/projects",
            headers=_write_headers(headers, "project-create"),
            json={"name": "Stable", "idempotency_key": "project-create"},
        )
        replay = await client.post(
            "/projects",
            headers=_write_headers(headers, "project-create"),
            json={"name": "Stable", "idempotency_key": "project-create"},
        )
        changed = await client.post(
            "/projects",
            headers=_write_headers(headers, "project-create"),
            json={"name": "Different", "idempotency_key": "project-create"},
        )

    assert missing.status_code == 409
    assert conflict.status_code == 409
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert changed.status_code == 409


@pytest.mark.anyio
async def test_v2_compatibility_routes_fail_closed_when_cutover_readiness_is_lost(
    state_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _v2_app(state_root, tmp_path)
    headers = _headers(app, "readiness-owner", "readiness-owner", "member")
    monkeypatch.setattr(app.state.domain_service, "v2_ready", lambda: False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/projects", headers=headers)

    assert response.status_code == 503


@pytest.mark.anyio
async def test_v2_member_capabilities_and_owner_transfer_are_available_over_http(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner: dict[str, object] = {"id": "member-owner", "role": "member"}
    owner_headers = _headers(app, "member-owner", "member-owner", "member")
    editor_headers = _headers(app, "member-editor", "member-editor", "member")
    new_owner_headers = _headers(app, "member-new-owner", "member-new-owner", "member")
    project = app.state.domain_service.create_project(owner, name="Transferable project")
    project_id = str(project["project_id"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        upsert = await client.put(
            f"/projects/{project_id}/members/member-editor",
            headers=_write_headers(owner_headers, "member-upsert"),
            json={"role": "editor", "can_publish": True},
        )
        members = await client.get(f"/projects/{project_id}/members", headers=owner_headers)
        transfer = await client.post(
            f"/projects/{project_id}/owner-transfer",
            headers=_write_headers(owner_headers, "owner-transfer"),
            json={"new_owner_user_id": "member-new-owner"},
        )
        default_project = app.state.domain_service.create_project(
            owner, name="Protected default", is_default=True
        )
        default_transfer = await client.post(
            f"/projects/{default_project['project_id']}/owner-transfer",
            headers=_write_headers(owner_headers, "default-owner-transfer"),
            json={"new_owner_user_id": "member-new-owner"},
        )
        editor_members = await client.get(f"/projects/{project_id}/members", headers=editor_headers)
        new_owner_members = await client.get(
            f"/projects/{project_id}/members", headers=new_owner_headers
        )

    assert upsert.status_code == 200
    assert upsert.json()["can_publish"] is True
    assert members.status_code == 200
    assert members.json()["items"] == [upsert.json()]
    assert transfer.status_code == 200
    assert transfer.json()["owner_user_id"] == "member-new-owner"
    assert default_transfer.status_code == 409
    assert editor_members.status_code == 200
    assert new_owner_members.status_code == 200


@pytest.mark.anyio
async def test_v2_detection_persists_observation_without_mutating_environment(
    state_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _v2_app(state_root, tmp_path)
    admin_headers = _headers(app, "observation-admin", "admin", "admin")
    environment = app.state.domain_service.create_environment(
        {"id": "admin", "role": "admin"},
        alias="observation-host",
        display_name="Observation host",
        connection={"host": "observation.example", "default_workdir": "/workspace"},
    )
    environment_id = str(environment["environment_id"])
    original_connection = str(environment["connection_json"])

    async def fake_probe(environment_entry: EnvironmentRegistryEntry) -> EnvironmentProbeOutcome:
        return EnvironmentProbeOutcome(
            snapshot=DetectionSnapshot(
                environment_id=environment_entry.id,
                detected_at=utc_now(),
                status=DetectionStatus.SUCCESS,
                summary="persistent observation",
                ssh_ok=True,
            )
        )

    monkeypatch.setattr("ainrf.domain.environment_observations.probe_with_ssh", fake_probe)
    assert isinstance(app.state.environment_service, PersistentEnvironmentFacade)
    assert isinstance(app.state.resource_monitor_service, ResourceMonitorService)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        detected = await client.post(
            f"/environments/{environment_id}/detect", headers=admin_headers
        )
        read_back = await client.get(f"/environments/{environment_id}", headers=admin_headers)

    assert detected.status_code == 200
    assert detected.json()["latest_detection"]["status"] == "success"
    assert read_back.status_code == 200
    assert read_back.json()["latest_detection"]["summary"] == "persistent observation"
    assert (state_root / "detections" / f"{environment_id}.json").is_file()
    current = app.state.domain_service.environment(environment_id, {"id": "admin", "role": "admin"})
    assert current["connection_json"] == original_connection

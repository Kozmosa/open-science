"""Mode- and fuse-gated v2 domain adapter tests."""

from __future__ import annotations

import httpx
import pytest
from pathlib import Path

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.domain_control import DomainCutoverError, DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]


@pytest.mark.anyio
async def test_domain_adapter_requires_v2_mode_and_cutover_fuse(
    state_root: Path, tmp_path: Path
) -> None:
    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("domain-key")}),
        state_root=state_root,
        domain_model_mode=DomainModelMode.V2,
        domain_artifact_sha=V2_ARTIFACT_SHA,
    )
    with pytest.raises(DomainCutoverError, match="fuse is not committed and ready"):
        create_app(config)

    prepare_committed_v2_cutover(state_root, tmp_path)
    app = create_app(config)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/domain/projects?api_key=domain-key",
            headers={"Idempotency-Key": "v2-project-create"},
            json={"name": "V2"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "V2"
    assert app.state.domain_cutover_controller.status().first_v2_write_actor_id == "api-key-user"


@pytest.mark.anyio
async def test_v2_task_adapter_uses_standard_task_create(state_root: Path, tmp_path: Path) -> None:
    prepare_committed_v2_cutover(state_root, tmp_path)
    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("domain-key")}),
        state_root=state_root,
        domain_model_mode=DomainModelMode.V2,
        domain_artifact_sha=V2_ARTIFACT_SHA,
    )
    app = create_app(config)
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    user: dict[str, object] = {"id": "api-key-user", "role": "user"}
    domain = app.state.domain_service
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="api-key-user",
        max_tasks=None,
        granted_by="admin",
        reason="v2 task adapter test",
    )
    project = domain.create_project(user, name="Project")
    workspace = domain.create_workspace(
        user,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/v2-task",
        label="Task",
    )
    domain.attach_workspace(
        str(project["project_id"]), str(workspace["workspace_id"]), user, idempotency_key="link"
    )
    context = app.state.project_context_service
    context.save_draft(str(project["project_id"]), "context", user)
    context.publish(str(project["project_id"]), user)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/tasks?api_key=domain-key",
            headers={"Idempotency-Key": "create"},
            json={
                "project_id": project["project_id"],
                "workspace_id": workspace["workspace_id"],
                "environment_id": environment["environment_id"],
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Prompt",
                "skills": [],
            },
        )

    assert response.status_code == 201
    assert response.json()["project_id"] == project["project_id"]

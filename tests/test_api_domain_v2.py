"""Mode- and fuse-gated v2 domain adapter tests."""

from __future__ import annotations

import httpx
import pytest
from pathlib import Path

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.db import connect
from ainrf.domain_control import DomainModelMode

pytestmark = [pytest.mark.api]


@pytest.mark.anyio
async def test_domain_adapter_requires_v2_mode_and_cutover_fuse(state_root: Path) -> None:
    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("domain-key")}),
        state_root=state_root,
        domain_model_mode=DomainModelMode.V2,
    )
    app = create_app(config)
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        conn.execute(
            "UPDATE domain_cutover_state SET constraints_ready = 1, cutover_ready = 1 WHERE singleton = 1"
        )
        conn.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/domain/projects?api_key=domain-key", json={"name": "V2"})

    assert response.status_code == 200
    assert response.json()["name"] == "V2"


@pytest.mark.anyio
async def test_v2_task_adapter_uses_standard_task_create(state_root: Path) -> None:
    config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("domain-key")}),
        state_root=state_root,
        domain_model_mode=DomainModelMode.V2,
    )
    app = create_app(config)
    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        conn.execute(
            "UPDATE domain_cutover_state SET constraints_ready = 1, cutover_ready = 1 WHERE singleton = 1"
        )
        conn.commit()
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    user: dict[str, object] = {"id": "api-key-user", "role": "user"}
    domain = app.state.domain_service
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
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
    from ainrf.domain import ProjectContextService

    context = ProjectContextService(state_root)
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

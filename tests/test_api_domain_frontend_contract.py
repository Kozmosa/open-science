"""Canonical Project and Workspace read contracts for the frontend phases."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.api.domain_schemas import DomainContextCandidateResponse
from ainrf.api.schemas import ForkConfirmResponse, ForkPreviewResponse, TaskSummaryResponse
from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import ConversationApplicationService, ProjectContextService
from tests.testutil import CURRENT_ARTIFACT_SHA, prepare_current_test_state


pytestmark = [pytest.mark.api]

_API_KEY = "frontend-contract-key"
_API_USER = {"id": "api-key-user", "role": "user"}
_ADMIN = {"id": "admin", "role": "admin"}


def test_task_summary_schema_exposes_conversation_status_union() -> None:
    schema = TaskSummaryResponse.model_json_schema()
    assert schema["$defs"]["ConversationTaskStatus"]["enum"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "completed",
    ]
    assert schema["$defs"]["AgenticResearcherType"]["enum"] == [
        "vanilla",
        "aris-researcher",
    ]
    assert schema["$defs"]["HarnessEngineType"]["enum"] == [
        "claude-code",
        "agent-sdk",
        "codex-app-server",
    ]
    assert schema["properties"]["researcher_type"] == {"$ref": "#/$defs/AgenticResearcherType"}
    assert schema["properties"]["harness_engine"] == {"$ref": "#/$defs/HarnessEngineType"}


def test_task_list_schema_exposes_sort_union(tmp_path: Path) -> None:
    app = _v2_app(tmp_path / "state", tmp_path)
    parameters = app.openapi()["paths"]["/api/tasks"]["get"]["parameters"]
    sort_parameter = next(parameter for parameter in parameters if parameter["name"] == "sort")
    sort_schema = sort_parameter["schema"]
    assert sort_schema["enum"] == ["updated", "created", "name", "status"]


def test_domain_frontend_routes_expose_named_response_models(tmp_path: Path) -> None:
    app = _v2_app(tmp_path / "state", tmp_path)
    paths = app.openapi()["paths"]
    expected = {
        ("/api/domain/capabilities", "get", "200"): "DomainCapabilitiesResponse",
        ("/api/domain/projects", "post", "200"): "DomainProjectCreateResponse",
        ("/api/domain/workspaces", "post", "200"): "DomainWorkspaceCreateResponse",
        (
            "/api/domain/projects/{project_id}/context",
            "get",
            "200",
        ): "DomainProjectContextResponse",
        (
            "/api/domain/projects/{project_id}/context/draft",
            "put",
            "200",
        ): "DomainContextDraftMutationResponse",
        (
            "/api/domain/projects/{project_id}/context/candidates/{candidate_id}/accept",
            "post",
            "200",
        ): "DomainContextCandidateAcceptResponse",
        ("/api/domain/overview/today", "get", "200"): "DomainOverviewSnapshotResponse",
        (
            "/api/domain/overview/today/refresh",
            "post",
            "202",
        ): "DomainOverviewRefreshJobResponse",
    }
    for (path, method, status_code), model_name in expected.items():
        schema = paths[path][method]["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert schema == {"$ref": f"#/components/schemas/{model_name}"}

    candidate_schema = DomainContextCandidateResponse.model_json_schema()
    assert candidate_schema["properties"]["status"]["enum"] == [
        "proposed",
        "accepted",
        "rejected",
    ]


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_current_test_state(state_root)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_artifact_sha=CURRENT_ARTIFACT_SHA,
        )
    )


def _seed_frontend_contract(app: FastAPI, state_root: Path) -> dict[str, str]:
    domain = app.state.project_module
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
    ConversationApplicationService(state_root, artifact_sha=CURRENT_ARTIFACT_SHA).create_task(
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
async def test_task_list_name_sort_is_authoritative_and_invalid_values_fail_closed(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)
    conversation = ConversationApplicationService(
        state_root,
        artifact_sha=CURRENT_ARTIFACT_SHA,
    )
    for title, key in (("Zulu task", "task-sort-zulu"), ("alpha task", "task-sort-alpha")):
        conversation.create_task(
            _API_USER,
            project_id=ids["project_id"],
            workspace_id=ids["workspace_id"],
            title=title,
            prompt=title,
            researcher_type="vanilla",
            harness_engine="claude-code",
            idempotency_key=key,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        by_name = await client.get(
            "/api/tasks?sort=name",
            headers={"X-API-Key": _API_KEY},
        )
        invalid = await client.get(
            "/api/tasks?sort=unexpected",
            headers={"X-API-Key": _API_KEY},
        )

    assert by_name.status_code == 200
    assert [item["title"] for item in by_name.json()["items"]] == [
        "alpha task",
        "Queued frontend task",
        "Zulu task",
    ]
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_frontend_project_contract_exposes_role_activity_and_attention(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/domain/projects", headers={"X-API-Key": _API_KEY})
        detail = await client.get(
            f"/api/domain/projects/{ids['project_id']}", headers={"X-API-Key": _API_KEY}
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
        response = await client.get("/api/domain/workspaces", headers={"X-API-Key": _API_KEY})
        detail = await client.get(
            f"/api/domain/workspaces/{ids['workspace_id']}", headers={"X-API-Key": _API_KEY}
        )
        missing = await client.get(
            "/api/domain/workspaces/not-visible", headers={"X-API-Key": _API_KEY}
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


@pytest.mark.anyio
async def test_task_work_lifecycle_returns_explicit_projection_and_requires_idempotency(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)
    headers = {"X-API-Key": _API_KEY}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get("/api/tasks", headers=headers)
        task = next(
            item for item in listed.json()["items"] if item["project_id"] == ids["project_id"]
        )
        task_id = str(task["task_id"])
        missing_key = await client.post(f"/api/tasks/{task_id}/complete", headers=headers)
        completed = await client.post(
            f"/api/tasks/{task_id}/complete",
            headers={**headers, "Idempotency-Key": "api-complete"},
        )
        replay = await client.post(
            f"/api/tasks/{task_id}/complete",
            headers={**headers, "Idempotency-Key": "api-complete"},
        )
        no_op = await client.post(
            f"/api/tasks/{task_id}/complete",
            headers={**headers, "Idempotency-Key": "api-complete-noop"},
        )
        reopened = await client.post(
            f"/api/tasks/{task_id}/reopen",
            headers={**headers, "Idempotency-Key": "api-reopen"},
        )

    assert listed.status_code == 200
    assert task["work_status"] == "open"
    assert missing_key.status_code == 409
    assert completed.status_code == 200
    assert completed.json()["work_status"] == "completed"
    assert completed.json()["updated_at"] != task["updated_at"]
    assert replay.status_code == 200
    assert replay.json() == completed.json()
    assert no_op.status_code == 409
    assert no_op.json()["detail"]["code"] == "invalid_state_transition"
    assert reopened.status_code == 200
    assert reopened.json()["work_status"] == "open"
    assert reopened.json()["updated_at"] != completed.json()["updated_at"]


@pytest.mark.anyio
async def test_task_surfaces_use_conversation_status_without_legacy_shadow(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)
    headers = {"X-API-Key": _API_KEY}
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        task = conn.execute(
            "SELECT task_id FROM tasks WHERE project_id = ?",
            (ids["project_id"],),
        ).fetchone()
        assert task is not None
        task_id = str(task["task_id"])
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "status" not in columns

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get("/api/tasks?sort=status", headers=headers)
        detail = await client.get(f"/api/tasks/{task_id}", headers=headers)
        health = await client.get(f"/api/tasks/{task_id}/health", headers=headers)
        projects = await client.get("/api/domain/projects", headers=headers)
        workspaces = await client.get("/api/domain/workspaces", headers=headers)
        cancelled = await client.post(
            f"/api/tasks/{task_id}/cancel",
            headers={**headers, "Idempotency-Key": "cancel-shadow-status"},
        )
        cancelled_detail = await client.get(f"/api/tasks/{task_id}", headers=headers)

    listed_task = next(item for item in listed.json()["items"] if item["task_id"] == task_id)
    project = next(
        item for item in projects.json()["items"] if item["project_id"] == ids["project_id"]
    )
    workspace = next(
        item for item in workspaces.json()["items"] if item["workspace_id"] == ids["workspace_id"]
    )
    assert listed_task["status"] == "queued"
    assert detail.json()["status"] == "queued"
    assert health.json()["status"] == "queued"
    assert project["active_task_count"] == 1
    assert workspace["active_task_count"] == 1
    assert cancelled.status_code == 204
    assert cancelled_detail.json()["status"] == "cancelled"


@pytest.mark.anyio
async def test_task_mutation_responses_use_strict_projection_for_create_and_fork(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)
    headers = {"X-API-Key": _API_KEY}

    def fail_on_aggregate_read(*_args: object, **_kwargs: object) -> dict[str, object]:
        pytest.fail("Task mutation transport must use the canonical Task projection")

    monkeypatch.setattr(
        app.state.conversation_application_service,
        "read_task",
        fail_on_aggregate_read,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get("/api/tasks", headers=headers)
        source_task_id = str(listed.json()["items"][0]["task_id"])
        created = await client.post(
            "/api/tasks",
            headers={**headers, "Idempotency-Key": "strict-create-task"},
            json={
                "project_id": ids["project_id"],
                "workspace_id": ids["workspace_id"],
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Strict create response",
                "skills": [],
                "mcp_servers": [],
            },
        )
        forked = await client.post(
            f"/api/tasks/{source_task_id}/fork",
            headers={**headers, "Idempotency-Key": "strict-fork-task"},
            json={
                "workspace_id": ids["workspace_id"],
                "project_id": ids["project_id"],
                "title": "Strict fork response",
                "prompt": "Strict fork response",
            },
        )

    assert created.status_code == 202
    assert forked.status_code == 202
    for response in (created, forked):
        payload = response.json()
        assert set(payload) == {"task", "submission"}
        task = payload["task"]
        validated = TaskSummaryResponse.model_validate(task)
        assert validated.task_id == task["task_id"]
        assert set(task) == set(TaskSummaryResponse.model_fields)
        assert {
            "conversation_revision",
            "runtime_status",
            "active_turn_id",
            "turn_count",
            "item_count",
            "binding",
        }.isdisjoint(task)


@pytest.mark.anyio
async def test_task_fork_preview_is_read_only_and_confirm_returns_canonical_target(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    ids = _seed_frontend_contract(app, state_root)
    headers = {"X-API-Key": _API_KEY}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed_before = await client.get("/api/tasks", headers=headers)
        source = next(
            item
            for item in listed_before.json()["items"]
            if item["project_id"] == ids["project_id"]
        )
        source_task_id = str(source["task_id"])
        preview_response = await client.post(
            f"/api/tasks/{source_task_id}/fork-preview",
            headers={**headers, "Idempotency-Key": "fork-preview-contract"},
            json={
                "target_engine_family": "codex",
                "target_harness_engine": "codex-app-server",
                "target_project_id": ids["project_id"],
                "target_workspace_id": ids["workspace_id"],
                "target_title": "Cross-engine contract fork",
                "transfer_mode": "context_only",
                "transfer_range": {},
                "metrics": {},
                "disclosure": {"caller": "frontend-contract"},
            },
        )
        listed_after_preview = await client.get("/api/tasks", headers=headers)
        preview = ForkPreviewResponse.model_validate(preview_response.json())
        confirm_response = await client.post(
            f"/api/tasks/{source_task_id}/fork-preview/{preview.preview_id}/confirm",
            headers={**headers, "Idempotency-Key": "fork-confirm-contract"},
            json={
                "preview_hash": preview.preview_hash,
                "source_revision": preview.source_revision,
                "transfer_mode": preview.transfer_mode,
                "truncation_acknowledged": False,
                "full_transcript_confirmed": False,
            },
        )
        confirmed = ForkConfirmResponse.model_validate(confirm_response.json())
        target = await client.get(f"/api/tasks/{confirmed.target_task_id}", headers=headers)
        listed_after_confirm = await client.get("/api/tasks", headers=headers)
        relationships = await client.get(
            f"/api/domain/projects/{ids['project_id']}/task-relationships",
            headers=headers,
        )

    assert listed_before.status_code == 200
    assert preview_response.status_code == 200
    assert listed_after_preview.status_code == 200
    assert len(listed_after_preview.json()["items"]) == len(listed_before.json()["items"])
    assert preview.source_task_id == source_task_id
    assert preview.source_engine_family == "claude"
    assert preview.target_engine_family == "codex"
    assert preview.target_harness_engine == "codex-app-server"
    assert preview.transfer_mode == "context_only"
    assert confirm_response.status_code == 200
    assert confirmed.status == "transferred"
    assert target.status_code == 200
    target_projection = TaskSummaryResponse.model_validate(target.json())
    assert target_projection.task_id == confirmed.target_task_id
    assert target_projection.harness_engine == "codex-app-server"
    assert target_projection.title == "Cross-engine contract fork"
    assert listed_after_confirm.status_code == 200
    assert len(listed_after_confirm.json()["items"]) == len(listed_before.json()["items"]) + 1
    assert relationships.status_code == 200
    assert any(
        {
            "source_task_id": confirmed.target_task_id,
            "target_task_id": source_task_id,
            "relationship_type": "derived_from",
        }.items()
        <= item.items()
        for item in relationships.json()["items"]
    )

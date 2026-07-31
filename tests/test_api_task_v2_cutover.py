"""Canonical Task route and retired compatibility contract tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain.attempts import AttemptWorkerModule as AttemptService
from ainrf.domain.worker import TaskDispatcher
from ainrf.domain_control import DomainMaintenanceService
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]

_API_KEY = "task-v2-key"
_OWNER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "task-v2-admin", "role": "admin"}


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key(_API_KEY)}),
            state_root=state_root,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )
    return app


def _prepare_task_scope(app: FastAPI, state_root: Path) -> tuple[str, str, str]:
    domain = app.state.project_module
    environment = domain.create_environment(
        _ADMIN,
        alias="task-v2-host",
        display_name="Task V2 Host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="task-v2-admin",
        reason="Task v2 adapter test",
    )
    project = domain.create_project(_OWNER, name="Task V2 Project")
    project_id = str(project["project_id"])
    workspace = domain.create_workspace(
        _OWNER,
        environment_id=environment_id,
        canonical_path=str(state_root / "task-v2-workspace"),
        label="Task V2 Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(project_id, workspace_id, _OWNER, idempotency_key="task-v2-link")
    context = app.state.project_context_service
    context.save_draft(project_id, "Task v2 context", _OWNER)
    context.publish(project_id, _OWNER, idempotency_key="task-v2-context")
    return project_id, workspace_id, environment_id


def _body(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _string_list(value: object) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return cast(list[str], value)


@pytest.mark.anyio
async def test_task_module_fuse_failure_never_falls_back_to_a_legacy_writer(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _v2_app(state_root, tmp_path)
    task_module = app.state.task_application_service
    monkeypatch.setattr(task_module, "v2_ready", lambda: False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        tasks = await client.get(f"/api/tasks?api_key={_API_KEY}")
        sessions = await client.get(f"/api/sessions?api_key={_API_KEY}")

    assert tasks.status_code == 503
    assert sessions.status_code == 404
    assert _body(tasks)["detail"] == "Task domain v2 is not ready"


@pytest.mark.anyio
async def test_retired_task_and_session_contracts_are_unroutable(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    retired = [
        ("GET", "/api/sessions"),
        ("GET", "/api/sessions/session-id"),
        ("GET", "/api/sessions/session-id/attempts"),
        ("GET", "/api/projects/project-id/tasks"),
        ("GET", "/api/projects/project-id/task-edges"),
        ("POST", "/api/projects/project-id/task-edges"),
        ("DELETE", "/api/task-edges/edge-id"),
        ("GET", "/api/projects/project-id/cost-summary"),
        ("PATCH", "/api/tasks/task-id/project"),
        ("DELETE", "/api/tasks/task-id/permanent"),
    ]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for method, path in retired:
            response = await client.request(method, f"{path}?api_key={_API_KEY}")
            assert response.status_code == 404, (method, path, response.text)


@pytest.mark.anyio
async def test_v2_task_routes_return_task_attempt_dispatch_and_retry_same_task(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, _ = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Inspect the durable Task contract",
                "skills": [],
            },
        )
        assert created.status_code == 201
        assert "deprecation" not in created.headers
        created_payload = _body(created)
        task = cast(dict[str, object], created_payload["task"])
        attempt = cast(dict[str, object], created_payload["attempt"])
        dispatch = cast(dict[str, object], created_payload["dispatch"])
        task_id = str(task["task_id"])
        assert task["archived_at"] is None
        assert task["archive_reason"] is None
        assert isinstance(task["project_context_version_id"], str)
        assert attempt["task_id"] == task_id
        assert attempt["context_version_id"] == task["project_context_version_id"]
        assert dispatch["attempt_id"] == attempt["attempt_id"]
        assert dispatch["status"] == "pending"

        # In v2 the health endpoint is a durable Attempt/RuntimeSession read;
        # it must not require the legacy in-process task/engine service.
        app.state.agentic_researcher_service = None
        health = await client.get(f"/api/tasks/{task_id}/health?api_key={_API_KEY}")
        assert health.status_code == 200
        health_payload = _body(health)
        assert health_payload == {
            "task_id": task_id,
            "status": "queued",
            "engine_alive": False,
            "last_event_at": None,
            "inactive_seconds": None,
        }

        attempts = await client.get(f"/api/tasks/{task_id}/attempts?api_key={_API_KEY}")
        assert attempts.status_code == 200
        attempt_items = cast(list[dict[str, object]], _body(attempts)["items"])
        assert [item["attempt_id"] for item in attempt_items] == [attempt["attempt_id"]]
        assert attempt_items[0]["context_version_id"] == task["project_context_version_id"]
        assert (
            cast(dict[str, object], attempt_items[0]["dispatch"])["dispatch_id"]
            == dispatch["dispatch_id"]
        )

        retried = await client.post(
            f"/api/tasks/{task_id}/retry?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-retry"},
        )
        assert retried.status_code == 201
        assert "deprecation" not in retried.headers
        retried_payload = _body(retried)
        assert cast(dict[str, object], retried_payload["task"])["task_id"] == task_id
        retried_attempt = cast(dict[str, object], retried_payload["attempt"])
        assert retried_attempt["attempt_seq"] == 2
        assert retried_attempt["context_version_id"] == task["project_context_version_id"]
        assert (
            cast(dict[str, object], retried_payload["dispatch"])["attempt_id"]
            == retried_attempt["attempt_id"]
        )

        forked = await client.post(
            f"/api/tasks/{task_id}/fork?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-fork"},
            json={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "prompt": "Fork the durable Task contract",
            },
        )
        assert forked.status_code == 201
        assert "deprecation" not in forked.headers
        assert "sunset" not in forked.headers
        assert "link" not in forked.headers
        forked_task_id = str(_mapping(_body(forked)["task"])["task_id"])
        assert forked_task_id != task_id

        relationships = await client.get(
            f"/api/domain/projects/{project_id}/task-relationships?api_key={_API_KEY}"
        )
        assert relationships.status_code == 200
        relationship_items = cast(list[dict[str, object]], _body(relationships)["items"])
        assert all(
            "relationship_id" in item and "edge_id" not in item for item in relationship_items
        )
        assert any(
            item["source_task_id"] == forked_task_id
            and item["target_task_id"] == task_id
            and item["relationship_type"] == "derived_from"
            for item in relationship_items
        )

        related = await client.post(
            f"/api/domain/projects/{project_id}/task-relationships?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-related"},
            json={"source_task_id": task_id, "target_task_id": forked_task_id},
        )
        assert related.status_code == 201
        related_payload = _body(related)
        relationship_id = str(related_payload["relationship_id"])
        assert "edge_id" not in related_payload

        usage = await client.get(
            f"/api/domain/projects/{project_id}/usage-summary?api_key={_API_KEY}"
        )
        assert usage.status_code == 200
        usage_payload = _body(usage)
        assert usage_payload["project_id"] == project_id
        assert usage_payload["task_count"] == 2
        assert usage_payload["attempt_count"] == 3
        assert usage_payload["total_duration_ms"] == 0
        assert "session_count" not in usage_payload

        deleted_relationship = await client.delete(
            f"/api/domain/projects/{project_id}/task-relationships/{relationship_id}"
            f"?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-related-delete"},
        )
        assert deleted_relationship.status_code == 204

        archived = await client.post(
            f"/api/tasks/{forked_task_id}/archive?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-archive-fork"},
        )
        assert archived.status_code == 200
        archived_task = _body(archived)
        assert isinstance(archived_task["archived_at"], str)
        assert archived_task["archive_reason"] == "user_archived"


@pytest.mark.anyio
async def test_task_create_and_retry_reject_legacy_request_shapes(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)
    payload = {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "researcher_type": "vanilla",
        "harness_engine": "claude-code",
        "prompt": "Reject compatibility input",
        "skills": [],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        empty_project = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-empty-project"},
            json={**payload, "project_id": ""},
        )
        environment_alias = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-environment-alias"},
            json={**payload, "environment_id": environment_id},
        )
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-canonical-create"},
            json=payload,
        )
        task_id = str(_mapping(_body(created)["task"])["task_id"])
        retry_body = await client.post(
            f"/api/tasks/{task_id}/retry?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-retry-body"},
            json={},
        )

    assert empty_project.status_code == 422
    assert environment_alias.status_code == 422
    assert created.status_code == 201
    assert retry_body.status_code == 422


@pytest.mark.anyio
async def test_v2_running_task_archive_returns_pending_until_runtime_confirms_stop(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, _ = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "archive-pending-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Keep running until archive cancellation is confirmed",
                "skills": [],
            },
        )
        assert created.status_code == 201
        created_payload = _body(created)
        task_id = str(cast(dict[str, object], created_payload["task"])["task_id"])
        attempt_id = str(cast(dict[str, object], created_payload["attempt"])["attempt_id"])
        dispatch_id = str(cast(dict[str, object], created_payload["dispatch"])["dispatch_id"])

        with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
            conn.execute(
                "UPDATE agent_task_attempts SET status = 'running' WHERE attempt_id = ?",
                (attempt_id,),
            )
            conn.execute(
                "UPDATE tasks SET status = 'running' WHERE task_id = ?",
                (task_id,),
            )
            conn.execute(
                """UPDATE task_dispatch_outbox
                   SET status = 'dispatched', launch_state = 'launched',
                       claim_token = 'archive-pending-token', dispatcher_id = 'archive-test',
                       claim_expires_at = '2099-01-01T00:00:00+00:00',
                       runtime_launch_key = 'archive-pending-launch'
                   WHERE dispatch_id = ?""",
                (dispatch_id,),
            )
            conn.commit()

        archived = await client.post(
            f"/api/tasks/{task_id}/archive?api_key={_API_KEY}",
            headers={"Idempotency-Key": "archive-pending-request"},
        )

    assert archived.status_code == 202
    assert archived.headers["x-openscience-archive-state"] == "pending"
    assert _body(archived)["status"] == "running"
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        task = conn.execute(
            "SELECT archived_at FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        control = conn.execute(
            """SELECT status, payload_json FROM task_attempt_control_requests
               WHERE attempt_id = ?""",
            (attempt_id,),
        ).fetchone()
    assert task is not None
    assert task["archived_at"] is None
    assert control is not None
    assert (control["status"], control["payload_json"]) == ("requested", '{"archive":true}')


@pytest.mark.anyio
async def test_v2_launch_unknown_resolution_is_terminal_and_idempotent(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, _ = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "launch-unknown-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Resolve an unknown runtime without a blind relaunch",
                "skills": [],
            },
        )
        assert created.status_code == 201
        created_payload = _body(created)
        task_id = str(cast(dict[str, object], created_payload["task"])["task_id"])
        attempt_id = str(cast(dict[str, object], created_payload["attempt"])["attempt_id"])

        attempts = AttemptService(state_root, artifact_sha=V2_ARTIFACT_SHA)
        claim = attempts.claim_next("unknown-api-worker", lease_seconds=120)
        assert claim is not None
        preparation = attempts.prepare_runtime_launch(claim)
        assert attempts.commit_runtime_launch(claim, preparation.runtime_session_id)
        attempts.mark_launch_unknown(claim, reason="fixture runtime probe inconclusive")

        endpoint = (
            f"/api/tasks/{task_id}/attempts/{attempt_id}/resolve-launch-unknown?api_key={_API_KEY}"
        )
        resolved = await client.post(
            endpoint,
            headers={"Idempotency-Key": "launch-unknown-resolve"},
            json={"reason": "operator verified the runtime is absent"},
        )
        assert resolved.status_code == 200
        resolved_payload = _body(resolved)
        assert resolved_payload["status"] == "stopped_runtime_unknown"

        replayed = await client.post(
            endpoint,
            headers={"Idempotency-Key": "launch-unknown-resolve"},
            json={"reason": "operator verified the runtime is absent"},
        )
        assert replayed.status_code == 200
        assert _body(replayed) == resolved_payload

        conflict = await client.post(
            endpoint,
            headers={"Idempotency-Key": "launch-unknown-resolve"},
            json={"reason": "a changed runtime conclusion"},
        )
        assert conflict.status_code == 409

    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        dispatch = conn.execute(
            "SELECT status, launch_state FROM task_dispatch_outbox WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    assert dispatch is not None
    assert (dispatch["status"], dispatch["launch_state"]) == ("cancelled", "unknown")


@pytest.mark.anyio
async def test_v2_task_capabilities_and_idempotency_contract(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, _ = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unavailable = await client.get(f"/api/domain/capabilities?api_key={_API_KEY}")
        assert unavailable.status_code == 200
        unavailable_payload = _body(unavailable)
        assert unavailable_payload["standard_task_create"] is False
        assert unavailable_payload["task_attempts"] is False
        assert unavailable_payload["literature_research_task"] is False
        dispatcher_payload = _mapping(unavailable_payload["task_dispatcher"])
        assert dispatcher_payload["ready"] is False
        assert unavailable_payload["overview_snapshot"] is False

        dispatcher = TaskDispatcher(
            state_root,
            dispatcher_id="task-capability-dispatcher",
            artifact_sha=V2_ARTIFACT_SHA,
        )
        maintenance = DomainMaintenanceService(state_root)
        try:
            dispatcher.start()
            available = await client.get(f"/api/domain/capabilities?api_key={_API_KEY}")
            assert available.status_code == 200
            available_payload = _body(available)
            assert available_payload["standard_task_create"] is True
            assert available_payload["task_attempts"] is True
            assert available_payload["literature_research_task"] is True
            active_dispatcher = _mapping(available_payload["task_dispatcher"])
            assert active_dispatcher["ready"] is True

            with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
                conn.execute(
                    "UPDATE domain_write_participants SET heartbeat_at = ? WHERE participant_id = ?",
                    ("2000-01-01T00:00:00+00:00", dispatcher.dispatcher_id),
                )
                conn.commit()
            stale = await client.get(f"/api/domain/capabilities?api_key={_API_KEY}")
            stale_payload = _body(stale)
            assert stale_payload["task_attempts"] is False
            stale_dispatcher = _mapping(stale_payload["task_dispatcher"])
            assert dispatcher.dispatcher_id in _string_list(
                stale_dispatcher["stale_participant_ids"]
            )

            maintenance.register_participant(dispatcher.dispatcher_id, "task-dispatcher")
            maintenance.enter(actor_id="task-capability-operator", reason="test maintenance")
            maintenance_blocked = await client.get(f"/api/domain/capabilities?api_key={_API_KEY}")
            maintenance_payload = _body(maintenance_blocked)
            assert maintenance_payload["standard_task_create"] is False
            maintenance_dispatcher = _mapping(maintenance_payload["task_dispatcher"])
            assert maintenance_dispatcher["maintenance_active"] is True
            assert maintenance_dispatcher["ready"] is False

            maintenance.drain_participant(dispatcher.dispatcher_id)
            drained = await client.get(f"/api/domain/capabilities?api_key={_API_KEY}")
            drained_dispatcher = _mapping(_body(drained)["task_dispatcher"])
            assert drained_dispatcher["ready"] is False
            assert drained_dispatcher["active_participant_ids"] == []
            maintenance.exit(actor_id="task-capability-operator")
        finally:
            dispatcher.stop()

        mismatch = await client.post(
            f"/api/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "header-key"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Reject conflicting idempotency transport",
                "skills": [],
                "idempotency_key": "body-key",
            },
        )
        assert mismatch.status_code == 422

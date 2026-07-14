"""B7 v2 Task route, Attempt projection, and compatibility contracts."""

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
from ainrf.domain import AttemptService
from ainrf.domain.worker import TaskDispatcher
from ainrf.domain_control import DomainMaintenanceService, DomainModelMode
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
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )
    return app


def _prepare_task_scope(app: FastAPI, state_root: Path) -> tuple[str, str, str]:
    domain = app.state.domain_service
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
async def test_v2_fuse_failure_never_falls_back_to_an_uninitialized_legacy_service(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _v2_app(state_root, tmp_path)
    domain = app.state.domain_service
    monkeypatch.setattr(domain, "v2_ready", lambda: False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        tasks = await client.get(f"/tasks?api_key={_API_KEY}")
        sessions = await client.get(f"/sessions?api_key={_API_KEY}")

    assert tasks.status_code == 503
    assert sessions.status_code == 503
    assert _body(tasks)["detail"] == "Task domain v2 is not ready"
    assert _body(sessions)["detail"] == "Session domain v2 is not ready"


@pytest.mark.anyio
async def test_v2_task_routes_return_task_attempt_dispatch_and_retry_same_task(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Inspect the durable Task contract",
                "skills": [],
            },
        )
        assert created.status_code == 201
        assert created.headers["deprecation"] == "true"
        created_payload = _body(created)
        task = cast(dict[str, object], created_payload["task"])
        attempt = cast(dict[str, object], created_payload["attempt"])
        dispatch = cast(dict[str, object], created_payload["dispatch"])
        task_id = str(task["task_id"])
        assert created_payload["task_id"] == task_id
        assert attempt["task_id"] == task_id
        assert dispatch["attempt_id"] == attempt["attempt_id"]
        assert dispatch["status"] == "pending"

        # In v2 the health endpoint is a durable Attempt/RuntimeSession read;
        # it must not require the legacy in-process task/engine service.
        app.state.agentic_researcher_service = None
        health = await client.get(f"/tasks/{task_id}/health?api_key={_API_KEY}")
        assert health.status_code == 200
        health_payload = _body(health)
        assert health_payload == {
            "task_id": task_id,
            "status": "queued",
            "engine_alive": False,
            "last_event_at": None,
            "inactive_seconds": None,
        }

        attempts = await client.get(f"/tasks/{task_id}/attempts?api_key={_API_KEY}")
        assert attempts.status_code == 200
        attempt_items = cast(list[dict[str, object]], _body(attempts)["items"])
        assert [item["attempt_id"] for item in attempt_items] == [attempt["attempt_id"]]
        assert (
            cast(dict[str, object], attempt_items[0]["dispatch"])["dispatch_id"]
            == dispatch["dispatch_id"]
        )

        retried = await client.post(
            f"/tasks/{task_id}/retry?api_key={_API_KEY}",
            headers={"Idempotency-Key": "task-v2-retry"},
            json={},
        )
        assert retried.status_code == 201
        assert retried.headers["deprecation"] == "true"
        retried_payload = _body(retried)
        assert cast(dict[str, object], retried_payload["new_task"])["task_id"] == task_id
        assert cast(dict[str, object], retried_payload["task"])["task_id"] == task_id
        retried_attempt = cast(dict[str, object], retried_payload["attempt"])
        assert retried_attempt["attempt_seq"] == 2
        assert (
            cast(dict[str, object], retried_payload["dispatch"])["attempt_id"]
            == retried_attempt["attempt_id"]
        )


@pytest.mark.anyio
async def test_v2_running_task_archive_returns_pending_until_runtime_confirms_stop(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "archive-pending-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
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
            f"/tasks/{task_id}/archive?api_key={_API_KEY}",
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
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "launch-unknown-create"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
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
            f"/tasks/{task_id}/attempts/{attempt_id}/resolve-launch-unknown?api_key={_API_KEY}"
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
    project_id, workspace_id, environment_id = _prepare_task_scope(app, state_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unavailable = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
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
            available = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
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
            stale = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
            stale_payload = _body(stale)
            assert stale_payload["task_attempts"] is False
            stale_dispatcher = _mapping(stale_payload["task_dispatcher"])
            assert dispatcher.dispatcher_id in _string_list(
                stale_dispatcher["stale_participant_ids"]
            )

            maintenance.register_participant(dispatcher.dispatcher_id, "task-dispatcher")
            maintenance.enter(actor_id="task-capability-operator", reason="test maintenance")
            maintenance_blocked = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
            maintenance_payload = _body(maintenance_blocked)
            assert maintenance_payload["standard_task_create"] is False
            maintenance_dispatcher = _mapping(maintenance_payload["task_dispatcher"])
            assert maintenance_dispatcher["maintenance_active"] is True
            assert maintenance_dispatcher["ready"] is False

            maintenance.drain_participant(dispatcher.dispatcher_id)
            drained = await client.get(f"/domain/capabilities?api_key={_API_KEY}")
            drained_dispatcher = _mapping(_body(drained)["task_dispatcher"])
            assert drained_dispatcher["ready"] is False
            assert drained_dispatcher["active_participant_ids"] == []
            maintenance.exit(actor_id="task-capability-operator")
        finally:
            dispatcher.stop()

        mismatch = await client.post(
            f"/tasks?api_key={_API_KEY}",
            headers={"Idempotency-Key": "header-key"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Reject conflicting idempotency transport",
                "skills": [],
                "idempotency_key": "body-key",
            },
        )
        assert mismatch.status_code == 409

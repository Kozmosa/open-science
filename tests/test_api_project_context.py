"""API-key contracts for the v2 Project Context workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover

pytestmark = [pytest.mark.api]

_API_KEY = "project-context-api-key"
_API_KEY_USER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "context-admin", "role": "admin"}
_OWNER: dict[str, object] = {"id": "context-owner", "role": "member"}


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


def _api_path(path: str, **params: str) -> str:
    return f"{path}?{urlencode({'api_key': _API_KEY, **params})}"


def _payload(response: httpx.Response) -> dict[str, object]:
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


def _nested(payload: dict[str, object], name: str) -> dict[str, object]:
    value = payload[name]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _prepare_attached_workspace(app: FastAPI, state_root: Path, project_id: str) -> tuple[str, str]:
    domain = app.state.domain_service
    environment = domain.create_environment(
        _ADMIN,
        alias="context-api-host",
        display_name="Context API Host",
        connection={},
    )
    environment_id = str(environment["environment_id"])
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by="context-admin",
        reason="Project Context API test",
    )
    workspace = domain.create_workspace(
        _API_KEY_USER,
        environment_id=environment_id,
        canonical_path=str(state_root / "context-api-workspace"),
        label="Context API Workspace",
    )
    workspace_id = str(workspace["workspace_id"])
    domain.attach_workspace(
        project_id,
        workspace_id,
        _API_KEY_USER,
        idempotency_key="context-api-workspace-link",
    )
    return workspace_id, environment_id


@pytest.mark.anyio
async def test_api_fresh_project_has_an_initial_context_and_can_create_a_task(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        project_response = await client.post(
            _api_path("/domain/projects"),
            headers={"Idempotency-Key": "initial-context-project"},
            json={"name": "Initial Context Project"},
        )
        assert project_response.status_code == 200
        project_id = str(_payload(project_response)["project_id"])

        context_response = await client.get(_api_path(f"/domain/projects/{project_id}/context"))
        assert context_response.status_code == 200
        initial_context = _payload(context_response)
        active_version = _nested(initial_context, "active_version")
        draft = _nested(initial_context, "draft")
        assert active_version["project_id"] == project_id
        assert active_version["content"] == ""
        assert active_version["is_active"] is True
        assert draft["content"] == ""
        # Version fingerprints include the frozen Fragment manifest, while a
        # Draft fingerprint intentionally represents only editable Brief text.
        assert active_version["fragment_manifest"] == []
        assert active_version["fragment_provenance_status"] == "verified"
        assert isinstance(draft["fingerprint"], str)

        workspace_id, environment_id = _prepare_attached_workspace(app, state_root, project_id)
        created = await client.post(
            _api_path("/tasks"),
            headers={"Idempotency-Key": "initial-context-task"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Run against the initial Context.",
                "skills": [],
            },
        )
        assert created.status_code == 201
        task_id = str(_payload(created)["task_id"])

        task_context = await client.get(_api_path(f"/domain/tasks/{task_id}/context"))
        assert task_context.status_code == 200
        assert _payload(task_context)["context_version_id"] == active_version["context_version_id"]


@pytest.mark.anyio
async def test_api_key_context_publish_candidate_and_task_confirmation(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        project_response = await client.post(
            _api_path("/domain/projects"),
            headers={"Idempotency-Key": "context-api-project"},
            json={"name": "Context API Project"},
        )
        assert project_response.status_code == 200
        project_id = str(_payload(project_response)["project_id"])

        draft_v1 = await client.put(
            _api_path(f"/domain/projects/{project_id}/context/draft"),
            headers={"Idempotency-Key": "draft-v1"},
            json={"content": "Brief v1"},
        )
        assert draft_v1.status_code == 200

        publish_headers = {"Idempotency-Key": "publish-v1"}
        published_v1 = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"), headers=publish_headers
        )
        assert published_v1.status_code == 200
        active_v1 = _payload(published_v1)
        active_v1_id = str(active_v1["context_version_id"])

        replay = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"), headers=publish_headers
        )
        assert replay.status_code == 200
        assert _payload(replay) == active_v1

        draft_v2 = await client.put(
            _api_path(f"/domain/projects/{project_id}/context/draft"),
            headers={"Idempotency-Key": "draft-v2"},
            json={"content": "Draft v2"},
        )
        assert draft_v2.status_code == 200
        stale_replay = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"), headers=publish_headers
        )
        assert stale_replay.status_code == 200
        assert _payload(stale_replay) == active_v1

        workspace_id, environment_id = _prepare_attached_workspace(app, state_root, project_id)
        task_response = await client.post(
            _api_path("/tasks"),
            headers={"Idempotency-Key": "context-api-task"},
            json={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "environment_id": environment_id,
                "researcher_type": "vanilla",
                "harness_engine": "claude-code",
                "prompt": "Investigate the result",
                "skills": [],
            },
        )
        assert task_response.status_code == 201
        task_id = str(_payload(task_response)["task_id"])

        with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
            conn.execute(
                """
                INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
                VALUES (?, 1, 'result', ?, ?)
                """,
                (task_id, "candidate source", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        created_candidate = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/candidates"),
            headers={"Idempotency-Key": "candidate-create"},
            json={
                "content": "Candidate finding",
                "source_metadata": {"kind": "manual"},
                "source_task_id": task_id,
                "source_output_start_seq": 1,
                "source_output_end_seq": 1,
            },
        )
        assert created_candidate.status_code == 200
        candidate = _payload(created_candidate)
        candidate_id = str(candidate["candidate_id"])
        assert candidate["status"] == "proposed"

        accepted = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/candidates/{candidate_id}/accept"),
            headers={"Idempotency-Key": "candidate-accept"},
        )
        assert accepted.status_code == 200
        accepted_payload = _payload(accepted)
        assert _nested(accepted_payload, "candidate")["status"] == "accepted"
        assert _nested(accepted_payload, "draft")["content"] == "Draft v2\n\nCandidate finding"

        context_after_accept = await client.get(_api_path(f"/domain/projects/{project_id}/context"))
        assert context_after_accept.status_code == 200
        context_payload = _payload(context_after_accept)
        assert _nested(context_payload, "active_version")["context_version_id"] == active_v1_id
        assert _nested(context_payload, "draft")["content"] == "Draft v2\n\nCandidate finding"

        published_v2 = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"),
            headers={"Idempotency-Key": "publish-v2"},
        )
        assert published_v2.status_code == 200
        active_v2_id = str(_payload(published_v2)["context_version_id"])
        assert active_v2_id != active_v1_id

        before_update = await client.get(_api_path(f"/domain/tasks/{task_id}/context"))
        assert before_update.status_code == 200
        current_snapshot = _payload(before_update)
        assert current_snapshot["context_version_id"] == active_v1_id
        original_snapshot_id = str(current_snapshot["context_snapshot_id"])

        preview = await client.post(
            _api_path(f"/domain/tasks/{task_id}/context/preview", project_id=project_id)
        )
        assert preview.status_code == 200
        preview_payload = _payload(preview)
        assert _nested(preview_payload, "current")["context_snapshot_id"] == original_snapshot_id
        assert _nested(preview_payload, "proposed")["context_version_id"] == active_v2_id
        assert isinstance(preview_payload["diff"], str)
        preview_id = str(preview_payload["preview_id"])

        confirm_headers = {"Idempotency-Key": "confirm-v2"}
        confirmed = await client.post(
            _api_path(f"/domain/tasks/{task_id}/context/confirm", project_id=project_id),
            headers=confirm_headers,
            json={"preview_id": preview_id},
        )
        assert confirmed.status_code == 200
        confirmed_payload = _payload(confirmed)
        assert confirmed_payload["context_version_id"] == active_v2_id
        assert confirmed_payload["context_snapshot_id"] != original_snapshot_id

        confirmed_replay = await client.post(
            _api_path(f"/domain/tasks/{task_id}/context/confirm", project_id=project_id),
            headers=confirm_headers,
            json={"preview_id": preview_id},
        )
        assert confirmed_replay.status_code == 200
        assert _payload(confirmed_replay) == confirmed_payload

        after_update = await client.get(_api_path(f"/domain/tasks/{task_id}/context"))
        assert after_update.status_code == 200
        assert (
            _payload(after_update)["context_snapshot_id"]
            == confirmed_payload["context_snapshot_id"]
        )


@pytest.mark.anyio
async def test_api_key_context_permissions_for_viewer_editor_and_publisher(
    state_root: Path, tmp_path: Path
) -> None:
    app = _v2_app(state_root, tmp_path)
    domain = app.state.domain_service
    context = app.state.project_context_service
    project = domain.create_project(_OWNER, name="Permission Project")
    project_id = str(project["project_id"])
    context.save_draft(project_id, "Owner brief", _OWNER)
    context.publish(project_id, _OWNER, idempotency_key="owner-publish")

    domain.add_member(project_id, "api-key-user", "viewer", False, _OWNER)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        viewer_context = await client.get(_api_path(f"/domain/projects/{project_id}/context"))
        assert viewer_context.status_code == 200
        assert _payload(viewer_context)["draft"] is None

        viewer_draft = await client.put(
            _api_path(f"/domain/projects/{project_id}/context/draft"),
            headers={"Idempotency-Key": "viewer-draft"},
            json={"content": "Viewer cannot write"},
        )
        assert viewer_draft.status_code == 403
        viewer_publish = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"),
            headers={"Idempotency-Key": "viewer-publish"},
        )
        assert viewer_publish.status_code == 403

        domain.add_member(project_id, "api-key-user", "editor", False, _OWNER)
        editor_draft = await client.put(
            _api_path(f"/domain/projects/{project_id}/context/draft"),
            headers={"Idempotency-Key": "editor-draft"},
            json={"content": "Editor draft"},
        )
        assert editor_draft.status_code == 200
        editor_publish = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"),
            headers={"Idempotency-Key": "editor-without-publish"},
        )
        assert editor_publish.status_code == 403

        domain.add_member(project_id, "api-key-user", "editor", True, _OWNER)
        publisher_publish = await client.post(
            _api_path(f"/domain/projects/{project_id}/context/publish"),
            headers={"Idempotency-Key": "editor-with-publish"},
        )
        assert publisher_publish.status_code == 200
        assert _payload(publisher_publish)["content"] == "Editor draft"

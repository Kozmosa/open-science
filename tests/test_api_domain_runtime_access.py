"""v2 authorization coverage for terminal and file runtime facades."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.domain_control import DomainModelMode
from tests.domain_cutover_fixtures import V2_ARTIFACT_SHA, prepare_committed_v2_cutover
from tests.testutil import seed_user

pytestmark = [pytest.mark.api]


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_committed_v2_cutover(state_root, tmp_path)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("runtime-access-key")}),
            state_root=state_root,
            domain_model_mode=DomainModelMode.V2,
            domain_artifact_sha=V2_ARTIFACT_SHA,
        )
    )


def _headers(app: FastAPI, username: str, user_id: str, role: str) -> dict[str, str]:
    auth = app.state.auth_service
    seed_user(auth, username, "runtime-access-password", role=role, user_id=user_id)
    token = auth.login(username=username, password="runtime-access-password")
    return {"Authorization": f"Bearer {token['access_token']}"}


def _environment_with_owner_grant(
    app: FastAPI,
    state_root: Path,
    owner_id: str,
) -> str:
    workdir = state_root / "runtime-environment"
    workdir.mkdir()
    (workdir / "visible.txt").write_text("visible")
    environment = app.state.domain_service.create_environment(
        {"id": "runtime-admin", "role": "admin"},
        alias="runtime-access-host",
        display_name="Runtime access host",
        connection={"host": "127.0.0.1", "default_workdir": str(workdir)},
    )
    environment_id = str(environment["environment_id"])
    app.state.auth_service.grant_environment(
        env_id=environment_id,
        user_id=owner_id,
        max_tasks=None,
        granted_by="runtime-admin",
        reason="runtime facade access test",
    )
    return environment_id


@pytest.mark.anyio
async def test_v2_runtime_facades_hide_ungranted_environments(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner_headers = _headers(app, "runtime-owner", "runtime-owner", "member")
    outsider_headers = _headers(app, "runtime-outsider", "runtime-outsider", "member")
    environment_id = _environment_with_owner_grant(app, state_root, "runtime-owner")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner_files = await client.get(
            f"/files/list?environment_id={environment_id}", headers=owner_headers
        )
        outsider_terminal = await client.get(
            f"/terminal/session?environment_id={environment_id}", headers=outsider_headers
        )
        outsider_session_pairs = await client.get(
            f"/terminal/session-pairs?environment_id={environment_id}", headers=outsider_headers
        )
        outsider_files = await client.get(
            f"/files/list?environment_id={environment_id}", headers=outsider_headers
        )

    assert owner_files.status_code == 200
    assert outsider_terminal.status_code == 404
    assert outsider_terminal.json() == {"detail": "Environment not found"}
    assert outsider_session_pairs.status_code == 404
    assert outsider_session_pairs.json() == {"detail": "Environment not found"}
    assert outsider_files.status_code == 404
    assert outsider_files.json() == {"detail": "Environment not found"}


@pytest.mark.anyio
async def test_v2_runtime_workspace_access_requires_the_linux_tenant_owner(
    state_root: Path,
    tmp_path: Path,
) -> None:
    app = _v2_app(state_root, tmp_path)
    _headers(app, "runtime-owner", "runtime-owner", "member")
    admin_headers = _headers(app, "runtime-admin", "runtime-admin", "admin")
    environment_id = _environment_with_owner_grant(app, state_root, "runtime-owner")
    workspace_path = state_root / "runtime-workspace"
    workspace_path.mkdir()
    workspace = app.state.domain_service.create_workspace(
        {"id": "runtime-owner", "role": "member"},
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Tenant-only workspace",
    )
    workspace_id = str(workspace["workspace_id"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        file_read = await client.get(
            f"/files/list?environment_id={environment_id}&workspace_id={workspace_id}",
            headers=admin_headers,
        )
        terminal_exec = await client.post(
            "/terminal/session/exec",
            headers=admin_headers,
            json={
                "environment_id": environment_id,
                "workspace_id": workspace_id,
                "command": ["pwd"],
            },
        )

    assert file_read.status_code == 403
    assert file_read.json() == {"detail": "Workspace owner permission is required"}
    assert terminal_exec.status_code == 403
    assert terminal_exec.json() == {"detail": "Workspace owner permission is required"}

"""v2 authorization coverage for terminal and file runtime facades."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
import structlog

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.api.routes.metrics import get_metrics_text, reset_metrics
from tests.testutil import CURRENT_ARTIFACT_SHA, prepare_current_test_state, seed_user

pytestmark = [pytest.mark.api]


def _v2_app(state_root: Path, tmp_path: Path) -> FastAPI:
    prepare_current_test_state(state_root)
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("runtime-access-key")}),
            state_root=state_root,
            domain_artifact_sha=CURRENT_ARTIFACT_SHA,
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
    environment = app.state.environment_module.create_environment(
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
            f"/api/files/list?environment_id={environment_id}", headers=owner_headers
        )
        outsider_terminal = await client.get(
            f"/api/terminal/session?environment_id={environment_id}", headers=outsider_headers
        )
        outsider_session_pairs = await client.get(
            f"/api/terminal/session-pairs?environment_id={environment_id}", headers=outsider_headers
        )
        outsider_files = await client.get(
            f"/api/files/list?environment_id={environment_id}", headers=outsider_headers
        )

    assert owner_files.status_code == 200
    assert outsider_terminal.status_code == 404
    assert outsider_terminal.json() == {"detail": "Environment not found"}
    assert outsider_session_pairs.status_code == 404
    assert outsider_session_pairs.json() == {"detail": "Environment not found"}
    assert outsider_files.status_code == 404
    assert outsider_files.json() == {"detail": "Environment not found"}


@pytest.mark.anyio
async def test_authorized_file_routes_emit_sensitive_path_audit_and_metrics(
    state_root: Path,
    tmp_path: Path,
) -> None:
    reset_metrics()
    app = _v2_app(state_root, tmp_path)
    owner_headers = _headers(app, "runtime-owner", "runtime-owner", "member")
    environment_id = _environment_with_owner_grant(app, state_root, "runtime-owner")
    workdir = state_root / "runtime-environment"
    (workdir / ".ssh" / "private").mkdir(parents=True)
    (workdir / ".env").write_text("TOKEN=secret")
    (workdir / "certificate.pem").write_bytes(b"certificate")

    try:
        with structlog.testing.capture_logs() as logs:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                listed = await client.get(
                    f"/api/files/list?environment_id={environment_id}&path=.ssh/private",
                    headers=owner_headers,
                )
                read = await client.get(
                    f"/api/files/read?environment_id={environment_id}&path=.env",
                    headers=owner_headers,
                )
                streamed = await client.get(
                    f"/api/files/stream?environment_id={environment_id}&path=certificate.pem",
                    headers=owner_headers,
                )
                uploaded = await client.post(
                    "/api/files/upload",
                    headers=owner_headers,
                    data={"environment_id": environment_id, "path": "private.key"},
                    files={"file": ("private.key", b"key")},
                )

        assert listed.status_code == 200
        assert read.status_code == 200
        assert streamed.status_code == 200
        assert uploaded.status_code == 200
        sensitive_logs = [
            entry for entry in logs if entry.get("event") == "files.sensitive_path_access"
        ]
        assert [entry["pattern"] for entry in sensitive_logs] == [
            "~/.ssh/*",
            ".env files",
            "*.pem",
            "*.key",
        ]
        assert all(entry["user_id"] == "runtime-owner" for entry in sensitive_logs)
        assert all(entry["environment_id"] == environment_id for entry in sensitive_logs)
        metrics = get_metrics_text()
        for pattern in ("~/.ssh/*", ".env files", "*.pem", "*.key"):
            assert f'ainrf_files_sensitive_path_access_total{{pattern="{pattern}"}} 1.0' in metrics
    finally:
        reset_metrics()


@pytest.mark.anyio
async def test_v2_runtime_workspace_access_requires_the_linux_tenant_owner(
    state_root: Path,
    tmp_path: Path,
) -> None:
    reset_metrics()
    app = _v2_app(state_root, tmp_path)
    _headers(app, "runtime-owner", "runtime-owner", "member")
    admin_headers = _headers(app, "runtime-admin", "runtime-admin", "admin")
    environment_id = _environment_with_owner_grant(app, state_root, "runtime-owner")
    app.state.auth_service.grant_environment(
        env_id=environment_id,
        user_id="runtime-admin",
        max_tasks=None,
        granted_by="runtime-admin",
        reason="workspace owner guard test execution grant",
    )
    workspace_path = state_root / "runtime-workspace"
    workspace_path.mkdir()
    workspace = app.state.workspace_module.create_workspace(
        {"id": "runtime-owner", "role": "member"},
        environment_id=environment_id,
        canonical_path=str(workspace_path),
        label="Tenant-only workspace",
    )
    workspace_id = str(workspace["workspace_id"])

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            file_read = await client.get(
                f"/api/files/list?environment_id={environment_id}&workspace_id={workspace_id}",
                headers=admin_headers,
            )
            terminal_exec = await client.post(
                "/api/terminal/session/exec",
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
        assert (
            'ainrf_domain_permission_denied_total{reason="tenant_owner_required",resource="workspace"} 2.0'
            in get_metrics_text()
        )
    finally:
        reset_metrics()


@pytest.mark.anyio
async def test_visible_owner_and_admin_without_execution_grant_are_denied_before_file_io(
    state_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _v2_app(state_root, tmp_path)
    owner_headers = _headers(app, "runtime-owner", "runtime-owner", "member")
    admin_headers = _headers(app, "runtime-admin", "runtime-admin", "admin")
    outsider_headers = _headers(app, "runtime-outsider", "runtime-outsider", "member")
    environment = app.state.environment_module.create_environment(
        {"id": "runtime-admin", "role": "admin"},
        alias="runtime-no-grant-host",
        display_name="Runtime no-grant host",
        connection={"host": "127.0.0.1"},
    )
    environment_id = str(environment["environment_id"])
    with closing(sqlite3.connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE environments SET owner_user_id = ? WHERE environment_id = ?",
            ("runtime-owner", environment_id),
        )
        conn.commit()
    calls: list[str] = []

    async def fail_list(*args: object, **kwargs: object) -> object:
        calls.append("list")
        raise AssertionError("FileBrowser list must not run without an execution grant")

    async def fail_upload(*args: object, **kwargs: object) -> object:
        calls.append("upload")
        raise AssertionError("FileBrowser upload must not run without an execution grant")

    async def fail_read(*args: object, **kwargs: object) -> object:
        calls.append("read")
        raise AssertionError("FileBrowser read must not run without an execution grant")

    async def fail_stream_target(*args: object, **kwargs: object) -> object:
        calls.append("stream")
        raise AssertionError("FileBrowser stream must not run without an execution grant")

    monkeypatch.setattr(app.state.file_browser_service, "list_directory", fail_list)
    monkeypatch.setattr(app.state.file_browser_service, "read_file", fail_read)
    monkeypatch.setattr(
        app.state.file_browser_service,
        "resolve_stream_target",
        fail_stream_target,
    )
    monkeypatch.setattr(app.state.file_browser_service, "upload_file", fail_upload)

    def fail_tempfile(*args: object, **kwargs: object) -> object:
        raise AssertionError("Upload temporary file must not be created without a grant")

    monkeypatch.setattr("ainrf.api.routes.files.tempfile.NamedTemporaryFile", fail_tempfile)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner_list = await client.get(
            f"/api/files/list?environment_id={environment_id}", headers=owner_headers
        )
        owner_read = await client.get(
            f"/api/files/read?environment_id={environment_id}&path=blocked.txt",
            headers=owner_headers,
        )
        owner_stream = await client.get(
            f"/api/files/stream?environment_id={environment_id}&path=blocked.txt",
            headers=owner_headers,
        )
        admin_upload = await client.post(
            "/api/files/upload",
            headers=admin_headers,
            data={"environment_id": environment_id, "path": "blocked.txt"},
            files={"file": ("blocked.txt", b"blocked")},
        )
        outsider_list = await client.get(
            f"/api/files/list?environment_id={environment_id}", headers=outsider_headers
        )

    assert owner_list.status_code == 403
    assert owner_read.status_code == 403
    assert owner_stream.status_code == 403
    assert admin_upload.status_code == 403
    assert outsider_list.status_code == 404
    assert calls == []


@pytest.mark.anyio
async def test_environment_execution_grant_passes_then_revoke_denies_and_records_once(
    state_root: Path,
    tmp_path: Path,
) -> None:
    reset_metrics()
    app = _v2_app(state_root, tmp_path)
    admin_headers = _headers(app, "runtime-admin", "runtime-admin", "admin")
    environment_id = _environment_with_owner_grant(app, state_root, "runtime-admin")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        allowed = await client.get(
            f"/api/files/list?environment_id={environment_id}", headers=admin_headers
        )
        app.state.auth_service.revoke_environment(
            environment_id,
            "runtime-admin",
            revoked_by="runtime-admin",
            reason="runtime grant regression",
        )
        denied = await client.get(
            f"/api/files/list?environment_id={environment_id}", headers=admin_headers
        )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Environment execution grant is required"}
    metrics = get_metrics_text()
    assert (
        'ainrf_domain_permission_denied_total{reason="environment_grant_required",resource="environment"} 1.0'
        in metrics
    )
    reset_metrics()


@pytest.mark.anyio
@pytest.mark.parametrize("auth_db_state", ["missing", "corrupt"])
async def test_environment_execution_grant_fails_closed_for_unavailable_auth_authority(
    state_root: Path,
    tmp_path: Path,
    auth_db_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_metrics()
    app = _v2_app(state_root, tmp_path)
    admin_headers = _headers(app, "runtime-admin", "runtime-admin", "admin")
    environment = app.state.environment_module.create_environment(
        {"id": "runtime-admin", "role": "admin"},
        alias=f"runtime-auth-{auth_db_state}",
        display_name="Runtime auth authority test",
        connection={"host": "127.0.0.1"},
    )
    user_record = app.state.auth_service.get_user_by_token(admin_headers["Authorization"][7:])
    monkeypatch.setattr(
        app.state.auth_service,
        "get_user_by_token",
        lambda _token: user_record,
    )
    auth_db = state_root / "runtime" / "auth.sqlite3"
    if auth_db_state == "missing":
        auth_db.unlink()
    else:
        auth_db.write_bytes(b"not a sqlite database")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/files/list?environment_id={environment['environment_id']}",
            headers=admin_headers,
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Environment execution grant is required"}
    metrics = get_metrics_text()
    assert (
        'ainrf_domain_permission_denied_total{reason="environment_grant_required",resource="environment"} 1.0'
        in metrics
    )
    reset_metrics()

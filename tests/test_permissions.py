"""Tests for permission enforcement."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path


class TestPermissionHelpers:
    def test_is_admin(self):
        from ainrf.auth.permissions import is_admin

        assert is_admin({"id": "u1", "role": "admin"}) is True
        assert is_admin({"id": "u2", "role": "member"}) is False

    def test_require_admin_raises_for_member(self):
        from ainrf.auth.permissions import require_admin
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            require_admin({"id": "u2", "role": "member"})
        assert exc.value.status_code == 403

    def test_require_admin_passes_for_admin(self):
        from ainrf.auth.permissions import require_admin

        require_admin({"id": "u1", "role": "admin"})  # no exception

    def test_check_resource_ownership_admin_sees_all(self):
        from ainrf.auth.permissions import check_resource_ownership

        # admin should not raise for any owner
        check_resource_ownership({"id": "admin1", "role": "admin"}, "owner_xyz")
        check_resource_ownership({"id": "admin1", "role": "admin"}, None)

    def test_check_resource_ownership_member_own(self):
        from ainrf.auth.permissions import check_resource_ownership

        check_resource_ownership({"id": "u1", "role": "member"}, "u1")  # no exception

    def test_check_resource_ownership_member_other(self):
        from ainrf.auth.permissions import check_resource_ownership
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            check_resource_ownership({"id": "u1", "role": "member"}, "u2")
        assert exc.value.status_code == 403

    def test_check_resource_ownership_member_null(self):
        from ainrf.auth.permissions import check_resource_ownership
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            check_resource_ownership({"id": "u1", "role": "member"}, None)
        assert exc.value.status_code == 403


@pytest.mark.anyio
class TestAdminApi:
    async def test_list_users_requires_admin(self):
        from tests._testutil import make_client

        async with make_client() as client:
            # Without auth headers, should get 401
            resp = await client.get("/admin/users")
            assert resp.status_code == 401

    async def test_non_admin_cannot_list_users(self):
        from tests._testutil import get_jwt_headers, make_client

        async with make_client() as client:
            headers = get_jwt_headers(client, user_id="member_user", role="member")
            resp = await client.get("/admin/users", headers=headers)
            assert resp.status_code in (403, 404)  # 403 if route in test app, 404 otherwise


def _ensure_user(auth_svc, username, password):
    """Create and activate a user, return their id."""
    try:
        user = auth_svc.register(
            username=username, display_name=username.capitalize(), password=password
        )
    except Exception:
        # already exists - find by username
        user = auth_svc._load_user_by_username(username)
    if user.status.value != "active":
        auth_svc.activate_user(user.id)
    return user.id


class TestCollaboratorCrud:
    @staticmethod
    def _make_service():
        from ainrf.auth import AuthService

        svc = AuthService(state_root=Path(tempfile.mkdtemp()))
        svc.initialize()
        return svc

    def test_add_and_list_collaborator(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.add_collaborator(project_id="p1", user_id=uid, role="member", added_by="admin")
        collabs = svc.list_collaborators("p1")
        assert len(collabs) == 1
        assert collabs[0]["role"] == "member"
        assert collabs[0]["user_id"] == uid

    def test_remove_collaborator(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.add_collaborator(project_id="p1", user_id=uid, role="member", added_by="admin")
        svc.remove_collaborator("p1", uid)
        assert len(svc.list_collaborators("p1")) == 0

    def test_get_user_project_ids(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.add_collaborator(project_id="p1", user_id=uid, role="viewer", added_by="admin")
        svc.add_collaborator(project_id="p2", user_id=uid, role="member", added_by="admin")
        project_ids = svc.get_user_project_ids(uid)
        assert "p1" in project_ids
        assert "p2" in project_ids


class TestEnvironmentAccessCrud:
    @staticmethod
    def _make_service():
        from ainrf.auth import AuthService

        svc = AuthService(state_root=Path(tempfile.mkdtemp()))
        svc.initialize()
        return svc

    def test_grant_and_list(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.grant_environment(env_id="env1", user_id=uid, max_tasks=2, granted_by="admin")
        env_ids = svc.get_user_environment_ids(uid)
        assert "env1" in env_ids

    def test_revoke(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.grant_environment(env_id="env1", user_id=uid, max_tasks=2, granted_by="admin")
        svc.revoke_environment("env1", uid)
        assert "env1" not in svc.get_user_environment_ids(uid)

    def test_grant_unlimited_tasks(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "bob", "bob123")
        svc.grant_environment(env_id="env2", user_id=uid, max_tasks=None, granted_by="admin")
        env_ids = svc.get_user_environment_ids(uid)
        assert "env2" in env_ids


class TestAdminUserManagement:
    @staticmethod
    def _make_service():
        from ainrf.auth import AuthService

        svc = AuthService(state_root=Path(tempfile.mkdtemp()))
        svc.initialize()
        return svc

    def test_list_all_users(self):
        svc = self._make_service()
        _ensure_user(svc, "alice", "alice123")
        _ensure_user(svc, "bob", "bob123")
        users = svc.list_users()
        assert len(users) >= 2

    def test_activate_pending_user(self):
        svc = self._make_service()
        user = svc.register(username="charlie", display_name="Charlie", password="pw123")
        assert user.status.value == "pending"
        activated = svc.activate_user(user.id)
        assert activated.status.value == "active"

    def test_disable_active_user(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "dave", "dave123")
        disabled = svc.disable_user(uid)
        assert disabled.status.value == "disabled"

    def test_reset_password(self):
        svc = self._make_service()
        uid = _ensure_user(svc, "eve", "oldpass")
        svc.reset_password(uid, "newpass")
        result = svc.login(username="eve", password="newpass")
        assert "access_token" in result

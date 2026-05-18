"""Tests for permission enforcement."""

from __future__ import annotations

import pytest


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

    def test_check_resource_owner_admin_sees_all(self):
        from ainrf.auth.permissions import check_resource_owner

        assert (
            check_resource_owner({"id": "admin1", "role": "admin"}, "owner_xyz")
            is True
        )
        assert (
            check_resource_owner({"id": "admin1", "role": "admin"}, None) is True
        )

    def test_check_resource_owner_member_own(self):
        from ainrf.auth.permissions import check_resource_owner

        assert check_resource_owner({"id": "u1", "role": "member"}, "u1") is True

    def test_check_resource_owner_member_other(self):
        from ainrf.auth.permissions import check_resource_owner

        assert check_resource_owner({"id": "u1", "role": "member"}, "u2") is False

    def test_check_resource_owner_member_null(self):
        from ainrf.auth.permissions import check_resource_owner

        assert check_resource_owner({"id": "u1", "role": "member"}, None) is False


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
            assert resp.status_code == 403

"""Tests for authentication service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit]
class TestAuthService:
    @pytest.fixture
    def service(self):
        from ainrf.auth import AuthService

        with tempfile.TemporaryDirectory() as td:
            svc = AuthService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_register_user(self, service):
        user = service.register(username="alice", display_name="Alice", password="secret123")
        assert user.username == "alice"
        assert user.status.value == "pending"
        assert user.role.value == "member"

    def test_register_duplicate_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with pytest.raises(Exception):
            service.register(username="alice", display_name="Alice2", password="other")

    def _activate(self, service, username):
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = ?", (username,))
            conn.commit()

    def test_login_pending_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with pytest.raises(Exception) as exc:
            service.login(username="alice", password="secret")
        assert "pending" in str(exc.value).lower()

    def test_login_active_succeeds(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        self._activate(service, "alice")
        result = service.login(username="alice", password="secret")
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["username"] == "alice"

    def test_login_wrong_password_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        self._activate(service, "alice")
        with pytest.raises(Exception):
            service.login(username="alice", password="wrongpass")

    def test_refresh_token(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        self._activate(service, "alice")
        login_result = service.login(username="alice", password="secret")
        refresh_result = service.refresh(login_result["refresh_token"])
        assert "access_token" in refresh_result

    def test_refresh_invalid_token_fails(self, service):
        with pytest.raises(Exception):
            service.refresh("invalid-token")

    def test_logout(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        self._activate(service, "alice")
        result = service.login(username="alice", password="secret")
        service.logout(result["refresh_token"])
        with pytest.raises(Exception):
            service.refresh(result["refresh_token"])

    def test_get_user_by_token(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        self._activate(service, "alice")
        result = service.login(username="alice", password="secret")
        user = service.get_user_by_token(result["access_token"])
        assert user["username"] == "alice"

    def test_disabled_user_login_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'disabled' WHERE username = ?", ("alice",))
            conn.commit()
        with pytest.raises(Exception) as exc:
            service.login(username="alice", password="secret")
        assert "disabled" in str(exc.value).lower()


class TestJwtUtils:
    def test_create_and_decode_token(self):
        from ainrf.auth.jwt_utils import create_access_token, decode_access_token

        token = create_access_token("user1", "alice", "member")
        payload = decode_access_token(token)
        assert payload["sub"] == "user1"
        assert payload["username"] == "alice"
        assert payload["role"] == "member"

    def test_create_refresh_token(self):
        from ainrf.auth.jwt_utils import create_refresh_token

        plain, hashed = create_refresh_token()
        assert len(plain) == 64
        assert len(hashed) == 64

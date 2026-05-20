"""Internal test utilities for permission and admin API tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key

_app_instance = None
_tmp_path: Path | None = None


def _ensure_app():
    """Lazy-create app singleton so tests can share state."""
    global _app_instance, _tmp_path
    if _app_instance is None:
        _tmp_path = Path(tempfile.mkdtemp())
        _app_instance = create_app(
            ApiConfig(
                api_key_hashes=frozenset({hash_api_key("secret-key")}),
                state_root=_tmp_path,
            )
        )
    return _app_instance


def make_client():
    """Create an unauthenticated async test client."""
    app = _ensure_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


def reset_app_instance():
    """Reset cached app instance between test modules."""
    global _app_instance, _tmp_path
    _app_instance = None
    _tmp_path = None


def get_jwt_headers(client, user_id: str = "test-user", role: str = "admin"):
    """Create JWT auth headers for the given user.

    The *client* argument is accepted for API compatibility but not used directly;
    the underlying app singleton is used to register + login the test user.
    """
    from tests.testutil import get_jwt_headers as _orig

    app = _ensure_app()
    headers = _orig(app, username=user_id, password="test-pass", user_id=user_id)
    # Override role if not admin (the base helper always sets role='admin')
    if role != "admin":
        with app.state.auth_service._connect() as conn:
            conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, user_id))
            conn.commit()
    return headers

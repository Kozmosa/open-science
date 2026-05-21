"""Test utilities for auth-enabled tests."""

from __future__ import annotations

from pathlib import Path

import httpx

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key


def get_jwt_headers(
    app,
    username: str = "test-user",
    password: str = "test-pass",
    user_id: str | None = None,
) -> dict:
    """Register a test user (admin role), log in, and return Authorization headers.

    If *user_id* is given, the user's ID is set to that value (useful when tests
    assert against a well-known user ID such as ``"browser-user"``).
    """
    auth_service = app.state.auth_service
    auth_service.initialize()

    with auth_service._connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

    if row is None:
        auth_service.register(username=username, display_name=username.title(), password=password)

    with auth_service._connect() as conn:
        conn.execute(
            "UPDATE users SET status = 'active', activated_at = ?, role = 'admin'"
            " WHERE username = ?",
            ("2025-01-01T00:00:00+00:00", username),
        )
        if user_id is not None:
            conn.execute("UPDATE users SET id = ? WHERE username = ?", (user_id, username))
        conn.commit()

    token_data = auth_service.login(username=username, password=password)
    return {"Authorization": f"Bearer {token_data['access_token']}"}


def make_client(tmp_path: Path, *, max_file_size_bytes: int | None = None) -> httpx.AsyncClient:
    """Create an authenticated test client with an admin JWT token."""
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config, max_file_size_bytes=max_file_size_bytes)
    headers = get_jwt_headers(app, "admin", "test-admin-password")

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


def make_client_and_app(tmp_path: Path, *, max_file_size_bytes: int | None = None) -> tuple:
    """Create an authenticated test client with admin JWT, returning (app, client, headers)."""
    api_config = ApiConfig(
        api_key_hashes=frozenset({hash_api_key("secret-key")}),
        state_root=tmp_path,
    )
    app = create_app(api_config)
    headers = get_jwt_headers(app, "admin", "test-admin-password")

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )
    return app, client, headers

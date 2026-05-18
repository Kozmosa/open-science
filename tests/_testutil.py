"""Test utilities for JWT authentication in API tests."""
from __future__ import annotations

from fastapi import FastAPI


def get_jwt_headers(app: FastAPI) -> dict[str, str]:
    """Register a test user, activate it, log in, and return Bearer auth headers.

    Call this after creating the app so that app.state.auth_service is available.
    The test user is named "testuser" with password "test123".
    """
    auth_service = app.state.auth_service
    try:
        auth_service.register(username="testuser", display_name="Test User", password="test123")
    except Exception:
        pass
    with auth_service._connect() as conn:
        conn.execute("UPDATE users SET status = 'active' WHERE username = 'testuser'")
        conn.commit()
    result = auth_service.login(username="testuser", password="test123")
    return {"Authorization": f"Bearer {result['access_token']}"}

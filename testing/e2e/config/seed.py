#!/usr/bin/env python3
"""E2E test environment seeder.

Runs INSIDE the ainrf-e2e container after the main entrypoint has started
the app. Creates deterministic test users and writes credentials to
/opt/ainrf/state/e2e-credentials.json for the test runner to pick up.

All user creation happens via direct DB access (bypassing API) for maximum
reliability. The only API call is a login to obtain JWT tokens.
"""

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

STATE_ROOT = Path("/opt/ainrf/state")
CREDENTIALS_FILE = STATE_ROOT / "e2e-credentials.json"
AUTH_DB = STATE_ROOT / "runtime" / "auth.sqlite3"
BASE_URL = "http://localhost:8000"

TEST_USERS = [
    {"username": "admin", "password": "E2eAdminPass123!", "role": "admin"},
    {"username": "alice", "password": "E2eAlicePass456!", "role": "member"},
    {"username": "bob",   "password": "E2eBobPass789!",   "role": "member"},
]


def _wait_for_health(max_wait: int = 120) -> None:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            if urllib.request.urlopen(f"{BASE_URL}/health").getcode() == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    sys.exit("Timed out waiting for /health")


def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _create_users_db() -> None:
    """Create/fix all test users directly in the auth database."""
    conn = sqlite3.connect(str(AUTH_DB))
    now = datetime.now(timezone.utc).isoformat()

    for user in TEST_USERS:
        pw_hash = _hash_password(user["password"])
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (user["username"],)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE users
                   SET password_hash = ?, role = ?, status = 'active',
                       activated_at = ?, must_change_password = 0
                   WHERE username = ?""",
                (pw_hash, user["role"], now, user["username"]),
            )
        else:
            conn.execute(
                """INSERT INTO users
                   (id, username, password_hash, display_name, role, status,
                    created_at, activated_at, must_change_password)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0)""",
                (uuid4().hex[:12], user["username"], pw_hash,
                 user["username"].title(), user["role"], now, now),
            )

    conn.commit()
    conn.close()


def _login(username: str, password: str) -> str:
    data = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/auth/login", data=data, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def seed() -> None:
    print("[e2e-seed] Waiting for app to become healthy...")
    _wait_for_health()
    print("[e2e-seed] App is healthy. Seeding test data...")

    _create_users_db()

    credentials = {}
    for user in TEST_USERS:
        try:
            token = _login(user["username"], user["password"])
            credentials[user["username"]] = {
                "password": user["password"],
                "token": token,
                "role": user["role"],
            }
            print(f"[e2e-seed] ✓ {user['username']} ({user['role']})")
        except Exception as exc:
            print(f"[e2e-seed] ✗ {user['username']}: {exc}")

    CREDENTIALS_FILE.write_text(json.dumps(credentials, indent=2))
    print(f"[e2e-seed] Credentials written to {CREDENTIALS_FILE}")


if __name__ == "__main__":
    seed()

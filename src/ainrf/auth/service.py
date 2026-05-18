# src/ainrf/auth/service.py
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

from ainrf.auth.jwt_utils import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from ainrf.auth.models import (
    AuthError,
    User,
    UserRole,
    UserStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AuthService:
    def __init__(self, *, state_root: Path) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "auth.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    last_login_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        return conn

    # --- Registration ---

    def register(self, *, username: str, display_name: str, password: str) -> User:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is not None:
            raise AuthError(f"Username '{username}' already exists")

        uid = _new_id()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, role, status, created_at) "
                "VALUES (?, ?, ?, ?, 'member', 'pending', ?)",
                (uid, username, password_hash, display_name, now),
            )
            conn.commit()
        return self._load_user(uid)

    # --- Login ---

    def login(self, *, username: str, password: str) -> dict:
        """Returns {access_token, refresh_token, user} or raises AuthError."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            raise AuthError("Invalid username or password")
        user = _row_to_user(row)
        if user.status == UserStatus.PENDING:
            raise AuthError("Account is pending approval")
        if user.status == UserStatus.DISABLED:
            raise AuthError("Account is disabled")

        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise AuthError("Invalid username or password")

        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?", (now, user.id)
            )
            conn.commit()

        access_token = create_access_token(user.id, user.username, user.role.value)
        plain_refresh, hashed_refresh = create_refresh_token()
        expires_at = (datetime.now(timezone.utc).timestamp() + 7 * 86400)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (_new_id(), user.id, hashed_refresh,
                 datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(), now),
            )
            conn.commit()

        return {
            "access_token": access_token,
            "refresh_token": plain_refresh,
            "user": _user_to_dict(user),
        }

    # --- Refresh ---

    def refresh(self, refresh_token: str) -> dict:
        """Returns {access_token} or raises AuthError."""
        self.initialize()
        token_hash_val = hashlib.sha256(refresh_token.encode()).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash_val,)
            ).fetchone()
        if row is None:
            raise AuthError("Invalid refresh token")

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            with self._connect() as conn:
                conn.execute("DELETE FROM refresh_tokens WHERE id = ?", (row["id"],))
                conn.commit()
            raise AuthError("Refresh token expired")

        user = self._load_user(row["user_id"])
        if user.status != UserStatus.ACTIVE:
            raise AuthError("Account is not active")

        access_token = create_access_token(user.id, user.username, user.role.value)
        return {"access_token": access_token}

    # --- Logout ---

    def logout(self, refresh_token: str) -> None:
        self.initialize()
        token_hash_val = hashlib.sha256(refresh_token.encode()).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash_val,)
            )
            conn.commit()

    # --- Me ---

    def get_user(self, user_id: str) -> User:
        return self._load_user(user_id)

    def get_user_by_token(self, token: str) -> dict:
        """Validate access token and return user dict."""
        payload = decode_access_token(token)
        user = self._load_user(payload["sub"])
        if user.status != UserStatus.ACTIVE:
            raise AuthError("Account is not active")
        return _user_to_dict(user)

    # --- Internal ---

    def _load_user(self, user_id: str) -> User:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise AuthError(f"User not found: {user_id}")
        return _row_to_user(row)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        role=UserRole(row["role"]),
        status=UserStatus(row["status"]),
        created_at=row["created_at"],
        activated_at=row["activated_at"],
        last_login_at=row["last_login_at"],
    )


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
    }

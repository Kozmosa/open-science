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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_collaborators (
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    added_by_user_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, user_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS environment_access (
                    environment_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    max_concurrent_tasks INTEGER,
                    granted_by_user_id TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY (environment_id, user_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_collab_user ON project_collaborators(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_env_access_user ON environment_access(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
            )
            # Migration: add must_change_password column
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.commit()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        return conn

    # --- Registration ---

    def register(
        self, *, username: str, display_name: str, password: str, must_change_password: bool = False,
    ) -> User:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            raise AuthError(f"Username '{username}' already exists")

        uid = _new_id()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, role, status, "
                "created_at, must_change_password) "
                "VALUES (?, ?, ?, ?, 'member', 'pending', ?, ?)",
                (uid, username, password_hash, display_name, now, int(must_change_password)),
            )
            conn.commit()
        return self._load_user(uid)

    # --- Login ---

    def login(self, *, username: str, password: str) -> dict:
        """Returns {access_token, refresh_token, user} or raises AuthError."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
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
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user.id))
            conn.commit()

        access_token = create_access_token(user.id, user.username, user.role.value)
        plain_refresh, hashed_refresh = create_refresh_token()
        expires_at = datetime.now(timezone.utc).timestamp() + 7 * 86400
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _new_id(),
                    user.id,
                    hashed_refresh,
                    datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                    now,
                ),
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
            conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash_val,))
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

    # --- Admin: User Management ---

    def list_users(self) -> list[User]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [_row_to_user(r) for r in rows]

    def activate_user(self, user_id: str) -> User:
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET status = 'active', activated_at = ? WHERE id = ?",
                (now, user_id),
            )
            if conn.total_changes == 0:
                raise AuthError(f"User not found: {user_id}")
            conn.commit()
        # Auto-grant seed environments to newly activated user
        self._grant_seed_environments(user_id)
        return self._load_user(user_id)

    def _grant_seed_environments(self, user_id: str) -> None:
        """Grant access to built-in seed environments (e.g., localhost)."""
        seed_envs = [
            ("env-localhost", None),  # (env_id, max_concurrent_tasks)
        ]
        now = _now_iso()
        with self._connect() as conn:
            for env_id, max_tasks in seed_envs:
                conn.execute(
                    "INSERT OR IGNORE INTO environment_access "
                    "(environment_id, user_id, max_concurrent_tasks, granted_by_user_id, granted_at) "
                    "VALUES (?, ?, ?, 'system', ?)",
                    (env_id, user_id, max_tasks, now),
                )
            conn.commit()

    def disable_user(self, user_id: str) -> User:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET status = 'disabled' WHERE id = ?",
                (user_id,),
            )
            if conn.total_changes == 0:
                raise AuthError(f"User not found: {user_id}")
            conn.commit()
        return self._load_user(user_id)

    def reset_password(self, user_id: str, new_password: str) -> None:
        self.initialize()
        password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
            conn.commit()

    # --- Collaborator Management ---

    def add_collaborator(self, *, project_id: str, user_id: str, role: str, added_by: str) -> None:
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO project_collaborators "
                "(project_id, user_id, role, added_by_user_id, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, user_id, role, added_by, now),
            )
            conn.commit()

    def remove_collaborator(self, project_id: str, user_id: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM project_collaborators WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )
            conn.commit()

    def list_collaborators(self, project_id: str) -> list[dict]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pc.role, pc.user_id, u.username, u.display_name "
                "FROM project_collaborators pc JOIN users u ON pc.user_id = u.id "
                "WHERE pc.project_id = ?",
                (project_id,),
            ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "display_name": r["display_name"],
                "role": r["role"],
            }
            for r in rows
        ]

    def get_user_project_ids(self, user_id: str) -> list[str]:
        """Return project_ids where user is a collaborator (not including owned projects)."""
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT project_id FROM project_collaborators WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [r["project_id"] for r in rows]

    # --- Environment Access ---

    def grant_environment(
        self, *, env_id: str, user_id: str, max_tasks: int | None, granted_by: str
    ) -> None:
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO environment_access "
                "(environment_id, user_id, max_concurrent_tasks, granted_by_user_id, granted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (env_id, user_id, max_tasks, granted_by, now),
            )
            conn.commit()

    def revoke_environment(self, env_id: str, user_id: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM environment_access WHERE environment_id = ? AND user_id = ?",
                (env_id, user_id),
            )
            conn.commit()

    def get_user_environment_ids(self, user_id: str) -> list[str]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT environment_id FROM environment_access WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [r["environment_id"] for r in rows]

    # --- Change Password ---

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        """Change password. Verifies old password first. Clears must_change_password flag."""
        user = self._load_user(user_id)
        if not bcrypt.checkpw(old_password.encode(), user.password_hash.encode()):
            raise AuthError("Current password is incorrect")
        password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (password_hash, user_id),
            )
            conn.commit()

    # --- Internal ---

    def _load_user(self, user_id: str) -> User:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise AuthError(f"User not found: {user_id}")
        return _row_to_user(row)

    def _load_user_by_username(self, username: str) -> User:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise AuthError(f"User not found: {username}")
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
        must_change_password=bool(row["must_change_password"]) if "must_change_password" in row.keys() else False,
    )


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "must_change_password": user.must_change_password,
    }

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import subprocess
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

_LOG = logging.getLogger(__name__)

# Linux usernames: lowercase ASCII + digits + hyphen + underscore, start with
# a letter or digit, 2–31 chars.  The AINRF prefix ``ainrf_`` is added
# automatically, so the final Linux username will be ``ainrf_<username>``.
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")

# Fixed GID for the ``ainrf_tenants`` group created in the Dockerfile.
_TENANT_GID = 2000
_TENANT_GROUP = "ainrf_tenants"
_TENANT_HOME_ROOT = Path("/home/ainrf_tenants")


def tenant_linux_username(ainrf_username: str) -> str:
    """Return the Linux username for an AINRF user, e.g. ``aaa`` → ``ainrf_aaa``."""
    return f"ainrf_{ainrf_username}"


def tenant_home_dir(ainrf_username: str) -> Path:
    """Return the home directory for an AINRF tenant user."""
    return _TENANT_HOME_ROOT / ainrf_username


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AuthService:
    def __init__(
        self, *, state_root: Path, login_max_failures: int = 10, login_lockout_hours: int = 24
    ) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "auth.sqlite3"
        self._initialized = False
        self._login_max_failures = login_max_failures
        self._login_lockout_hours = login_lockout_hours

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    attempted_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, attempted_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip_address, attempted_at)"
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
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        must_change_password: bool = False,
    ) -> User:
        if not _USERNAME_RE.fullmatch(username):
            raise AuthError(
                "Username must be 2-31 characters, start with a letter or digit, "
                "and contain only lowercase letters, digits, underscores, or hyphens"
            )
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

        self._ensure_tenant_user(username)
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

    # --- Login brute-force protection ---

    class AccountLockedError(AuthError):
        """Raised when an account or IP is temporarily locked due to too many failures."""

    def check_login_lockout(self, *, username: str, ip_address: str) -> None:
        """Raise AccountLockedError if the username or IP has too many recent failures."""
        self.initialize()
        cutoff = datetime.now(timezone.utc).timestamp() - self._login_lockout_hours * 3600
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        with self._connect() as conn:
            user_failures = conn.execute(
                "SELECT COUNT(*) FROM login_attempts "
                "WHERE username = ? AND success = 0 AND attempted_at > ?",
                (username, cutoff_iso),
            ).fetchone()[0]
            ip_failures = conn.execute(
                "SELECT COUNT(*) FROM login_attempts "
                "WHERE ip_address = ? AND success = 0 AND attempted_at > ?",
                (ip_address, cutoff_iso),
            ).fetchone()[0]
        if user_failures >= self._login_max_failures:
            raise self.AccountLockedError(
                f"Account locked: too many failed login attempts. "
                f"Try again in {self._login_lockout_hours} hours or contact an admin."
            )
        if ip_failures >= self._login_max_failures * 3:
            raise self.AccountLockedError(
                "IP locked: too many failed login attempts from this address."
            )

    def record_login_attempt(self, *, username: str, ip_address: str, success: bool) -> None:
        """Record a login attempt for brute-force tracking."""
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO login_attempts (id, username, ip_address, success, attempted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (_new_id(), username, ip_address, int(success), now),
            )
            # Cleanup attempts older than 2x lockout window to bound table growth
            cutoff = datetime.now(timezone.utc).timestamp() - self._login_lockout_hours * 3600 * 2
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff_iso,))
            conn.commit()

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

    def _ensure_tenant_user(self, username: str) -> None:
        """Create Linux user, home directory and default workspace for *username*.

        Silently succeeds if the user or directories already exist so that the
        method is safe to call idempotently (e.g. during migration).
        """
        provision_tenant_user(username)


def _ensure_tenant_group() -> None:
    """Create the ``ainrf_tenants`` group (GID 2000) if it does not exist."""
    result = subprocess.run(
        ["getent", "group", _TENANT_GROUP],
        capture_output=True,
    )
    if result.returncode != 0:
        _LOG.info("_ensure_tenant_group: creating group %s (gid %d)", _TENANT_GROUP, _TENANT_GID)
        subprocess.run(
            ["groupadd", "--gid", str(_TENANT_GID), _TENANT_GROUP],
            check=True,
            capture_output=True,
        )


def _linux_user_exists(username: str) -> bool:
    return subprocess.run(
        ["id", username], capture_output=True
    ).returncode == 0


def _chown_recursive(path: Path, user: str, group: str) -> None:
    subprocess.run(
        ["chown", "-R", f"{user}:{group}", str(path)],
        check=True,
        capture_output=True,
    )


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
        must_change_password=bool(row["must_change_password"])
        if "must_change_password" in row.keys()
        else False,
    )


def _is_container_environment() -> bool:
    """Return True if running inside a container with the ainrf_tenants group."""
    return Path("/opt/ainrf/state").is_dir() or Path("/.dockerenv").exists()


def provision_tenant_user(username: str) -> None:
    """Create the Linux user ``ainrf_<username>`` with home directory and
    default workspace tree.  Idempotent — safe to call for existing users.

    Outside a container (local dev / tests), creates the workspace directory
    under a temp-root instead of ``/home/ainrf_tenants/`` so the caller does
    not need root privileges.
    """
    linux_user = tenant_linux_username(username)
    home = tenant_home_dir(username)
    workspace_dir = home / "workspaces" / "default"

    if _is_container_environment():
        _ensure_tenant_group()
        if not _linux_user_exists(linux_user):
            _LOG.info("provision_tenant_user: creating Linux user %s", linux_user)
            subprocess.run(
                [
                    "useradd",
                    "--gid", str(_TENANT_GID),
                    "--home-dir", str(home),
                    "--create-home",
                    "--shell", "/bin/bash",
                    linux_user,
                ],
                check=True,
                capture_output=True,
            )
        home.mkdir(parents=True, exist_ok=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        _chown_recursive(home, linux_user, _TENANT_GROUP)
    else:
        # Local dev / tests: just ensure the workspace dir is creatable.
        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            _LOG.debug(
                "provision_tenant_user: cannot create %s (non-container), "
                "using /tmp fallback",
                workspace_dir,
            )
            fallback = Path("/tmp/ainrf_tenants") / username / "workspaces" / "default"
            fallback.mkdir(parents=True, exist_ok=True)


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "must_change_password": user.must_change_password,
    }

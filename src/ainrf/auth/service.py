from __future__ import annotations

import hashlib
import logging
import os
import shutil
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
from ainrf.auth.username import USERNAME_REQUIREMENT, is_valid_username
from ainrf.runtime import tenant_identity

_LOG = logging.getLogger(__name__)


# Fixed GID for the ``ainrf_tenants`` group created in the Dockerfile.
def _is_root() -> bool:
    """Return True if the current process is running as root."""
    return os.geteuid() == 0


def _run_privileged(cmd: list[str]) -> None:
    """Run *cmd* as root, prefixing with ``sudo`` when not already root.

    Raises AuthError if the command fails or if sudo is unavailable.
    """
    if not _is_root():
        if shutil.which("sudo") is None:
            raise AuthError("sudo is required for tenant provisioning but is not installed")
        cmd = ["sudo", *cmd]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise AuthError(f"Privileged command failed: {' '.join(cmd)}: {stderr}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _upsert_environment_grant(
    conn: sqlite3.Connection,
    *,
    env_id: str,
    user_id: str,
    max_tasks: int | None,
    granted_by: str,
    now: str,
    reason: str | None,
    reactivate_only: bool,
) -> bool:
    """Create or renew one versioned Environment authorization grant.

    Seed provisioning is deliberately idempotent for already-active grants;
    explicit administrator grants always advance the version so a dispatcher
    can distinguish a fresh authorization decision from an earlier one.
    """
    if max_tasks is not None and max_tasks < 0:
        raise AuthError("max_concurrent_tasks must be zero or greater")
    reactivate_clause = "WHERE environment_access.status = 'revoked'" if reactivate_only else ""
    cursor = conn.execute(
        f"""
        INSERT INTO environment_access (
            environment_id, user_id, max_concurrent_tasks, granted_by_user_id,
            granted_at, grant_version, status, updated_at, revoked_at,
            grant_reason, revoked_by_user_id, revocation_reason
        ) VALUES (?, ?, ?, ?, ?, 1, 'active', ?, NULL, ?, NULL, NULL)
        ON CONFLICT(environment_id, user_id) DO UPDATE SET
            max_concurrent_tasks = excluded.max_concurrent_tasks,
            granted_by_user_id = excluded.granted_by_user_id,
            granted_at = excluded.granted_at,
            grant_version = environment_access.grant_version + 1,
            status = 'active',
            updated_at = excluded.updated_at,
            revoked_at = NULL,
            grant_reason = excluded.grant_reason,
            revoked_by_user_id = NULL,
            revocation_reason = NULL
        {reactivate_clause}
        """,
        (env_id, user_id, max_tasks, granted_by, now, now, reason),
    )
    if cursor.rowcount == 0:
        return False
    return True


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
        from ainrf.db.migration import run_pending

        with self._connect() as conn:
            run_pending(conn, "auth")
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        from ainrf.db.connection import connect

        return connect(str(self._db_path))

    # --- Registration ---

    def register(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        must_change_password: bool = False,
    ) -> User:
        self.initialize()
        if not is_valid_username(username):
            raise AuthError(USERNAME_REQUIREMENT)
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
            # The default Project lives in the separate domain database.  Do
            # not fake a distributed transaction: persist this intent beside
            # the newly-created user and let the v2 control plane reconcile it
            # idempotently after the auth transaction commits.
            conn.execute(
                """
                INSERT INTO domain_default_project_provisioning (
                    user_id, username, status, attempt_count, created_at, updated_at
                ) VALUES (?, ?, 'queued', 0, ?, ?)
                """,
                (uid, username, now, now),
            )
            conn.commit()

        self._ensure_tenant_user(username)
        return self._load_user(uid)

    def ensure_domain_default_project_provisioning(self, user_id: str, username: str) -> None:
        """Backfill an idempotent default-Project provisioning intent for one user."""

        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO domain_default_project_provisioning (
                    user_id, username, status, attempt_count, created_at, updated_at
                ) VALUES (?, ?, 'queued', 0, ?, ?)
                """,
                (user_id, username, now, now),
            )
            conn.commit()

    def pending_domain_default_project_provisioning(self) -> list[tuple[str, str]]:
        """Return durable provisioning work that has not reached the v2 domain."""

        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, username FROM domain_default_project_provisioning
                WHERE status = 'queued'
                ORDER BY created_at, user_id
                """
            ).fetchall()
        return [(str(row["user_id"]), str(row["username"])) for row in rows]

    def mark_domain_default_project_provisioned(self, user_id: str) -> None:
        """Acknowledge a successful idempotent v2 default-Project write."""

        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            updated = conn.execute(
                """
                UPDATE domain_default_project_provisioning
                SET status = 'provisioned', last_error = NULL, provisioned_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (now, now, user_id),
            ).rowcount
            if updated != 1:
                raise AuthError("Default Project provisioning intent is missing")
            conn.commit()

    def record_domain_default_project_provisioning_failure(
        self, user_id: str, error: Exception
    ) -> None:
        """Retain a bounded diagnostic while keeping the provisioning intent retryable."""

        self.initialize()
        now = _now_iso()
        detail = str(error).strip() or type(error).__name__
        with self._connect() as conn:
            updated = conn.execute(
                """
                UPDATE domain_default_project_provisioning
                SET status = 'queued', attempt_count = attempt_count + 1,
                    last_error = ?, updated_at = ?
                WHERE user_id = ? AND status = 'queued'
                """,
                (detail[:1024], now, user_id),
            ).rowcount
            if updated != 1:
                raise AuthError("Default Project provisioning intent is missing")
            conn.commit()

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
                _upsert_environment_grant(
                    conn,
                    env_id=env_id,
                    user_id=user_id,
                    max_tasks=max_tasks,
                    granted_by="system",
                    now=now,
                    reason="seed environment provisioning",
                    reactivate_only=True,
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

    # --- Environment Access ---

    def grant_environment(
        self,
        *,
        env_id: str,
        user_id: str,
        max_tasks: int | None,
        granted_by: str,
        reason: str | None = None,
    ) -> None:
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            _upsert_environment_grant(
                conn,
                env_id=env_id,
                user_id=user_id,
                max_tasks=max_tasks,
                granted_by=granted_by,
                now=now,
                reason=reason,
                reactivate_only=False,
            )
            conn.commit()

    def revoke_environment(
        self,
        env_id: str,
        user_id: str,
        *,
        revoked_by: str = "system",
        reason: str | None = None,
    ) -> None:
        self.initialize()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE environment_access
                SET status = 'revoked',
                    grant_version = grant_version + 1,
                    updated_at = ?,
                    revoked_at = ?,
                    revoked_by_user_id = ?,
                    revocation_reason = ?
                WHERE environment_id = ? AND user_id = ? AND status = 'active'
                """,
                (now, now, revoked_by, reason, env_id, user_id),
            )
            conn.commit()

    def get_user_environment_ids(self, user_id: str) -> list[str]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT environment_id FROM environment_access "
                "WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchall()
        return [r["environment_id"] for r in rows]

    def list_environment_access(self, env_id: str) -> list[dict[str, object]]:
        """Return active grants with their authoritative concurrency limits."""

        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT access.user_id, user.username, user.display_name,
                       access.max_concurrent_tasks
                FROM environment_access AS access
                JOIN users AS user ON user.id = access.user_id
                WHERE access.environment_id = ? AND access.status = 'active'
                ORDER BY user.username, access.user_id
                """,
                (env_id,),
            ).fetchall()
        return [
            {
                "user_id": str(row["user_id"]),
                "username": str(row["username"]),
                "display_name": str(row["display_name"]),
                "max_concurrent_tasks": (
                    None
                    if row["max_concurrent_tasks"] is None
                    else int(row["max_concurrent_tasks"])
                ),
            }
            for row in rows
        ]

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
        ["getent", "group", tenant_identity.TENANT_GROUP],
        capture_output=True,
    )
    if result.returncode != 0:
        _LOG.info(
            "_ensure_tenant_group: creating group %s (gid %d)",
            tenant_identity.TENANT_GROUP,
            tenant_identity.TENANT_GID,
        )
        _run_privileged(
            [
                "groupadd",
                "--gid",
                str(tenant_identity.TENANT_GID),
                tenant_identity.TENANT_GROUP,
            ]
        )


def _chown_recursive(path: Path, user: str, group: str) -> None:
    _run_privileged(["chown", "-R", f"{user}:{group}", str(path)])


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


def provision_tenant_user(username: str) -> None:
    """Create the Linux user ``ainrf_<username>`` with home directory and
    default workspace tree.  Idempotent — safe to call for existing users.

    Outside a container (local dev / tests), creates the workspace directory
    under a temp-root instead of ``/home/ainrf_tenants/`` so the caller does
    not need root privileges.
    """
    linux_user = tenant_identity.tenant_linux_username(username)
    home = tenant_identity.tenant_home_dir(username)
    workspace_dir = home / "workspaces" / "default"

    if tenant_identity.is_container_environment():
        _ensure_tenant_group()
        if not tenant_identity.linux_user_exists(linux_user):
            _LOG.info("provision_tenant_user: creating Linux user %s", linux_user)
            _run_privileged(
                [
                    "useradd",
                    "--gid",
                    str(tenant_identity.TENANT_GID),
                    "--home-dir",
                    str(home),
                    "--create-home",
                    "--shell",
                    "/bin/bash",
                    linux_user,
                ]
            )
        # Create/ensure the home tree as root, then hand ownership to the tenant.
        _run_privileged(["mkdir", "-p", str(home), str(workspace_dir)])
        _chown_recursive(home, linux_user, tenant_identity.TENANT_GROUP)
    else:
        # Local dev / tests: just ensure the workspace dir is creatable.
        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            _LOG.debug(
                "provision_tenant_user: cannot create %s (non-container), using /tmp fallback",
                workspace_dir,
            )
            fallback = Path("/tmp/ainrf_tenants") / username / "workspaces" / "default"
            fallback.mkdir(parents=True, exist_ok=True)


def provision_tenant_owned_path(path: Path, username: str) -> None:
    """Create a runtime path owned by the user's Linux tenant identity."""

    if tenant_identity.is_container_environment():
        provision_tenant_user(username)
        linux_user = tenant_identity.tenant_linux_username(username)
        _run_privileged(["mkdir", "-p", str(path)])
        _chown_recursive(path, linux_user, tenant_identity.TENANT_GROUP)
        return
    path.mkdir(parents=True, exist_ok=True)


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "must_change_password": user.must_change_password,
    }

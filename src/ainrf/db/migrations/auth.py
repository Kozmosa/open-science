from __future__ import annotations

import sqlite3

from ainrf.db.migration import registry

_DATABASE = "auth"


@registry.register(_DATABASE)
def migration_001_baseline(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_collaborators (
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            added_by_user_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS environment_access (
            environment_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            max_concurrent_tasks INTEGER,
            granted_by_user_id TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY (environment_id, user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_collab_user ON project_collaborators(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_env_access_user ON environment_access(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, attempted_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip_address, attempted_at)"
    )


@registry.register(_DATABASE)
def migration_002_must_change_password(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists


@registry.register(_DATABASE)
def migration_003_admin_role_fix(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE users SET role = 'admin' WHERE username = 'admin' AND role != 'admin'")


@registry.register(_DATABASE)
def migration_004_login_attempts_cleanup_index(conn: sqlite3.Connection) -> None:
    """Index on attempted_at so periodic cleanup DELETE is a range scan, not a full table scan."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_attempted_at ON login_attempts(attempted_at)"
    )


@registry.register(_DATABASE)
def migration_005_environment_grant_versioning(conn: sqlite3.Connection) -> None:
    for name, definition in (
        ("grant_version", "INTEGER NOT NULL DEFAULT 1"),
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ("updated_at", "TEXT"),
        ("revoked_at", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE environment_access ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass
    conn.execute("UPDATE environment_access SET updated_at = granted_at WHERE updated_at IS NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_env_access_active ON environment_access(user_id, status)"
    )


@registry.register(_DATABASE)
def migration_006_harden_environment_grant_history(conn: sqlite3.Connection) -> None:
    """Keep Environment grants durable, versioned, and auditable.

    ``environment_access`` predates the domain control plane and originally
    modelled a grant as a row that could simply be deleted.  A dispatcher must
    be able to prove which authorization version it checked, so revocation is
    now a state transition and every transition has an append-only audit row.
    """
    for name, definition in (
        ("grant_reason", "TEXT"),
        ("revoked_by_user_id", "TEXT"),
        ("revocation_reason", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE environment_access ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.execute(
        """
        UPDATE environment_access
        SET grant_version = CASE
                WHEN grant_version IS NULL OR grant_version < 1 THEN 1
                ELSE grant_version
            END,
            status = CASE
                WHEN status IN ('active', 'revoked') THEN status
                ELSE 'active'
            END,
            updated_at = COALESCE(updated_at, granted_at)
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS environment_access_audit_events (
            event_id TEXT PRIMARY KEY,
            environment_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            grant_version INTEGER NOT NULL CHECK (grant_version >= 1),
            event_type TEXT NOT NULL CHECK (event_type IN ('granted', 'revoked')),
            actor_user_id TEXT NOT NULL,
            max_concurrent_tasks INTEGER,
            reason TEXT,
            occurred_at TEXT NOT NULL,
            UNIQUE(environment_id, user_id, grant_version)
        );
        CREATE INDEX IF NOT EXISTS idx_env_access_audit_subject
        ON environment_access_audit_events(environment_id, user_id, grant_version DESC);

        CREATE TRIGGER IF NOT EXISTS trg_env_access_audit_prevent_update
        BEFORE UPDATE ON environment_access_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'environment access audit events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_audit_prevent_delete
        BEFORE DELETE ON environment_access_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'environment access audit events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_status_insert
        BEFORE INSERT ON environment_access
        WHEN NEW.status NOT IN ('active', 'revoked')
        BEGIN
            SELECT RAISE(ABORT, 'environment access status must be active or revoked');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_status_update
        BEFORE UPDATE OF status ON environment_access
        WHEN NEW.status NOT IN ('active', 'revoked')
        BEGIN
            SELECT RAISE(ABORT, 'environment access status must be active or revoked');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_version_insert
        BEFORE INSERT ON environment_access
        WHEN NEW.grant_version < 1
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant_version must be positive');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_version_update
        BEFORE UPDATE OF grant_version ON environment_access
        WHEN NEW.grant_version <= OLD.grant_version
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant_version must increase');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_env_access_prevent_delete
        BEFORE DELETE ON environment_access
        BEGIN
            SELECT RAISE(ABORT, 'environment access grants are retained for audit history');
        END;
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO environment_access_audit_events (
            event_id, environment_id, user_id, grant_version, event_type,
            actor_user_id, max_concurrent_tasks, reason, occurred_at
        )
        SELECT
            lower(hex(randomblob(16))),
            environment_id,
            user_id,
            grant_version,
            CASE WHEN status = 'revoked' THEN 'revoked' ELSE 'granted' END,
            CASE
                WHEN status = 'revoked' THEN COALESCE(revoked_by_user_id, granted_by_user_id)
                ELSE granted_by_user_id
            END,
            max_concurrent_tasks,
            CASE
                WHEN status = 'revoked' THEN revocation_reason
                ELSE grant_reason
            END,
            COALESCE(revoked_at, updated_at, granted_at)
        FROM environment_access
        """
    )


@registry.register(_DATABASE)
def migration_007_domain_default_project_provisioning(conn: sqlite3.Connection) -> None:
    """Persist the cross-database default-Project provisioning intent.

    User registration is authoritative in ``auth.sqlite3`` while the default
    Project belongs to the domain control plane.  The two databases must not
    pretend to share a transaction, so registration records a durable intent
    locally and a v2 process reconciles it through an idempotent domain write.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_default_project_provisioning (
            user_id TEXT PRIMARY KEY REFERENCES users(id)
                ON DELETE RESTRICT ON UPDATE CASCADE,
            username TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'provisioned')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            provisioned_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_domain_default_project_provisioning_pending
        ON domain_default_project_provisioning(status, updated_at, user_id)
        WHERE status = 'queued';
        """
    )

-- Generated from the current fresh-install schema. Do not edit historical migrations here.
CREATE TABLE domain_default_project_provisioning (
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
CREATE TABLE environment_access (
            environment_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            max_concurrent_tasks INTEGER,
            granted_by_user_id TEXT NOT NULL,
            granted_at TEXT NOT NULL, grant_version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active', updated_at TEXT, revoked_at TEXT, grant_reason TEXT, revoked_by_user_id TEXT, revocation_reason TEXT,
            PRIMARY KEY (environment_id, user_id)
        );
CREATE TABLE login_attempts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        );
CREATE TABLE refresh_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
CREATE TABLE "users" (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('admin', 'member')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
            created_at TEXT NOT NULL,
            activated_at TEXT,
            last_login_at TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 0
        );
CREATE INDEX idx_env_access_user ON environment_access(user_id);
CREATE INDEX idx_users_status ON users(status);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
CREATE INDEX idx_login_attempts_username_time ON login_attempts(username, attempted_at);
CREATE INDEX idx_login_attempts_ip_time ON login_attempts(ip_address, attempted_at);
CREATE INDEX idx_login_attempts_attempted_at ON login_attempts(attempted_at);
CREATE INDEX idx_env_access_active ON environment_access(user_id, status);
CREATE TRIGGER trg_env_access_status_insert
        BEFORE INSERT ON environment_access
        WHEN NEW.status NOT IN ('active', 'revoked')
        BEGIN
            SELECT RAISE(ABORT, 'environment access status must be active or revoked');
        END;
CREATE TRIGGER trg_env_access_status_update
        BEFORE UPDATE OF status ON environment_access
        WHEN NEW.status NOT IN ('active', 'revoked')
        BEGIN
            SELECT RAISE(ABORT, 'environment access status must be active or revoked');
        END;
CREATE TRIGGER trg_env_access_version_insert
        BEFORE INSERT ON environment_access
        WHEN NEW.grant_version < 1
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant_version must be positive');
        END;
CREATE TRIGGER trg_env_access_version_update
        BEFORE UPDATE OF grant_version ON environment_access
        WHEN NEW.grant_version <= OLD.grant_version
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant_version must increase');
        END;
CREATE TRIGGER trg_env_access_prevent_delete
        BEFORE DELETE ON environment_access
        BEGIN
            SELECT RAISE(ABORT, 'environment access grant authority must be revoked, not deleted');
        END;
CREATE INDEX idx_domain_default_project_provisioning_pending
        ON domain_default_project_provisioning(status, updated_at, user_id)
        WHERE status = 'queued';

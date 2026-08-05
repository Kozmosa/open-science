-- Generated from the current fresh-install schema. Do not edit historical migrations here.
CREATE TABLE user_environment_bindings (
            binding_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            remote_login_user TEXT NOT NULL,
            default_shell TEXT,
            default_workdir TEXT,
            mux_kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, environment_id)
        );
CREATE TABLE user_session_pairs (
            binding_id TEXT PRIMARY KEY,
            personal_session_name TEXT NOT NULL,
            agent_session_name TEXT,
            personal_status TEXT NOT NULL,
            agent_status TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            personal_started_at TEXT,
            personal_closed_at TEXT,
            last_verified_at TEXT,
            last_personal_attach_at TEXT,
            last_agent_attach_at TEXT,
            detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(binding_id) REFERENCES user_environment_bindings(binding_id)
        );

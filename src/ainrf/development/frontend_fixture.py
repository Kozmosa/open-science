from __future__ import annotations

import json
import os
import re
import secrets
from contextlib import closing
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import bcrypt

from ainrf.api.config import hash_api_key
from ainrf.auth.service import AuthService
from ainrf.backup import BackupService
from ainrf.db import connect
from ainrf.db.connection import atomic_write_json
from ainrf.development.frontend_profiles import (
    FRONTEND_DEV_FIXTURE_VERSION,
    FrontendDevProfile,
    FrontendDevUsers,
    normalize_frontend_dev_profile,
    seed_frontend_dev_profile,
)
from ainrf.domain_control import (
    CUTOVER_REQUIRED_PARTICIPANT_TYPES,
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    backup_manifest_sha256,
)
from ainrf.domain_migration import DomainImporter, DomainReconciliationService


_ACTOR_ID = "frontend-dev-fixture"
_PROFILE_MARKER_NAME = "frontend-dev-fixture.json"
_LOGIN_CREDENTIALS_SCHEMA_VERSION = 1
_LOGIN_IDENTITY_SPECS = {
    "owner": {
        "user_id": "frontend-owner-user",
        "username": "frontend-owner",
        "display_name": "Frontend Owner",
        "auth_role": "member",
        "project_role": "owner",
    },
    "editor": {
        "user_id": "frontend-editor-user",
        "username": "frontend-editor",
        "display_name": "Frontend Editor",
        "auth_role": "member",
        "project_role": "editor",
    },
    "viewer": {
        "user_id": "frontend-viewer-user",
        "username": "frontend-viewer",
        "display_name": "Frontend Viewer",
        "auth_role": "member",
        "project_role": "viewer",
    },
    "admin": {
        "user_id": "frontend-admin-user",
        "username": "frontend-admin",
        "display_name": "Frontend Admin",
        "auth_role": "admin",
        "project_role": "admin",
    },
}

DEFAULT_FRONTEND_DEV_API_KEY = "openscience-frontend-dev"
DEFAULT_FRONTEND_DEV_ARTIFACT_SHA = sha256(b"openscience-frontend-dev-fixture-v1").hexdigest()


@dataclass(frozen=True, slots=True)
class FrontendDevFixture:
    state_root: str
    artifact_sha: str
    profile: str
    fixture_version: int
    api_user_id: str
    owner_user_id: str
    login_credentials_path: str
    login_users: dict[str, dict[str, str]]
    project_id: str | None
    primary_workspace_id: str | None
    blocked_workspace_id: str | None
    environment_id: str | None
    counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _assert_safe_state_root(state_root: Path) -> Path:
    resolved = state_root.expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        git_marker = ancestor / ".git"
        if git_marker.is_file() or (git_marker / "HEAD").is_file():
            raise ValueError("frontend dev fixture state must live outside every Git worktree")
    return resolved


def _assert_safe_credentials_path(credentials_path: Path) -> Path:
    resolved = credentials_path.expanduser().resolve()
    for ancestor in (resolved.parent, *resolved.parent.parents):
        git_marker = ancestor / ".git"
        if git_marker.is_file() or (git_marker / "HEAD").is_file():
            raise ValueError("frontend login credentials must live outside every Git worktree")
    return resolved


def _validate_artifact_sha(artifact_sha: str) -> str:
    normalized = artifact_sha.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError("artifact_sha must be a SHA-256 hex digest")
    return normalized


def _enter_fixture_maintenance(maintenance: DomainMaintenanceService) -> None:
    participant_ids: list[str] = []
    for participant_type in CUTOVER_REQUIRED_PARTICIPANT_TYPES:
        participant_id = f"frontend-dev:{participant_type}"
        maintenance.register_participant(participant_id, participant_type)
        participant_ids.append(participant_id)
    maintenance.enter(actor_id=_ACTOR_ID, reason="prepare isolated frontend v2 fixture")
    for participant_id in participant_ids:
        maintenance.drain_participant(participant_id)


def _prepare_cutover(state_root: Path, artifact_sha: str) -> None:
    controller = DomainCutoverController(state_root)
    status = controller.status()
    if status.state != "legacy":
        raise DomainCutoverError("new frontend dev fixture did not start from the legacy state")

    run = DomainImporter(state_root).run(artifact_sha=artifact_sha)
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    now = "2026-07-14T00:00:00+00:00"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, owner_user_id, name, description, status, is_default,
                created_at, updated_at
            ) VALUES (
                'project-frontend-dev', 'api-key-user', 'Frontend Development',
                'Synthetic v2 project for frontend implementation', 'active', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    maintenance = DomainMaintenanceService(state_root)
    _enter_fixture_maintenance(maintenance)
    backup_archive = state_root.with_name(f"{state_root.name}-cutover-backup.tar.gz")
    try:
        controller.finalize_constraints(
            actor_id=_ACTOR_ID,
            run_id=run.run_id,
            stability_window_seconds=0,
        )
        archive = BackupService(state_root).create_backup(backup_archive)
        manifest = BackupService(state_root).verify_backup(archive)
        DomainReconciliationService(state_root).finalize_run(
            run.run_id,
            _ACTOR_ID,
            artifact_sha,
            {
                "manifest_sha256": backup_manifest_sha256(manifest),
                "validated_at": now,
                "status": "valid",
            },
        )
        with closing(connect(db_path)) as conn:
            schema_row = conn.execute(
                "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
            ).fetchone()
        if schema_row is None:
            raise RuntimeError("frontend fixture schema version is unavailable")
        schema_version = int(schema_row[0])
        controller.prepare(
            actor_id=_ACTOR_ID,
            run_id=run.run_id,
            backup_archive=archive,
            artifact_sha=artifact_sha,
            artifact_contract_min=2,
            artifact_contract_max=2,
            artifact_schema_min=schema_version,
            artifact_schema_max=schema_version,
            stability_window_seconds=0,
        )
        controller.commit(
            actor_id=_ACTOR_ID,
            run_id=run.run_id,
            backup_archive=archive,
            artifact_sha=artifact_sha,
            artifact_contract_min=2,
            artifact_contract_max=2,
            artifact_schema_min=schema_version,
            artifact_schema_max=schema_version,
            stability_window_seconds=0,
        )
    finally:
        maintenance.exit(actor_id=_ACTOR_ID)


def _profile_marker_path(state_root: Path) -> Path:
    return state_root / "runtime" / _PROFILE_MARKER_NAME


def _validate_existing_profile(
    state_root: Path,
    *,
    artifact_sha: str,
    profile: FrontendDevProfile,
) -> None:
    marker_path = _profile_marker_path(state_root)
    if not marker_path.is_file():
        raise DomainCutoverError(
            "existing frontend fixture predates profile versioning; reset the managed fixture"
        )
    payload = atomic_read_json(marker_path)
    if payload.get("fixture_version") != FRONTEND_DEV_FIXTURE_VERSION:
        raise DomainCutoverError("frontend fixture version changed; reset the managed fixture")
    if payload.get("profile") != profile.value:
        raise DomainCutoverError("existing frontend fixture uses a different profile")
    if payload.get("artifact_sha") != artifact_sha:
        raise DomainCutoverError(
            "existing frontend fixture uses a different immutable artifact SHA"
        )


def atomic_read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DomainCutoverError("frontend fixture profile marker is malformed")
    return {str(key): value for key, value in payload.items()}


def _write_secret_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{json.dumps(payload, indent=2, sort_keys=True)}\n")
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _new_login_credentials_payload() -> dict[str, object]:
    users: dict[str, dict[str, str]] = {}
    for label, spec in _LOGIN_IDENTITY_SPECS.items():
        users[label] = {
            **spec,
            "password": secrets.token_urlsafe(24),
        }
    return {
        "schema_version": _LOGIN_CREDENTIALS_SCHEMA_VERSION,
        "users": users,
    }


def _validated_login_users(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    if payload.get("schema_version") != _LOGIN_CREDENTIALS_SCHEMA_VERSION:
        raise DomainCutoverError("frontend login credentials version changed; reset the fixture")
    raw_users = payload.get("users")
    if not isinstance(raw_users, dict) or set(raw_users) != set(_LOGIN_IDENTITY_SPECS):
        raise DomainCutoverError("frontend login credentials are malformed; reset the fixture")
    normalized_raw_users: dict[str, object] = {str(key): value for key, value in raw_users.items()}
    users: dict[str, dict[str, str]] = {}
    for label, expected in _LOGIN_IDENTITY_SPECS.items():
        raw_user = normalized_raw_users.get(label)
        if not isinstance(raw_user, dict):
            raise DomainCutoverError("frontend login credentials are malformed; reset the fixture")
        user = {str(key): str(value) for key, value in raw_user.items()}
        if any(user.get(key) != value for key, value in expected.items()):
            raise DomainCutoverError("frontend login identity changed; reset the fixture")
        if not user.get("password"):
            raise DomainCutoverError("frontend login credentials are malformed; reset the fixture")
        users[label] = user
    return users


def _ensure_login_identities(
    auth: AuthService,
    credentials_path: Path,
) -> tuple[FrontendDevUsers, dict[str, dict[str, str]]]:
    auth.initialize()
    with auth._connect() as conn:
        existing_usernames = {
            str(row["username"])
            for row in conn.execute(
                "SELECT username FROM users WHERE username IN (?, ?, ?, ?)",
                tuple(str(spec["username"]) for spec in _LOGIN_IDENTITY_SPECS.values()),
            ).fetchall()
        }
    if credentials_path.exists():
        credentials_path.chmod(0o600)
        users = _validated_login_users(atomic_read_json(credentials_path))
    else:
        if existing_usernames:
            raise DomainCutoverError(
                "frontend login identities exist without credentials; reset the managed fixture"
            )
        payload = _new_login_credentials_payload()
        users = _validated_login_users(payload)
        now = "2026-07-14T00:00:00+00:00"
        with auth._connect() as conn:
            for user in users.values():
                password_hash = bcrypt.hashpw(user["password"].encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    """
                    INSERT INTO users (
                        id, username, password_hash, display_name, role, status,
                        created_at, activated_at, must_change_password
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0)
                    """,
                    (
                        user["user_id"],
                        user["username"],
                        password_hash,
                        user["display_name"],
                        user["auth_role"],
                        now,
                        now,
                    ),
                )
            conn.commit()
        _write_secret_json_atomic(credentials_path, payload)

    with auth._connect() as conn:
        for user in users.values():
            row = conn.execute(
                "SELECT id, password_hash, role, status FROM users WHERE username = ?",
                (user["username"],),
            ).fetchone()
            if (
                row is None
                or str(row["id"]) != user["user_id"]
                or str(row["role"]) != user["auth_role"]
                or str(row["status"]) != "active"
                or not bcrypt.checkpw(user["password"].encode(), str(row["password_hash"]).encode())
            ):
                raise DomainCutoverError(
                    "frontend login identity state does not match credentials; reset the fixture"
                )

    public_users = {
        label: {key: value for key, value in user.items() if key != "password"}
        for label, user in users.items()
    }
    return (
        FrontendDevUsers(
            owner_user_id=users["owner"]["user_id"],
            editor_user_id=users["editor"]["user_id"],
            viewer_user_id=users["viewer"]["user_id"],
            admin_user_id=users["admin"]["user_id"],
        ),
        public_users,
    )


def _seed_fixture(
    state_root: Path,
    artifact_sha: str,
    api_key: str,
    profile: FrontendDevProfile,
    credentials_path: Path,
) -> FrontendDevFixture:
    atomic_write_json(state_root / "config.json", {"api_key_hashes": [hash_api_key(api_key)]})
    auth = AuthService(state_root=state_root)
    users, public_users = _ensure_login_identities(auth, credentials_path)
    seeded = seed_frontend_dev_profile(
        state_root,
        artifact_sha=artifact_sha,
        profile=profile,
        users=users,
    )
    atomic_write_json(
        _profile_marker_path(state_root),
        {
            "artifact_sha": artifact_sha,
            "fixture_version": FRONTEND_DEV_FIXTURE_VERSION,
            "profile": profile.value,
        },
    )
    return FrontendDevFixture(
        state_root=str(state_root),
        artifact_sha=artifact_sha,
        profile=profile.value,
        fixture_version=FRONTEND_DEV_FIXTURE_VERSION,
        api_user_id="api-key-user",
        owner_user_id=users.owner_user_id,
        login_credentials_path=str(credentials_path),
        login_users=public_users,
        project_id=seeded.project_id,
        primary_workspace_id=seeded.primary_workspace_id,
        blocked_workspace_id=seeded.blocked_workspace_id,
        environment_id=seeded.environment_id,
        counts=seeded.counts,
    )


def prepare_frontend_dev_fixture(
    state_root: Path,
    *,
    artifact_sha: str,
    api_key: str,
    profile: FrontendDevProfile | str = FrontendDevProfile.FULL,
    credentials_path: Path | None = None,
) -> FrontendDevFixture:
    """Prepare an isolated, synthetic, committed-v2 state for frontend work."""

    if not api_key.strip():
        raise ValueError("api_key is required")
    resolved_state_root = _assert_safe_state_root(state_root)
    resolved_credentials_path = _assert_safe_credentials_path(
        credentials_path
        if credentials_path is not None
        else resolved_state_root / "runtime" / "frontend-login-identities.json"
    )
    normalized_artifact_sha = _validate_artifact_sha(artifact_sha)
    normalized_profile = normalize_frontend_dev_profile(profile)
    state_exists = resolved_state_root.exists() and any(resolved_state_root.iterdir())
    resolved_state_root.mkdir(parents=True, exist_ok=True)
    if state_exists:
        status = DomainCutoverController(resolved_state_root).status()
        if status.state != "v2":
            raise DomainCutoverError(
                "frontend dev fixture refuses to reuse a non-empty or partially prepared state root"
            )
        if status.artifact_sha != normalized_artifact_sha:
            raise DomainCutoverError(
                "existing frontend fixture uses a different immutable artifact SHA"
            )
        _validate_existing_profile(
            resolved_state_root,
            artifact_sha=normalized_artifact_sha,
            profile=normalized_profile,
        )
    else:
        _prepare_cutover(resolved_state_root, normalized_artifact_sha)
    return _seed_fixture(
        resolved_state_root,
        normalized_artifact_sha,
        api_key.strip(),
        normalized_profile,
        resolved_credentials_path,
    )

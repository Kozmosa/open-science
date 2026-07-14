from __future__ import annotations

import re
from contextlib import closing
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from ainrf.api.config import hash_api_key
from ainrf.auth.service import AuthService
from ainrf.backup import BackupService
from ainrf.db import connect
from ainrf.db.connection import atomic_write_json
from ainrf.domain import DomainService, ProjectContextService
from ainrf.domain_control import (
    CUTOVER_REQUIRED_PARTICIPANT_TYPES,
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    backup_manifest_sha256,
)
from ainrf.domain_migration import DomainImporter, DomainReconciliationService


_ACTOR_ID = "frontend-dev-fixture"
_API_USER: dict[str, object] = {"id": "api-key-user", "role": "user"}
_ADMIN: dict[str, object] = {"id": "frontend-dev-admin", "role": "admin"}

DEFAULT_FRONTEND_DEV_API_KEY = "openscience-frontend-dev"
DEFAULT_FRONTEND_DEV_ARTIFACT_SHA = sha256(b"openscience-frontend-dev-fixture-v1").hexdigest()


@dataclass(frozen=True, slots=True)
class FrontendDevFixture:
    state_root: str
    artifact_sha: str
    api_user_id: str
    project_id: str
    primary_workspace_id: str
    blocked_workspace_id: str
    environment_id: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _assert_safe_state_root(state_root: Path) -> Path:
    resolved = state_root.expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        git_marker = ancestor / ".git"
        if git_marker.is_file() or (git_marker / "HEAD").is_file():
            raise ValueError("frontend dev fixture state must live outside every Git worktree")
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


def _seed_fixture(state_root: Path, artifact_sha: str, api_key: str) -> FrontendDevFixture:
    atomic_write_json(state_root / "config.json", {"api_key_hashes": [hash_api_key(api_key)]})
    auth = AuthService(state_root=state_root)
    auth.initialize()
    domain = DomainService(state_root, artifact_sha=artifact_sha)

    workspace_root = state_root.parent / f"{state_root.name}-workspaces"
    primary_path = workspace_root / "primary"
    blocked_path = workspace_root / "blocked"
    primary_path.mkdir(parents=True, exist_ok=True)
    blocked_path.mkdir(parents=True, exist_ok=True)

    environment = domain.create_environment(
        _ADMIN,
        alias="frontend-dev-local",
        display_name="Frontend Dev Local",
        description="Synthetic local Environment for frontend implementation",
        connection={"host": "127.0.0.1", "default_workdir": str(workspace_root)},
        idempotency_key="frontend-dev-environment",
    )
    environment_id = str(environment["environment_id"])
    auth.grant_environment(
        env_id=environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by=_ACTOR_ID,
        reason="frontend development fixture",
    )

    project_id = "project-frontend-dev"
    primary_workspace = domain.create_workspace(
        _API_USER,
        environment_id=environment_id,
        canonical_path=str(primary_path),
        label="Primary frontend workspace",
        description="Executable synthetic Workspace",
        workspace_prompt="Use this synthetic Workspace for frontend development.",
        idempotency_key="frontend-dev-primary-workspace",
    )
    primary_workspace_id = str(primary_workspace["workspace_id"])
    domain.attach_workspace(
        project_id,
        primary_workspace_id,
        _API_USER,
        idempotency_key="frontend-dev-primary-link",
    )
    domain.set_primary_workspace(
        project_id,
        primary_workspace_id,
        _API_USER,
        idempotency_key="frontend-dev-primary-selection",
    )

    blocked_environment = domain.create_environment(
        _ADMIN,
        alias="frontend-dev-blocked",
        display_name="Frontend Dev Blocked",
        description="Synthetic Environment used to exercise permission states",
        connection={"host": "127.0.0.1", "default_workdir": str(blocked_path)},
        idempotency_key="frontend-dev-blocked-environment",
    )
    blocked_environment_id = str(blocked_environment["environment_id"])
    auth.grant_environment(
        env_id=blocked_environment_id,
        user_id="api-key-user",
        max_tasks=None,
        granted_by=_ACTOR_ID,
        reason="create the blocked frontend fixture Workspace",
    )
    blocked_workspace = domain.create_workspace(
        _API_USER,
        environment_id=blocked_environment_id,
        canonical_path=str(blocked_path),
        label="Unavailable frontend workspace",
        description="Synthetic Workspace with a revoked Environment grant",
        idempotency_key="frontend-dev-blocked-workspace",
    )
    blocked_workspace_id = str(blocked_workspace["workspace_id"])
    domain.attach_workspace(
        project_id,
        blocked_workspace_id,
        _API_USER,
        idempotency_key="frontend-dev-blocked-link",
    )
    auth.revoke_environment(
        blocked_environment_id,
        "api-key-user",
        revoked_by=_ACTOR_ID,
        reason="exercise the linked-but-not-executable frontend state",
    )

    domain.create_project(
        _API_USER,
        name="Frontend Needs Workspace",
        description="Synthetic attention state without a Workspace",
        idempotency_key="frontend-dev-empty-project",
    )
    context = ProjectContextService(state_root, artifact_sha=artifact_sha)
    context.save_draft(
        project_id,
        "Synthetic Project Context for the frontend phase worktree.",
        _API_USER,
        idempotency_key="frontend-dev-context-draft",
    )
    context.publish(
        project_id,
        _API_USER,
        idempotency_key="frontend-dev-context-publish",
    )
    return FrontendDevFixture(
        state_root=str(state_root),
        artifact_sha=artifact_sha,
        api_user_id="api-key-user",
        project_id=project_id,
        primary_workspace_id=primary_workspace_id,
        blocked_workspace_id=blocked_workspace_id,
        environment_id=environment_id,
    )


def prepare_frontend_dev_fixture(
    state_root: Path, *, artifact_sha: str, api_key: str
) -> FrontendDevFixture:
    """Prepare an isolated, synthetic, committed-v2 state for frontend work."""

    if not api_key.strip():
        raise ValueError("api_key is required")
    resolved_state_root = _assert_safe_state_root(state_root)
    normalized_artifact_sha = _validate_artifact_sha(artifact_sha)
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
    else:
        _prepare_cutover(resolved_state_root, normalized_artifact_sha)
    return _seed_fixture(resolved_state_root, normalized_artifact_sha, api_key.strip())

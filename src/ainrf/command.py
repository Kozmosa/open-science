from __future__ import annotations

import asyncio
import json as json_mod
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from ainrf import __version__
from ainrf.onboarding import (
    load_runtime_config,
    run_onboarding,
    save_runtime_config,
)
from ainrf.runtime import normalize_runtime_config
from ainrf.runtime.container_profile import (
    ParsedSSHCommand,
    build_container_profile,
    parse_ssh_command,
)
from ainrf.state import default_state_root
from ainrf.backup.service import BackupService
from ainrf.db.retire_legacy import migrate as retire_legacy_migrate
from ainrf.db.retire_legacy import preflight as retire_legacy_preflight
from ainrf.db.retire_legacy import verify as retire_legacy_verify
from ainrf.domain_control import (
    REQUIRED_PARTICIPANT_TYPES,
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceLease,
    MaintenanceModeError,
)
from ainrf.domain_migration import LegacyDomainRecordAuditService
from ainrf.domain import OverviewSnapshotPlanner
from ainrf.domain.write_fence import DomainWriteFenceError
from ainrf.development import (
    DEFAULT_FRONTEND_DEV_API_KEY,
    DEFAULT_FRONTEND_DEV_ARTIFACT_SHA,
    FrontendFixtureWorker,
    FrontendDevFaultProfile,
    FrontendDevProfile,
    prepare_frontend_dev_fixture,
)
from ainrf.logging import configure_cli_logging


app = typer.Typer(
    add_completion=False,
    help="OpenScience daemon-oriented runtime CLI.",
    no_args_is_help=True,
)

container_app = typer.Typer(help="Manage reusable container profiles.")
app.add_typer(container_app, name="container")

backup_app = typer.Typer(help="Backup and restore OpenScience data.")
app.add_typer(backup_app, name="backup")

domain_maintenance_app = typer.Typer(help="Manage the persistent domain migration write barrier.")
app.add_typer(domain_maintenance_app, name="domain-maintenance")

domain_migration_app = typer.Typer(help="Inspect retired domain records (read-only audit).")
app.add_typer(domain_migration_app, name="domain-migration")

migration_app = typer.Typer(help="Run explicit one-time schema migrations.")
app.add_typer(migration_app, name="migration")


overview_snapshot_app = typer.Typer(help="Refresh persisted control-plane overview snapshots.")
app.add_typer(overview_snapshot_app, name="overview-snapshot")

frontend_dev_app = typer.Typer(help="Prepare isolated synthetic state for frontend development.")
app.add_typer(frontend_dev_app, name="frontend-dev")

_TOKEN_FILE = Path.home() / ".ainrf" / "token"


def version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(f"ainrf {__version__}")
    raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the installed ainrf version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    configure_cli_logging()
    _ = version


@app.command()
def onboard(
    state_root: Annotated[
        Path,
        typer.Option(help="State root where OpenScience config will be initialized."),
    ] = default_state_root(),
) -> None:
    run_onboarding(state_root)


@app.command("domain-worker")
def domain_worker(
    state_root: Annotated[
        Path,
        typer.Option(help="State root shared by the API and durable domain worker."),
    ] = default_state_root(),
    once: Annotated[
        bool,
        typer.Option(help="Claim and dispatch at most one durable Task, then exit."),
    ] = False,
) -> None:
    """Run the no-port durable Conversation dispatcher."""
    from ainrf.domain.conversation_worker import ConversationDispatcher

    try:
        artifact_sha = _domain_worker_artifact_sha(state_root)
    except DomainWriteFenceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if artifact_sha is None:
        typer.echo(
            "domain worker is unavailable until an immutable domain artifact is configured",
            err=True,
        )
        raise typer.Exit(code=2)
    dispatcher = ConversationDispatcher(
        state_root,
        artifact_sha=artifact_sha,
    )
    if once:
        processed = asyncio.run(dispatcher.run_once())
        typer.echo(json_mod.dumps({"outcome": "completed" if processed else "idle"}, indent=2))
        return

    async def run_forever() -> None:
        while True:
            await dispatcher.run_once()
            await asyncio.sleep(0.1)

    asyncio.run(run_forever())


@frontend_dev_app.command("prepare")
def frontend_dev_prepare(
    state_root: Annotated[
        Path,
        typer.Option(help="Isolated state root outside every Git worktree."),
    ] = Path("/tmp/openscience-frontend-dev"),
    api_key: Annotated[
        str,
        typer.Option(help="Local API key injected by the Vite development proxy."),
    ] = DEFAULT_FRONTEND_DEV_API_KEY,
    credentials_path: Annotated[
        Path | None,
        typer.Option(help="Repo-external JSON file for generated browser login identities."),
    ] = None,
    artifact_sha: Annotated[
        str,
        typer.Option(help="Synthetic immutable artifact SHA bound to the v2 fixture."),
    ] = DEFAULT_FRONTEND_DEV_ARTIFACT_SHA,
    profile: Annotated[
        FrontendDevProfile,
        typer.Option(help="Deterministic frontend state profile to prepare."),
    ] = FrontendDevProfile.FULL,
    fault_profile: Annotated[
        FrontendDevFaultProfile,
        typer.Option(help="Deterministic API fault profile for the managed fixture."),
    ] = FrontendDevFaultProfile.NONE,
) -> None:
    """Create or reconcile a synthetic committed-v2 frontend fixture."""

    try:
        fixture = prepare_frontend_dev_fixture(
            state_root,
            artifact_sha=artifact_sha,
            api_key=api_key,
            profile=profile,
            credentials_path=credentials_path,
            fault_profile=fault_profile,
        )
    except (DomainWriteFenceError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(fixture.as_dict(), indent=2, sort_keys=True))


@frontend_dev_app.command("worker")
def frontend_dev_worker(
    state_root: Annotated[
        Path,
        typer.Option(help="Managed synthetic frontend fixture state root."),
    ] = Path("/tmp/openscience-frontend-dev"),
    artifact_sha: Annotated[
        str,
        typer.Option(help="Synthetic immutable artifact SHA bound to the v2 fixture."),
    ] = DEFAULT_FRONTEND_DEV_ARTIFACT_SHA,
    once: Annotated[
        bool,
        typer.Option(help="Process one bounded fixture worker cycle, then exit."),
    ] = False,
    poll_seconds: Annotated[
        float,
        typer.Option(help="Polling interval for deterministic local work."),
    ] = 0.25,
) -> None:
    """Run the marker-guarded worker without external runtime or provider calls."""

    try:
        worker = FrontendFixtureWorker(state_root, artifact_sha=artifact_sha)
        if once:
            result = asyncio.run(worker.run_once())
            worker.stop()
            typer.echo(json_mod.dumps(result.as_dict(), indent=2, sort_keys=True))
            return
        asyncio.run(worker.run_forever(poll_seconds=poll_seconds))
    except (DomainWriteFenceError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


def _domain_worker_artifact_sha(state_root: Path) -> str:
    """Return the immutable artifact identity for a current worker."""

    _ = state_root
    artifact_sha = os.environ.get(
        "AINRF_DOMAIN_ARTIFACT_SHA", os.environ.get("OPENSCIENCE_DOMAIN_ARTIFACT_SHA", "")
    ).strip()
    if not artifact_sha:
        raise DomainWriteFenceError("AINRF_DOMAIN_ARTIFACT_SHA is required for domain worker")
    return artifact_sha


@container_app.command("add")
def container_add(
    state_root: Annotated[
        Path,
        typer.Option(help="State root where container profiles are stored."),
    ] = default_state_root(),
    name: Annotated[
        str,
        typer.Option(help="Profile name used for lookup.", prompt="Container profile name"),
    ] = "default",
    ssh_command: Annotated[
        str,
        typer.Option(
            "--ssh",
            help="SSH command, e.g. ssh -p 22 user@host -i ~/.ssh/id_rsa",
            prompt="SSH command",
        ),
    ] = "",
    project_dir: Annotated[
        str,
        typer.Option(
            help="Remote project directory used by OpenScience.",
            prompt="Remote project directory",
        ),
    ] = "/workspace/projects",
    password: Annotated[
        str,
        typer.Option(
            help="SSH password (optional; leave empty when key-based auth is used).",
            prompt="SSH password (optional)",
            hide_input=True,
            confirmation_prompt=False,
        ),
    ] = "",
    set_default: Annotated[
        bool,
        typer.Option(help="Set this profile as the default container profile."),
    ] = True,
) -> None:
    profile_name, profile = build_container_profile(name, ssh_command, project_dir, password)
    config_path = state_root / "config.json"
    payload = normalize_runtime_config(load_runtime_config(config_path))
    profiles = payload.get("container_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    profiles[profile_name] = profile
    payload["container_profiles"] = profiles
    if set_default:
        payload["default_container_profile"] = profile_name
    save_runtime_config(config_path, payload)
    typer.echo(
        f"Saved container profile `{profile_name}` -> {profile['user']}@{profile['host']}:{profile['port']} "
        f"(project_dir={project_dir})"
    )


@app.command()
def login(
    server: Annotated[
        str, typer.Option("--server", help="OpenScience server URL")
    ] = "http://localhost:8000",
) -> None:
    """Log in to OpenScience and cache the token locally."""
    import getpass

    import requests

    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    try:
        resp = requests.post(
            f"{server}/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Login failed: {exc}")
        raise typer.Exit(code=1)

    data = resp.json()
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(
        json_mod.dumps(
            {
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
            }
        )
    )
    user = data["user"]
    print(f"Logged in as {user['username']} ({user['role']}). Token saved.")


@backup_app.command("create")
def backup_create(
    output: Annotated[
        Path | None,
        typer.Option(help="Output path (file or directory). Default: ./ainrf-backup-<ts>.tar.gz"),
    ] = None,
    state_root: Annotated[
        Path,
        typer.Option(help="State root to back up."),
    ] = default_state_root(),
    include_workspaces: Annotated[
        bool,
        typer.Option(help="Include workspace files (can be large)."),
    ] = False,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Workspace root (default: ~/.ainrf_workspaces)."),
    ] = None,
    include_tenants: Annotated[
        bool,
        typer.Option(help="Include tenant home directories (can be large)."),
    ] = False,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Tenant home root (default: /home/ainrf_tenants)."),
    ] = None,
) -> None:
    """Create a backup archive of OpenScience databases and config."""
    svc = BackupService(state_root)
    ws = workspace_root or (Path.home() / ".ainrf_workspaces") if include_workspaces else None
    tr = tenant_root or Path("/home/ainrf_tenants") if include_tenants else None
    path = svc.create_backup(
        output,
        include_workspaces=include_workspaces,
        include_tenants=include_tenants,
        workspace_root=ws,
        tenant_root=tr,
    )
    typer.echo(f"Backup created: {path}")


@backup_app.command("restore")
def backup_restore(
    archive: Annotated[
        Path,
        typer.Argument(help="Backup archive to restore."),
    ],
    staged_state_root: Annotated[
        Path,
        typer.Option(help="New staged state root. It must not already exist."),
    ],
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Target workspace root (required if archive includes workspaces)."),
    ] = None,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Target tenant root (required if archive includes tenants)."),
    ] = None,
    skip_pre_backup: Annotated[
        bool,
        typer.Option(help="Skip the automatic pre-restore safety backup."),
    ] = False,
) -> None:
    """Restore OpenScience state into a new staged root.

    The active state root is not overwritten. After services are stopped or
    in maintenance, use ``backup promote-generation`` with an explicit active
    state symlink to atomically select this verified generation.
    """
    svc = BackupService(default_state_root())
    restored_root = svc.restore_backup(
        archive,
        target_state_root=staged_state_root,
        target_workspace_root=workspace_root,
        target_tenant_root=tenant_root,
        skip_pre_backup=skip_pre_backup,
    )
    typer.echo(f"Restore staged and verified: {restored_root}")


@backup_app.command("promote-generation")
def backup_promote_generation(
    generation_state_root: Annotated[
        Path,
        typer.Argument(help="Verified staged state root returned by backup restore."),
    ],
    active_state_pointer: Annotated[
        Path,
        typer.Option(
            help="Symlink used as AINRF_STATE_ROOT; atomically repointed to the staged generation."
        ),
    ],
    maintenance_state_root: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Current active state root that owns the validated maintenance epoch. "
                "Defaults to the active-state-pointer target."
            )
        ),
    ] = None,
    maintenance_stability_window_seconds: Annotated[
        float,
        typer.Option(
            min=0.0,
            help="Required stable-source window for the active maintenance preflight.",
        ),
    ] = 5.0,
    confirm_active_switch: Annotated[
        bool,
        typer.Option(
            "--confirm-active-switch",
            help="Required acknowledgement before the verified maintenance-gated switch.",
        ),
    ] = False,
) -> None:
    """Atomically point a stopped runtime at one verified restored generation.

    This command does not merge, promote, or otherwise alter any explicitly
    restored workspace or tenant tree.  Inspect its high-risk restore report
    before a separate deployment-level volume/directory decision. Both the
    current active root and the staged generation must already be in a valid
    maintenance epoch; enter maintenance on the staged root explicitly before
    running this command.
    """

    if not confirm_active_switch:
        raise typer.BadParameter(
            "pass --confirm-active-switch only after services are stopped or in maintenance"
        )
    try:
        result = BackupService(generation_state_root).promote_restored_generation(
            generation_state_root,
            active_state_pointer=active_state_pointer,
            maintenance_state_root=maintenance_state_root,
            maintenance_stability_window_seconds=maintenance_stability_window_seconds,
        )
    except (MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"Active state generation switched: {result.active_pointer} -> {result.generation_root}"
    )


@backup_app.command("verify")
def backup_verify(
    archive: Annotated[
        Path,
        typer.Argument(help="Backup archive to verify."),
    ],
) -> None:
    """Verify integrity of a backup archive."""
    svc = BackupService(Path("/dummy"))  # state_root unused for verify
    manifest = svc.verify_backup(archive)
    typer.echo(f"Archive valid (version {manifest.version}, created {manifest.created_at})")
    typer.echo(f"  Databases: {len(manifest.databases)}")
    typer.echo(f"  Config files: {len(manifest.config_files)}")
    if manifest.includes_workspaces:
        typer.echo("  Includes: workspaces")
    if manifest.includes_tenants:
        typer.echo("  Includes: tenants")


def _maintenance_service(
    state_root: Path,
    *,
    workspace_root: Path | None = None,
    tenant_root: Path | None = None,
) -> DomainMaintenanceService:
    service = DomainMaintenanceService(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )
    service.initialize()
    return service


def _admin_cli_participant(
    state_root: Path,
    command: str,
    *,
    maintenance: DomainMaintenanceService | None = None,
) -> DomainWriteParticipant:
    """Register the command process before it touches domain control state."""

    maintenance = maintenance or _maintenance_service(state_root)
    participant = DomainWriteParticipant(
        maintenance,
        "admin-cli",
        details={"command": command},
    )
    participant.start()
    # A preflight/prepare process is itself a registered writer role.  During
    # maintenance it performs only read-only safety work, so explicitly
    # acknowledge the current epoch as drained before that same preflight
    # evaluates the complete participant set.
    participant.drain()
    return participant


@contextmanager
def _admin_cli_mutation(
    state_root: Path,
    command: str,
) -> Iterator[tuple[DomainMaintenanceService, MaintenanceLease]]:
    """Own one maintenance lease for a CLI command's complete write transaction."""

    maintenance = _maintenance_service(state_root)
    participant = _admin_cli_participant(state_root, command, maintenance=maintenance)
    lease: MaintenanceLease | None = None
    try:
        lease = participant.begin_mutation(source=command)
        participant.check_lease(lease)
        yield maintenance, lease
        participant.check_lease(lease)
    except MaintenanceModeError:
        participant.drain()
        raise
    finally:
        if lease is not None:
            participant.finish_mutation(lease)
        participant.stop()


@domain_maintenance_app.command("status")
def domain_maintenance_status(
    state_root: Annotated[
        Path, typer.Option(help="State root containing the control database.")
    ] = default_state_root(),
) -> None:
    status = _maintenance_service(state_root).status()
    typer.echo(
        f"epoch={status.maintenance_epoch} active={status.is_active} "
        f"in_flight={status.in_flight_mutations}"
    )


@domain_maintenance_app.command("enter")
def domain_maintenance_enter(
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in the maintenance state.")],
    reason: Annotated[str, typer.Option(help="Reason recorded in the maintenance audit state.")],
    timeout_seconds: Annotated[
        float, typer.Option(min=0.0, help="Seconds to wait for in-flight writes.")
    ] = 30.0,
    state_root: Annotated[
        Path, typer.Option(help="State root containing the control database.")
    ] = default_state_root(),
) -> None:
    service = _maintenance_service(state_root)
    try:
        status = service.enter(actor_id=actor_id, reason=reason)
        if not service.wait_for_drain(timeout_seconds=timeout_seconds):
            raise typer.Exit(code=2)
    except MaintenanceModeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"maintenance entered at epoch {status.maintenance_epoch}")


@domain_maintenance_app.command("exit")
def domain_maintenance_exit(
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded when maintenance ends.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing the control database.")
    ] = default_state_root(),
) -> None:
    try:
        status = _maintenance_service(state_root).exit(actor_id=actor_id)
    except MaintenanceModeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"maintenance exited at epoch {status.maintenance_epoch}")


@domain_maintenance_app.command("preflight")
def domain_maintenance_preflight(
    required_participant_type: Annotated[
        list[str],
        typer.Option(
            "--require-participant",
            help="Participant type that must be freshly heartbeating and drained.",
        ),
    ] = [],
    stability_window_seconds: Annotated[
        float,
        typer.Option(min=0.0, help="Seconds during which source content must remain stable."),
    ] = 5.0,
    stale_after_seconds: Annotated[
        float,
        typer.Option(min=0.1, help="Maximum age of a required participant heartbeat."),
    ] = 30.0,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Explicit Workspace tree selected for backup/cutover stability proof."),
    ] = None,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Explicit tenant tree selected for backup/cutover stability proof."),
    ] = None,
    state_root: Annotated[
        Path, typer.Option(help="State root containing the control database.")
    ] = default_state_root(),
) -> None:
    """Report the hard migration/cutover safety gates without changing state."""
    service = _maintenance_service(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )
    participant = _admin_cli_participant(
        state_root,
        "domain-maintenance.preflight",
        maintenance=service,
    )
    try:
        required_types = tuple(
            dict.fromkeys(REQUIRED_PARTICIPANT_TYPES + tuple(required_participant_type))
        )
        report = service.preflight(
            required_participant_types=required_types,
            stability_window_seconds=stability_window_seconds,
            stale_after_seconds=stale_after_seconds,
        )
    finally:
        participant.stop()
    typer.echo(json_mod.dumps(asdict(report), indent=2))
    if not report.ready:
        raise typer.Exit(code=2)


@domain_migration_app.command("records")
def domain_migration_records(
    run_id: Annotated[
        str | None, typer.Option(help="Optional historical migration run ID.")
    ] = None,
    record_type: Annotated[
        str | None, typer.Option(help="Optional historical record type.")
    ] = None,
    cursor: Annotated[str | None, typer.Option(help="Opaque pagination cursor.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
    state_root: Annotated[
        Path, typer.Option(help="State root containing read-only legacy audit evidence.")
    ] = default_state_root(),
) -> None:
    """List immutable historical records; this command cannot mutate migration state."""
    service = LegacyDomainRecordAuditService(state_root)
    records, has_more, next_cursor = service.list_records(
        run_id=run_id,
        record_type=record_type,
        cursor=cursor,
        limit=limit,
    )
    typer.echo(
        json_mod.dumps(
            {"items": records, "has_more": has_more, "next_cursor": next_cursor}, indent=2
        )
    )


@domain_migration_app.command("record")
def domain_migration_record(
    legacy_record_id: Annotated[str, typer.Argument(help="Historical record ID to inspect.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing read-only legacy audit evidence.")
    ] = default_state_root(),
) -> None:
    """Inspect one immutable historical record with credential redaction."""
    try:
        result = LegacyDomainRecordAuditService(state_root).inspect_record(legacy_record_id)
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result, indent=2))


retire_legacy_app = typer.Typer(help="Run the one-time pre-baseline schema retirement.")
migration_app.add_typer(retire_legacy_app, name="retire-legacy")


@retire_legacy_app.command("preflight")
def retire_legacy_preflight_command(
    state_root: Annotated[Path, typer.Option(help="State root to inspect.")] = default_state_root(),
) -> None:
    """Report whether the explicit retirement migration is safe to run."""
    report = retire_legacy_preflight(state_root)
    typer.echo(json_mod.dumps(report.as_dict(), indent=2))
    if not report.ready:
        raise typer.Exit(code=2)


@retire_legacy_app.command("apply")
def retire_legacy_apply_command(
    state_root: Annotated[Path, typer.Option(help="State root to migrate.")] = default_state_root(),
) -> None:
    """Apply the one-time retirement after the operator has verified the preflight."""
    try:
        report = retire_legacy_migrate(state_root)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(report.as_dict(), indent=2))
    if not report.ready:
        raise typer.Exit(code=2)


@retire_legacy_app.command("verify")
def retire_legacy_verify_command(
    state_root: Annotated[
        Path, typer.Option(help="State root to validate.")
    ] = default_state_root(),
) -> None:
    """Validate the current baseline and absence of retired tables."""
    report = retire_legacy_verify(state_root)
    typer.echo(json_mod.dumps(report.as_dict(), indent=2))
    if not report.ready:
        raise typer.Exit(code=2)


@overview_snapshot_app.command("refresh")
def overview_snapshot_refresh(
    user_id: Annotated[str, typer.Option(help="Owner user ID for the persisted overview.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing the control plane.")
    ] = default_state_root(),
) -> None:
    """Refresh one user's snapshot through the planner participant."""

    planner: OverviewSnapshotPlanner | None = None
    try:
        artifact_sha = _domain_worker_artifact_sha(state_root)
        if artifact_sha is None:
            raise DomainWriteFenceError(
                "overview snapshot refresh requires a committed domain v2 artifact"
            )
        planner = OverviewSnapshotPlanner(
            state_root,
            artifact_sha=artifact_sha,
            active_user_ids=lambda: (),
        )
        job = planner.request_refresh(user_id)
        result = planner.run_job(str(job["job_id"]))
        snapshot = planner.service.latest(user_id)
        if snapshot is None:
            detail = result.detail or "overview refresh did not produce a snapshot"
            typer.echo(detail, err=True)
            raise typer.Exit(code=2)
        typer.echo(json_mod.dumps(snapshot, indent=2))
    except (DomainWriteFenceError, MaintenanceModeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        if planner is not None:
            planner.stop()


def _parse_ssh_command(command: str) -> ParsedSSHCommand:
    try:
        return parse_ssh_command(command)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

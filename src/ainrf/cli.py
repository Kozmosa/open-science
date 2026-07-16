from __future__ import annotations

import asyncio
import json as json_mod
import os
import shlex
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from ainrf import __version__
from ainrf.auth.service import AuthService
from ainrf.onboarding import (
    config_path_for,
    ensure_interactive_onboarding_available,
    load_runtime_config,
    onboard_state_root,
    run_onboarding,
    save_runtime_config,
)
from ainrf.server import run_server, run_server_daemon, stop_server_daemon
from ainrf.runtime import normalize_runtime_config
from ainrf.state import default_state_root
from ainrf.backup.service import BackupService
from ainrf.domain_control import (
    CUTOVER_REQUIRED_PARTICIPANT_TYPES,
    DomainCutoverController,
    DomainCutoverError,
    DomainMaintenanceService,
    DomainModelMode,
    DomainWriteParticipant,
    MaintenanceLease,
    MaintenanceModeError,
)
from ainrf.domain_migration import (
    DomainImporter,
    DomainReconciliationService,
    capture_source_manifest,
)
from ainrf.domain import OverviewSnapshotPlanner, TaskApplicationService, TaskDispatcher
from ainrf.development import (
    DEFAULT_FRONTEND_DEV_API_KEY,
    DEFAULT_FRONTEND_DEV_ARTIFACT_SHA,
    FrontendFixtureWorker,
    FrontendDevProfile,
    prepare_frontend_dev_fixture,
)
from ainrf.literature.planner import run_once as run_literature_planner_once
from ainrf.literature.tracking import LiteratureTrackingService
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

domain_migration_app = typer.Typer(help="Inspect legacy sources before domain-model migration.")
app.add_typer(domain_migration_app, name="domain-migration")

domain_cutover_app = typer.Typer(help="Prepare and commit the durable domain v2 cutover fuse.")
app.add_typer(domain_cutover_app, name="domain-cutover")

domain_runtime_app = typer.Typer(help="Reconcile durable runtime boundaries without relaunching.")
app.add_typer(domain_runtime_app, name="domain-runtime")

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


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host for the API server.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the API server.")] = 8000,
    workers: Annotated[int, typer.Option(help="Number of uvicorn worker processes.")] = 1,
    daemon: Annotated[bool, typer.Option(help="Run the API server in the background.")] = False,
    state_root: Annotated[
        Path,
        typer.Option(help="State root for API configuration and daemon runtime files."),
    ] = default_state_root(),
    pid_file: Annotated[
        Path | None,
        typer.Option(help="Optional pid file path for daemon mode."),
    ] = None,
    log_file: Annotated[
        Path | None,
        typer.Option(help="Optional log file path for daemon mode."),
    ] = None,
) -> None:
    _ensure_api_key_hashes_configured(state_root)
    if daemon:
        runtime_dir = state_root / "runtime"
        resolved_pid_file = pid_file or runtime_dir / "ainrf-api.pid"
        resolved_log_file = log_file or runtime_dir / "ainrf-api.log"
        daemon_pid = run_server_daemon(host, port, state_root, resolved_pid_file, resolved_log_file)
        typer.echo(f"OpenScience API daemon started (pid={daemon_pid}, port={port})")
        return
    run_server(host, port, state_root, workers=workers)


@app.command("literature-planner")
def literature_planner(
    state_root: Annotated[
        Path,
        typer.Option(help="State root shared by the API, literature planner, and worker."),
    ] = default_state_root(),
    once: Annotated[
        bool,
        typer.Option(help="Publish pending durable literature work once and exit."),
    ] = False,
) -> None:
    """Run the durable literature planner/outbox dispatcher."""
    _require_legacy_literature_planner(state_root)
    service = LiteratureTrackingService(state_root)
    if once:
        typer.echo(f"Published {run_literature_planner_once(service)} literature work item(s).")
        return
    from ainrf.literature.planner import run_forever

    run_forever(service)


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
    """Run the no-port durable Task dispatcher."""
    try:
        artifact_sha = _domain_worker_artifact_sha(state_root)
    except DomainCutoverError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if artifact_sha is None:
        typer.echo(
            "domain worker is unavailable until the domain v2 cutover is committed",
            err=True,
        )
        raise typer.Exit(code=2)
    dispatcher = TaskDispatcher(state_root, artifact_sha=artifact_sha)
    try:
        if once:
            result = asyncio.run(dispatcher.run_once())
            typer.echo(json_mod.dumps(asdict(result), indent=2))
            return
        asyncio.run(dispatcher.run_forever())
    finally:
        dispatcher.stop()


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
) -> None:
    """Create or reconcile a synthetic committed-v2 frontend fixture."""

    try:
        fixture = prepare_frontend_dev_fixture(
            state_root,
            artifact_sha=artifact_sha,
            api_key=api_key,
            profile=profile,
            credentials_path=credentials_path,
        )
    except (DomainCutoverError, OSError, ValueError) as exc:
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
    except (DomainCutoverError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


def _configured_domain_mode() -> DomainModelMode:
    raw = (
        os.environ.get(
            "OPENSCIENCE_DOMAIN_MODEL_MODE",
            os.environ.get("AINRF_DOMAIN_MODEL_MODE", DomainModelMode.LEGACY.value),
        )
        .strip()
        .lower()
    )
    try:
        return DomainModelMode(raw)
    except ValueError as exc:
        raise DomainCutoverError("invalid OPENSCIENCE_DOMAIN_MODEL_MODE for domain worker") from exc


def _domain_worker_artifact_sha(state_root: Path) -> str | None:
    """Return the exact v2 artifact only when both config and DB fuse agree."""

    controller = _cutover_controller(state_root)
    status = controller.status()
    mode = _configured_domain_mode()
    if status.state == "legacy":
        if mode is DomainModelMode.V2:
            raise DomainCutoverError("v2 domain worker cannot start before cutover commit")
        return None
    if status.state != "v2":
        raise DomainCutoverError("domain worker cannot start while cutover is prepared")
    if mode is not DomainModelMode.V2:
        raise DomainCutoverError("legacy/validate domain worker cannot open committed v2 state")
    artifact_sha = os.environ.get(
        "OPENSCIENCE_DOMAIN_ARTIFACT_SHA", os.environ.get("AINRF_DOMAIN_ARTIFACT_SHA", "")
    ).strip()
    if not artifact_sha:
        raise DomainCutoverError("OPENSCIENCE_DOMAIN_ARTIFACT_SHA is required for v2 domain worker")
    controller.assert_v2_writable(artifact_sha=artifact_sha)
    return artifact_sha


def _require_legacy_literature_planner(state_root: Path) -> None:
    """Prevent the pre-B9 legacy planner from writing after the v2 cutover."""

    status = _cutover_controller(state_root).status()
    if status.state != "legacy":
        raise DomainCutoverError(
            "legacy literature planner is unavailable after prepare; use the B9 domain worker planner"
        )


@app.command()
def stop(
    state_root: Annotated[
        Path,
        typer.Option(help="State root containing daemon runtime files."),
    ] = default_state_root(),
    pid_file: Annotated[
        Path | None,
        typer.Option(help="Optional pid file path for daemon mode."),
    ] = None,
) -> None:
    runtime_dir = state_root / "runtime"
    resolved_pid_file = pid_file or runtime_dir / "ainrf-api.pid"
    if stop_server_daemon(resolved_pid_file):
        typer.echo("OpenScience API daemon stopped.")
        return
    typer.echo("OpenScience API daemon is not running.")


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


def build_container_profile(
    name: str,
    ssh_command: str,
    project_dir: str,
    password: str,
) -> tuple[str, dict[str, str | int | None]]:
    parsed = _parse_ssh_command(ssh_command)
    profile = {
        "host": parsed.host,
        "port": parsed.port,
        "user": parsed.user,
        "ssh_key_path": parsed.ssh_key_path,
        "project_dir": project_dir,
        "ssh_password": password or None,
    }
    return name, profile


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


def _cutover_controller(
    state_root: Path,
    *,
    workspace_root: Path | None = None,
    tenant_root: Path | None = None,
) -> DomainCutoverController:
    return DomainCutoverController(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )


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


@domain_cutover_app.command("status")
def domain_cutover_status(
    state_root: Annotated[
        Path, typer.Option(help="State root containing the authoritative cutover fuse.")
    ] = default_state_root(),
) -> None:
    """Report persisted cutover evidence and the legacy-source monitor."""

    try:
        typer.echo(json_mod.dumps(_cutover_controller(state_root).status().as_dict(), indent=2))
    except DomainCutoverError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


@domain_cutover_app.command("finalize-constraints")
def domain_cutover_finalize_constraints(
    run_id: Annotated[
        str, typer.Argument(help="Completed migration run whose Task references will be finalized.")
    ],
    actor_id: Annotated[
        str, typer.Option(help="Operator ID recorded in the constraints finalization audit.")
    ],
    stability_window_seconds: Annotated[
        float,
        typer.Option(
            min=0.0,
            help="Required stable source window while the maintenance epoch owns writes.",
        ),
    ] = 5.0,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Explicit Workspace tree selected for backup/cutover stability proof."),
    ] = None,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Explicit tenant tree selected for backup/cutover stability proof."),
    ] = None,
    state_root: Annotated[
        Path, typer.Option(help="State root containing migration and maintenance state.")
    ] = default_state_root(),
) -> None:
    """Install and attest the final Task reference guards during maintenance."""

    maintenance = _maintenance_service(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )
    participant = _admin_cli_participant(
        state_root,
        "domain-cutover.finalize-constraints",
        maintenance=maintenance,
    )
    try:
        result = _cutover_controller(
            state_root,
            workspace_root=workspace_root,
            tenant_root=tenant_root,
        ).finalize_constraints(
            actor_id=actor_id,
            run_id=run_id,
            stability_window_seconds=stability_window_seconds,
            maintenance_participant_id=participant.participant_id,
        )
    except (DomainCutoverError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        participant.stop()
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_cutover_app.command("prepare")
def domain_cutover_prepare(
    run_id: Annotated[str, typer.Argument(help="Finalized migration run to bind to cutover.")],
    backup_archive: Annotated[Path, typer.Argument(help="Verified v3 backup archive.")],
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in cutover audit events.")],
    artifact_sha: Annotated[str, typer.Option(help="Exact immutable backend artifact SHA-256.")],
    artifact_contract_min: Annotated[
        int, typer.Option(help="Lowest domain contract version supported by the artifact.")
    ],
    artifact_contract_max: Annotated[
        int, typer.Option(help="Highest domain contract version supported by the artifact.")
    ],
    artifact_schema_min: Annotated[
        int, typer.Option(help="Lowest domain schema migration version supported by the artifact.")
    ],
    artifact_schema_max: Annotated[
        int, typer.Option(help="Highest domain schema migration version supported by the artifact.")
    ],
    stability_window_seconds: Annotated[
        float, typer.Option(min=0.0, help="Required stable source window before preparing.")
    ] = 5.0,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Explicit Workspace tree selected for backup/cutover stability proof."),
    ] = None,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Explicit tenant tree selected for backup/cutover stability proof."),
    ] = None,
    state_root: Annotated[
        Path, typer.Option(help="State root containing migration and maintenance state.")
    ] = default_state_root(),
) -> None:
    """Prepare but do not yet enable the irreversible v2 cutover."""

    maintenance = _maintenance_service(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )
    participant = _admin_cli_participant(
        state_root,
        "domain-cutover.prepare",
        maintenance=maintenance,
    )
    try:
        result = _cutover_controller(
            state_root,
            workspace_root=workspace_root,
            tenant_root=tenant_root,
        ).prepare(
            actor_id=actor_id,
            run_id=run_id,
            backup_archive=backup_archive,
            artifact_sha=artifact_sha,
            artifact_contract_min=artifact_contract_min,
            artifact_contract_max=artifact_contract_max,
            artifact_schema_min=artifact_schema_min,
            artifact_schema_max=artifact_schema_max,
            stability_window_seconds=stability_window_seconds,
            maintenance_participant_id=participant.participant_id,
        )
    except (DomainCutoverError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        participant.stop()
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_cutover_app.command("commit")
def domain_cutover_commit(
    run_id: Annotated[str, typer.Argument(help="Prepared migration run ID.")],
    backup_archive: Annotated[Path, typer.Argument(help="Verified v3 backup archive.")],
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in cutover audit events.")],
    artifact_sha: Annotated[str, typer.Option(help="Exact immutable backend artifact SHA-256.")],
    artifact_contract_min: Annotated[
        int, typer.Option(help="Lowest domain contract version supported by the artifact.")
    ],
    artifact_contract_max: Annotated[
        int, typer.Option(help="Highest domain contract version supported by the artifact.")
    ],
    artifact_schema_min: Annotated[
        int, typer.Option(help="Lowest domain schema migration version supported by the artifact.")
    ],
    artifact_schema_max: Annotated[
        int, typer.Option(help="Highest domain schema migration version supported by the artifact.")
    ],
    stability_window_seconds: Annotated[
        float, typer.Option(min=0.0, help="Required stable source window before committing.")
    ] = 5.0,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Explicit Workspace tree selected for backup/cutover stability proof."),
    ] = None,
    tenant_root: Annotated[
        Path | None,
        typer.Option(help="Explicit tenant tree selected for backup/cutover stability proof."),
    ] = None,
    state_root: Annotated[
        Path, typer.Option(help="State root containing migration and maintenance state.")
    ] = default_state_root(),
) -> None:
    """Commit the prepared v2 fuse after repeating all safety gates."""

    maintenance = _maintenance_service(
        state_root,
        workspace_root=workspace_root,
        tenant_root=tenant_root,
    )
    participant = _admin_cli_participant(
        state_root,
        "domain-cutover.commit",
        maintenance=maintenance,
    )
    try:
        result = _cutover_controller(
            state_root,
            workspace_root=workspace_root,
            tenant_root=tenant_root,
        ).commit(
            actor_id=actor_id,
            run_id=run_id,
            backup_archive=backup_archive,
            artifact_sha=artifact_sha,
            artifact_contract_min=artifact_contract_min,
            artifact_contract_max=artifact_contract_max,
            artifact_schema_min=artifact_schema_min,
            artifact_schema_max=artifact_schema_max,
            stability_window_seconds=stability_window_seconds,
            maintenance_participant_id=participant.participant_id,
        )
    except (DomainCutoverError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        participant.stop()
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_cutover_app.command("abort")
def domain_cutover_abort(
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in cutover audit events.")],
    reason: Annotated[str, typer.Option(help="Required reason for abandoning prepared cutover.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing the authoritative cutover fuse.")
    ] = default_state_root(),
) -> None:
    """Abort only a prepared cutover before the first v2 write exists."""

    participant = _admin_cli_participant(state_root, "domain-cutover.abort")
    try:
        result = _cutover_controller(state_root).abort(
            actor_id=actor_id,
            reason=reason,
            maintenance_participant_id=participant.participant_id,
        )
    except (DomainCutoverError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        participant.stop()
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_runtime_app.command("resolve-launch-unknown")
def domain_runtime_resolve_launch_unknown(
    task_id: Annotated[str, typer.Argument(help="Task containing the unknown runtime launch.")],
    attempt_id: Annotated[
        str, typer.Argument(help="Attempt whose launch was manually investigated.")
    ],
    actor_id: Annotated[
        str,
        typer.Option(help="Existing active Task owner or admin user ID recorded in the audit."),
    ],
    reason: Annotated[
        str,
        typer.Option(help="Required evidence explaining why the unknown runtime is terminal."),
    ],
    idempotency_key: Annotated[
        str | None,
        typer.Option(help="Stable key reused if this manual resolution command is retried."),
    ] = None,
    state_root: Annotated[
        Path, typer.Option(help="State root containing the committed domain v2 control plane.")
    ] = default_state_root(),
) -> None:
    """Close a manually investigated unknown launch; never retry or relaunch it."""

    try:
        with _admin_cli_mutation(
            state_root,
            "domain-runtime.resolve-launch-unknown",
        ) as (maintenance, lease):
            artifact_sha = _domain_worker_artifact_sha(state_root)
            if artifact_sha is None:
                raise DomainCutoverError(
                    "runtime launch reconciliation requires a committed domain v2 artifact"
                )
            auth = AuthService(state_root=state_root)
            auth.initialize()
            maintenance.check_lease(lease)
            actor = auth.get_user(actor_id)
            if actor.status.value != "active":
                raise DomainCutoverError("runtime launch reconciliation actor is not active")
            result = TaskApplicationService(
                state_root,
                artifact_sha=artifact_sha,
            ).resolve_launch_unknown(
                task_id,
                attempt_id,
                {"id": actor.id, "role": actor.role.value},
                reason=reason,
                idempotency_key=idempotency_key or f"launch-unknown-resolution:{attempt_id}",
            )
            maintenance.check_lease(lease)
    except (DomainCutoverError, LookupError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result, indent=2))


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
            dict.fromkeys(CUTOVER_REQUIRED_PARTICIPANT_TYPES + tuple(required_participant_type))
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


@domain_migration_app.command("dry-run")
def domain_migration_dry_run(
    state_root: Annotated[
        Path, typer.Option(help="Legacy state root to inspect.")
    ] = default_state_root(),
) -> None:
    """Print an immutable source manifest without modifying legacy state."""
    typer.echo(json_mod.dumps(capture_source_manifest(state_root).as_dict(), indent=2))


@domain_migration_app.command("apply")
def domain_migration_apply(
    state_root: Annotated[
        Path, typer.Option(help="State root containing legacy sources and v2 shadow tables.")
    ] = default_state_root(),
    mode: Annotated[str, typer.Option(help="Importer mode: validate or apply.")] = "validate",
    artifact_sha: Annotated[
        str | None,
        typer.Option(help="Immutable artifact SHA recorded with this migration run."),
    ] = None,
) -> None:
    """Run the application-level shadow importer; this never performs cutover."""
    try:
        result = DomainImporter(state_root).run(mode=mode, artifact_sha=artifact_sha)
    except (MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_migration_app.command("resume")
def domain_migration_resume(
    run_id: Annotated[str, typer.Argument(help="Interrupted migration run ID to resume.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing the fixed legacy sources and v2 tables.")
    ] = default_state_root(),
    artifact_sha: Annotated[
        str | None,
        typer.Option(help="Artifact SHA; it must equal the interrupted run's artifact."),
    ] = None,
) -> None:
    """Resume an interrupted or maintenance-paused run with matching source evidence."""
    try:
        result = DomainImporter(state_root).resume(run_id, artifact_sha=artifact_sha)
    except (MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_migration_app.command("inspect")
def domain_migration_inspect(
    run_id: Annotated[str, typer.Argument(help="Migration run ID to inspect.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """Inspect persisted phase, checkpoint, heartbeat, and resume metadata."""
    typer.echo(json_mod.dumps(DomainImporter(state_root).inspect(run_id).as_dict(), indent=2))


@domain_migration_app.command("records")
def domain_migration_records(
    run_id: Annotated[str, typer.Argument(help="Migration run ID whose source outcomes to list.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """List the durable imported/skipped/attention-needed result for each source record."""
    results = [item.as_dict() for item in DomainImporter(state_root).record_results(run_id)]
    typer.echo(json_mod.dumps(results, indent=2))


@domain_migration_app.command("issues")
def domain_migration_issues(
    run_id: Annotated[str, typer.Argument(help="Migration run ID whose issues to list.")],
    include_resolved: Annotated[
        bool,
        typer.Option(help="Include issues with a verified, applied typed resolution."),
    ] = False,
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """List unresolved remediation work without changing cutover state."""
    service = DomainReconciliationService(state_root)
    issues = [
        issue.as_dict() for issue in service.list_issues(run_id, include_resolved=include_resolved)
    ]
    typer.echo(json_mod.dumps(issues, indent=2))


@domain_migration_app.command("issue")
def domain_migration_issue(
    issue_id: Annotated[str, typer.Argument(help="Migration issue ID to inspect.")],
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """Inspect one migration issue and its explicit resolution state."""
    typer.echo(
        json_mod.dumps(
            DomainReconciliationService(state_root).inspect_issue(issue_id).as_dict(), indent=2
        )
    )


@domain_migration_app.command("resolve")
def domain_migration_resolve(
    run_id: Annotated[str, typer.Argument(help="Migration run ID containing the issue.")],
    issue_id: Annotated[str, typer.Argument(help="Migration issue ID to resolve.")],
    resolution_type: Annotated[
        str,
        typer.Option(
            help=(
                "Explicit resolution: assign_project_owner, assign_workspace_owner, "
                "assign_task_owner, assign_workspace_environment, set_primary_workspace, "
                "or map_runtime_session."
            )
        ),
    ],
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in the audit event.")],
    payload_json: Annotated[
        str,
        typer.Option("--payload", help="JSON object required by the selected typed resolution."),
    ] = "{}",
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """Apply a narrowly typed, audited migration remediation."""
    try:
        parsed = json_mod.loads(payload_json)
    except json_mod.JSONDecodeError as exc:
        raise typer.BadParameter("--payload must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("--payload must be a JSON object")
    payload = {str(key): value for key, value in parsed.items()}
    try:
        with _admin_cli_mutation(state_root, "domain-migration.resolve") as (
            maintenance,
            lease,
        ):
            result = DomainReconciliationService(
                state_root,
                maintenance=maintenance,
                maintenance_lease=lease,
                initialize_schema=False,
            ).resolve_issue(
                run_id,
                issue_id,
                resolution_type,
                payload,
                actor_id=actor_id,
            )
    except (LookupError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_migration_app.command("finalize")
def domain_migration_finalize(
    run_id: Annotated[
        str, typer.Argument(help="Completed migration run to finalize for cutover prepare.")
    ],
    actor_id: Annotated[str, typer.Option(help="Operator ID recorded in the audit event.")],
    artifact_sha: Annotated[
        str,
        typer.Option(help="SHA-256 of the immutable artifact that performed the migration."),
    ],
    restore_evidence_json: Annotated[
        str,
        typer.Option("--restore-evidence", help="Validated restore evidence as a JSON object."),
    ],
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
) -> None:
    """Freeze reconciliation evidence; this does not prepare or commit cutover."""
    try:
        parsed = json_mod.loads(restore_evidence_json)
    except json_mod.JSONDecodeError as exc:
        raise typer.BadParameter("--restore-evidence must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("--restore-evidence must be a JSON object")
    evidence = {str(key): value for key, value in parsed.items()}
    try:
        with _admin_cli_mutation(state_root, "domain-migration.finalize") as (
            maintenance,
            lease,
        ):
            result = DomainReconciliationService(
                state_root,
                maintenance=maintenance,
                maintenance_lease=lease,
                initialize_schema=False,
            ).finalize_run(
                run_id,
                actor_id,
                artifact_sha,
                evidence,
            )
    except (LookupError, MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


@domain_migration_app.command("reconcile")
def domain_migration_reconcile(
    state_root: Annotated[
        Path, typer.Option(help="State root containing v2 shadow tables.")
    ] = default_state_root(),
    run_id: Annotated[str | None, typer.Option(help="Optional migration run ID.")] = None,
) -> None:
    """Report migration counts and blocking issues without cutover."""
    try:
        with _admin_cli_mutation(state_root, "domain-migration.reconcile") as (
            maintenance,
            lease,
        ):
            result = DomainReconciliationService(
                state_root,
                maintenance=maintenance,
                maintenance_lease=lease,
                initialize_schema=False,
            ).reconcile(run_id)
    except (MaintenanceModeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json_mod.dumps(result.as_dict(), indent=2))


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
            raise DomainCutoverError(
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
    except (DomainCutoverError, MaintenanceModeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        if planner is not None:
            planner.stop()


def main() -> None:

    app()


@dataclass(slots=True)
class ParsedSSHCommand:
    host: str
    user: str
    port: int = 22
    ssh_key_path: str | None = None


def _parse_ssh_command(command: str) -> ParsedSSHCommand:
    tokens = shlex.split(command)
    if not tokens:
        raise typer.BadParameter("SSH command cannot be empty")
    if tokens[0] == "ssh":
        tokens = tokens[1:]
    port = 22
    user: str | None = None
    ssh_key_path: str | None = None
    host: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "-p":
            index += 1
            if index >= len(tokens):
                raise typer.BadParameter("Invalid SSH command: missing value for -p")
            port = int(tokens[index])
        elif token.startswith("-p") and token != "-p":
            port = int(token[2:])
        elif token == "-l":
            index += 1
            if index >= len(tokens):
                raise typer.BadParameter("Invalid SSH command: missing value for -l")
            user = tokens[index]
        elif token == "-i":
            index += 1
            if index >= len(tokens):
                raise typer.BadParameter("Invalid SSH command: missing value for -i")
            ssh_key_path = tokens[index]
        elif token.startswith("-"):
            if token in {"-o", "-J"}:
                index += 1
        else:
            host = token
        index += 1
    if host is None:
        raise typer.BadParameter("Invalid SSH command: missing target host")
    if "@" in host:
        parsed_user, parsed_host = host.split("@", 1)
        if parsed_user:
            user = parsed_user
        host = parsed_host
    if user is None:
        raise typer.BadParameter("Invalid SSH command: missing user (use user@host or -l user)")
    return ParsedSSHCommand(host=host, user=user, port=port, ssh_key_path=ssh_key_path)


def _ensure_api_key_hashes_configured(state_root: Path) -> None:
    # Keep the command preflight aligned with ``ApiConfig.from_env``.  A
    # deployment using the public OpenScience name must not fall into
    # interactive onboarding before the server has a chance to read the same
    # configuration.
    env_hashes = os.environ.get(
        "OPENSCIENCE_API_KEY_HASHES",
        os.environ.get("AINRF_API_KEY_HASHES", ""),
    ).strip()
    if env_hashes:
        return
    config_path = config_path_for(state_root)
    if not config_path.exists():
        try:
            ensure_interactive_onboarding_available()
        except typer.BadParameter:
            typer.echo(
                "OpenScience API key hashes are not configured. Run `openscience onboard` interactively."
            )
            raise typer.Exit(code=1) from None
        onboard_state_root(state_root)
        return
    payload = load_runtime_config(config_path)
    hashes = payload.get("api_key_hashes")
    if isinstance(hashes, list) and any(isinstance(item, str) and item for item in hashes):
        return
    raise typer.BadParameter(f"Invalid runtime config at {config_path}: missing api_key_hashes")

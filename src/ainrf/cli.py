from __future__ import annotations

import json as json_mod
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from ainrf import __version__
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
from ainrf.domain_control import DomainMaintenanceService, MaintenanceModeError
from ainrf.domain_migration import capture_source_manifest
from ainrf.literature.planner import dispatch_outbox
from ainrf.literature.tracking import LiteratureTrackingService


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
    service = LiteratureTrackingService(state_root)
    service.initialize()
    if once:
        typer.echo(f"Published {dispatch_outbox(service)} literature work item(s).")
        return
    from ainrf.literature.planner import run_forever

    run_forever(service)


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

    The active state root is not overwritten. Verify and promote the staged
    root through the deployment's explicit directory/volume switch procedure.
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


def _maintenance_service(state_root: Path) -> DomainMaintenanceService:
    service = DomainMaintenanceService(state_root)
    service.initialize()
    return service


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


@domain_migration_app.command("dry-run")
def domain_migration_dry_run(
    state_root: Annotated[
        Path, typer.Option(help="Legacy state root to inspect.")
    ] = default_state_root(),
) -> None:
    """Print an immutable source manifest without modifying legacy state."""
    typer.echo(json_mod.dumps(capture_source_manifest(state_root).as_dict(), indent=2))


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
    env_hashes = os.environ.get("AINRF_API_KEY_HASHES", "").strip()
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

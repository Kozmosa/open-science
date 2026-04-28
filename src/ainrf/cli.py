from __future__ import annotations

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


app = typer.Typer(
    add_completion=False,
    help="AINRF daemon-oriented runtime CLI.",
    no_args_is_help=True,
)

container_app = typer.Typer(help="Manage reusable container profiles.")
app.add_typer(container_app, name="container")


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
        typer.Option(help="State root where AINRF config will be initialized."),
    ] = default_state_root(),
) -> None:
    run_onboarding(state_root)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host for the API server.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the API server.")] = 8000,
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
        typer.echo(f"AINRF API daemon started (pid={daemon_pid}, port={port})")
        return
    run_server(host, port, state_root)


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
        typer.echo("AINRF API daemon stopped.")
        return
    typer.echo("AINRF API daemon is not running.")


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
            help="Remote project directory used by AINRF.",
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
                "AINRF API key hashes are not configured. Run `ainrf onboard` interactively."
            )
            raise typer.Exit(code=1) from None
        onboard_state_root(state_root)
        return
    payload = load_runtime_config(config_path)
    hashes = payload.get("api_key_hashes")
    if isinstance(hashes, list) and any(isinstance(item, str) and item for item in hashes):
        return
    raise typer.BadParameter(f"Invalid runtime config at {config_path}: missing api_key_hashes")

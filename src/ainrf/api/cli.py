from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from ainrf.api.server import (
    run_http_server,
    run_http_server_daemon,
    stop_http_server_daemon,
)
from ainrf.command import app
from ainrf.onboarding import (
    config_path_for,
    ensure_interactive_onboarding_available,
    load_runtime_config,
    onboard_state_root,
)
from ainrf.state import default_state_root


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host for the API server.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the API server.")] = 8000,
    workers: Annotated[int, typer.Option(help="Number of uvicorn worker processes.")] = 1,
    daemon: Annotated[bool, typer.Option(help="Run the API server in the background.")] = False,
    reload: Annotated[
        bool, typer.Option(help="Reload the HTTP Adapter on source changes.")
    ] = False,
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
    if daemon and reload:
        raise typer.BadParameter("--daemon and --reload cannot be used together")
    if reload and workers != 1:
        raise typer.BadParameter("--reload requires --workers 1")
    if daemon:
        runtime_dir = state_root / "runtime"
        resolved_pid_file = pid_file or runtime_dir / "ainrf-api.pid"
        resolved_log_file = log_file or runtime_dir / "ainrf-api.log"
        daemon_pid = run_http_server_daemon(
            host, port, state_root, resolved_pid_file, resolved_log_file
        )
        typer.echo(f"OpenScience API daemon started (pid={daemon_pid}, port={port})")
        return
    run_http_server(host, port, state_root, workers=workers, reload=reload)


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
    if stop_http_server_daemon(resolved_pid_file):
        typer.echo("OpenScience API daemon stopped.")
        return
    typer.echo("OpenScience API daemon is not running.")


def main() -> None:
    app()


def _ensure_api_key_hashes_configured(state_root: Path) -> None:
    env_hashes = os.environ.get(
        "AINRF_API_KEY_HASHES",
        os.environ.get("OPENSCIENCE_API_KEY_HASHES", ""),
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

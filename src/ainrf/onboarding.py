from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import click
import typer

from ainrf.api.config import hash_api_key
from ainrf.runtime import build_default_runtime_config, normalize_runtime_config
from ainrf.runtime.readiness import RuntimeReadinessPayload, check_runtime_readiness


def config_path_for(state_root: Path) -> Path:
    return state_root / "config.json"


def load_runtime_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid runtime config at {config_path}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"Invalid runtime config at {config_path}")
    return payload


def save_runtime_config(config_path: Path, payload: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def ensure_interactive_onboarding_available() -> None:
    stdin = click.get_text_stream("stdin")
    stdout = click.get_text_stream("stdout")
    if not stdin.isatty() or not stdout.isatty():
        raise typer.BadParameter(
            "AINRF runtime config is not configured. Run onboarding interactively."
        )


def prompt_api_key() -> str:
    api_key = typer.prompt(
        "API key for AINRF clients",
        hide_input=True,
        confirmation_prompt=True,
    ).strip()
    if not api_key:
        raise typer.BadParameter("API key cannot be empty.")
    return api_key


def prompt_optional_container_profile() -> tuple[str, dict[str, str | int | None]] | None:
    if not typer.confirm("Add an optional container profile?", default=False):
        return None
    from ainrf.cli import build_container_profile

    name = typer.prompt("Container profile name", default="default").strip()
    ssh_command = typer.prompt("SSH command").strip()
    project_dir = typer.prompt("Remote project directory", default="/workspace/projects").strip()
    password = typer.prompt(
        "SSH password (optional)",
        hide_input=True,
        confirmation_prompt=False,
        default="",
    ).strip()
    return build_container_profile(name, ssh_command, project_dir, password)


def echo_runtime_readiness(payload: RuntimeReadinessPayload) -> None:
    if payload.get("ready") is True:
        typer.echo("Runtime dependencies are ready.")
        return
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, dict):
        return
    missing = [
        (name, dependency)
        for name, dependency in dependencies.items()
        if isinstance(dependency, dict) and dependency.get("available") is False
    ]
    if not missing:
        return
    typer.echo("Runtime dependency setup needed:")
    for name, dependency in missing:
        detail = dependency.get("detail")
        typer.echo(
            f"- {name}: {detail if isinstance(detail, str) else 'Dependency is unavailable.'}"
        )


def onboard_state_root(state_root: Path, *, reset_existing: bool = False) -> Path:
    config_path = config_path_for(state_root)
    payload = build_default_runtime_config() if reset_existing else load_runtime_config(config_path)
    payload = normalize_runtime_config(payload)
    payload["api_key_hashes"] = [hash_api_key(prompt_api_key())]
    runtime_readiness = check_runtime_readiness().as_public_payload()
    payload["runtime_readiness"] = runtime_readiness
    echo_runtime_readiness(runtime_readiness)

    container_profile = prompt_optional_container_profile()
    if container_profile is not None:
        name, profile = container_profile
        profiles = payload.get("container_profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        profiles[name] = profile
        payload["container_profiles"] = profiles

    save_runtime_config(config_path, payload)
    typer.echo(f"Saved onboarding config to `{config_path}`.")
    return config_path


def run_onboarding(state_root: Path) -> Path | None:
    ensure_interactive_onboarding_available()
    config_path = config_path_for(state_root)
    reset_existing = False
    if config_path.exists() and not typer.confirm(
        f"AINRF config already exists at `{config_path}`. Overwrite it?",
        default=False,
    ):
        typer.echo("Keeping existing AINRF config.")
        return None
    if config_path.exists():
        reset_existing = True
    return onboard_state_root(state_root, reset_existing=reset_existing)


def ensure_onboarded(state_root: Path) -> Path:
    config_path = config_path_for(state_root)
    if config_path.exists():
        return config_path
    ensure_interactive_onboarding_available()
    return onboard_state_root(state_root)

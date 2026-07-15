from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

from ainrf.development import (
    DEFAULT_FRONTEND_DEV_ARTIFACT_SHA,
    DevelopmentStack,
    DevelopmentStackError,
    DevelopmentStackMode,
    FrontendDevInstance,
    resolve_frontend_dev_instance,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default="full")
    parser.add_argument(
        "--mode", choices=[mode.value for mode in DevelopmentStackMode], default="dev"
    )
    parser.add_argument("--artifact-sha", default=DEFAULT_FRONTEND_DEV_ARTIFACT_SHA)
    parser.add_argument("--api-key")
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--personal-state-root", type=Path)
    parser.add_argument("--bind-host")
    parser.add_argument("--frontend-host")
    parser.add_argument("--frontend-port", type=int)
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--json", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenScience isolated development stack")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "down", "status", "reset", "env", "smoke"):
        _add_common_options(subparsers.add_parser(command))
    up = subparsers.add_parser("up")
    _add_common_options(up)
    up.add_argument("--foreground", action="store_true")
    logs = subparsers.add_parser("logs")
    _add_common_options(logs)
    logs.add_argument(
        "service", choices=("api", "worker", "frontend", "all"), nargs="?", default="all"
    )
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--lines", type=int, default=200)
    return parser


def _instance_env(args: argparse.Namespace) -> dict[str, str]:
    environment = os.environ.copy()
    if args.bind_host:
        environment["OPENSCIENCE_DEV_BIND_HOST"] = args.bind_host
    if args.frontend_port is not None:
        environment["OPENSCIENCE_DEV_FRONTEND_PORT"] = str(args.frontend_port)
    if args.api_port is not None:
        environment["OPENSCIENCE_DEV_API_PORT"] = str(args.api_port)
    return environment


def _resolve_instance(args: argparse.Namespace) -> FrontendDevInstance:
    profile = "personal" if args.personal_state_root is not None else args.profile
    instance = resolve_frontend_dev_instance(
        REPO_ROOT,
        profile=profile,
        env=_instance_env(args),
    )
    if args.state_root is not None:
        instance = replace(instance, state_root=args.state_root.expanduser().resolve())
    return instance


def _stack(args: argparse.Namespace) -> DevelopmentStack:
    return DevelopmentStack(
        _resolve_instance(args),
        artifact_sha=args.artifact_sha,
        mode=DevelopmentStackMode(args.mode),
        api_key=args.api_key,
        personal_state_root=args.personal_state_root,
        frontend_bind_host=args.frontend_host,
    )


def _print_payload(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    state = payload.get("state")
    if state is not None:
        print(f"OpenScience development stack: {state}")
    urls = payload.get("urls")
    if isinstance(urls, dict):
        for name, value in urls.items():
            print(f"{name}: {value}")
    paths = payload.get("paths")
    if isinstance(paths, dict):
        path_values = cast(dict[str, object], paths)
        print(f"state: {path_values.get('state_root')}")
        print(f"logs: {path_values.get('log_root')}")
    if state is None and not isinstance(urls, dict) and not isinstance(paths, dict):
        print(json.dumps(payload, indent=2, sort_keys=True))


def _print_environment(stack: DevelopmentStack) -> None:
    environment = stack.environment()
    names = (
        "OPENSCIENCE_STATE_ROOT",
        "OPENSCIENCE_DOMAIN_MODEL_MODE",
        "OPENSCIENCE_DOMAIN_ARTIFACT_SHA",
        "OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED",
        "OPENSCIENCE_JWT_SECRET",
        "OPENSCIENCE_WEBUI_API_KEY",
        "OPENSCIENCE_WEBUI_BACKEND_TARGET",
        "OPENSCIENCE_AUTH_COOKIE_NAMESPACE",
    )
    for name in names:
        value = environment.get(name)
        if value is not None:
            print(f"export {name}={shlex.quote(value)}")


def _show_logs(stack: DevelopmentStack, service: str, lines: int, follow: bool) -> int:
    if lines <= 0:
        raise DevelopmentStackError("--lines must be a positive integer")
    paths = stack.log_paths(service)
    existing = [path for path in paths if path.exists()]
    if not existing:
        raise DevelopmentStackError("no development logs exist for the selected service")
    if follow:
        return subprocess.run(
            ["tail", "-n", str(lines), "-f", *[str(path) for path in existing]],
            check=False,
        ).returncode
    for path in existing:
        print(f"==> {path} <==")
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(content[-lines:]))
    return 0


def _foreground(stack: DevelopmentStack) -> int:
    try:
        while True:
            status = stack.status()
            if status.state != "healthy":
                _print_payload(status.payload, as_json=False)
                return 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        stack.down()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        stack = _stack(args)
        if args.command == "prepare":
            _print_payload(stack.prepare(), as_json=args.json)
            return 0
        if args.command == "up":
            status = stack.up()
            _print_payload(status.payload, as_json=args.json)
            return _foreground(stack) if args.foreground else 0
        if args.command == "down":
            status = stack.down()
            _print_payload(status.payload, as_json=args.json)
            return 0
        if args.command == "status":
            status = stack.status()
            _print_payload(status.payload, as_json=args.json)
            return 0 if status.state == "healthy" else 1
        if args.command == "reset":
            _print_payload(stack.reset(), as_json=args.json)
            return 0
        if args.command == "env":
            _print_environment(stack)
            return 0
        if args.command == "smoke":
            _print_payload(stack.smoke(), as_json=args.json)
            return 0
        if args.command == "logs":
            return _show_logs(stack, args.service, args.lines, args.follow)
    except (DevelopmentStackError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[osci-dev] {exc}", file=sys.stderr)
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

"""Neutral parsing and construction of SSH-backed runtime profiles."""

from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedSSHCommand:
    host: str
    user: str
    port: int = 22
    ssh_key_path: str | None = None


def parse_ssh_command(command: str) -> ParsedSSHCommand:
    tokens = shlex.split(command)
    if not tokens:
        raise ValueError("SSH command cannot be empty")
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
                raise ValueError("Invalid SSH command: missing value for -p")
            port = int(tokens[index])
        elif token.startswith("-p") and token != "-p":
            port = int(token[2:])
        elif token == "-l":
            index += 1
            if index >= len(tokens):
                raise ValueError("Invalid SSH command: missing value for -l")
            user = tokens[index]
        elif token == "-i":
            index += 1
            if index >= len(tokens):
                raise ValueError("Invalid SSH command: missing value for -i")
            ssh_key_path = tokens[index]
        elif token.startswith("-"):
            if token in {"-o", "-J"}:
                index += 1
        else:
            host = token
        index += 1
    if host is None:
        raise ValueError("Invalid SSH command: missing target host")
    if "@" in host:
        parsed_user, host = host.split("@", 1)
        if parsed_user:
            user = parsed_user
    if user is None:
        raise ValueError("Invalid SSH command: missing user (use user@host or -l user)")
    return ParsedSSHCommand(host=host, user=user, port=port, ssh_key_path=ssh_key_path)


def build_container_profile(
    name: str,
    ssh_command: str,
    project_dir: str,
    password: str,
) -> tuple[str, dict[str, str | int | None]]:
    parsed = parse_ssh_command(ssh_command)
    return name, {
        "host": parsed.host,
        "port": parsed.port,
        "user": parsed.user,
        "ssh_key_path": parsed.ssh_key_path,
        "project_dir": project_dir,
        "ssh_password": password or None,
    }

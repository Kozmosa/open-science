#!/usr/bin/env python3
"""Migrate existing OpenScience users to per-tenant Linux users and workspaces.

Creates ``ainrf_<username>`` Linux users (group ``ainrf_tenants``, GID 2000),
home directories under ``/home/ainrf_tenants/<username>/``,
default workspaces, and updates the workspace registry to point at the new
paths.

This script is idempotent — safe to run multiple times.

Usage (inside the container or on the host with the right privileges)::

    python scripts/migrate_tenant_users.py [--state-root /opt/ainrf/state]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_LOG = logging.getLogger(__name__)

_TENANT_GID = 2000
_TENANT_GROUP = "ainrf_tenants"
_TENANT_HOME_ROOT = Path("/home/ainrf_tenants")


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    _LOG.debug("  → %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _group_exists(name: str) -> bool:
    return _run(["getent", "group", name], check=False).returncode == 0


def _user_exists(name: str) -> bool:
    return _run(["id", name], check=False).returncode == 0


def _ensure_group() -> None:
    if _group_exists(_TENANT_GROUP):
        _LOG.info("Group %s already exists", _TENANT_GROUP)
        return
    _LOG.info("Creating group %s (GID %d)", _TENANT_GROUP, _TENANT_GID)
    _run(["groupadd", "--gid", str(_TENANT_GID), _TENANT_GROUP])


def _create_user(username: str) -> Path:
    linux_user = f"ainrf_{username}"
    home = _TENANT_HOME_ROOT / username
    workspace_dir = home / "workspaces" / "default"

    if _user_exists(linux_user):
        _LOG.info("User %s already exists — skipping useradd", linux_user)
    else:
        _LOG.info("Creating user %s (home: %s)", linux_user, home)
        _run(
            [
                "useradd",
                "--gid", str(_TENANT_GID),
                "--home-dir", str(home),
                "--create-home",
                "--shell", "/bin/bash",
                linux_user,
            ]
        )

    home.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    _run(["chown", "-R", f"{linux_user}:{_TENANT_GROUP}", str(home)])
    return workspace_dir


def _migrate_workspace_files(
    username: str,
    old_workspace_dir: Path | None,
    new_workspace_dir: Path,
) -> None:
    """Move files from old workspace directory to the new tenant workspace."""
    if old_workspace_dir is None or not old_workspace_dir.exists():
        return
    if old_workspace_dir.resolve() == new_workspace_dir.resolve():
        return
    if not any(old_workspace_dir.iterdir()):
        return

    _LOG.info(
        "Migrating workspace files: %s → %s",
        old_workspace_dir,
        new_workspace_dir,
    )
    # Copy contents, don't replace the directory itself
    for item in old_workspace_dir.iterdir():
        dest = new_workspace_dir / item.name
        if dest.exists():
            _LOG.warning("  Skipping %s (already exists in target)", item.name)
            continue
        if item.is_dir():
            shutil.copytree(str(item), str(dest))
        else:
            shutil.copy2(str(item), str(dest))
    linux_user = f"ainrf_{username}"
    _run(["chown", "-R", f"{linux_user}:{_TENANT_GROUP}", str(new_workspace_dir)])


def _update_workspace_registry(
    state_root: Path,
    username: str,
    new_workspace_dir: Path,
) -> None:
    """Update workspaces.json entries for the user to point at the new path."""
    registry_path = state_root / "runtime" / "workspaces.json"
    if not registry_path.exists():
        _LOG.info("No workspace registry found at %s — skipping", registry_path)
        return

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    changed = False
    for item in items:
        if item.get("owner_user_id") != username:
            continue
        old_dir = item.get("default_workdir", "")
        new_dir = str(new_workspace_dir)
        if old_dir == new_dir:
            continue
        _LOG.info("  Updating workspace %s: %s → %s", item.get("workspace_id"), old_dir, new_dir)
        item["default_workdir"] = new_dir
        changed = True

    if changed:
        registry_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _LOG.info("Workspace registry updated")


def main(state_root: Path) -> None:
    auth_db = state_root / "runtime" / "auth.sqlite3"
    if not auth_db.exists():
        _LOG.error("Auth database not found at %s", auth_db)
        raise SystemExit(1)

    _LOG.info("=== Tenant migration ===")
    _LOG.info("State root: %s", state_root)
    _LOG.info("Auth DB:    %s", auth_db)

    _ensure_group()
    _TENANT_HOME_ROOT.mkdir(parents=True, exist_ok=True)
    _run(["chmod", "0755", str(_TENANT_HOME_ROOT)], check=False)

    conn = sqlite3.connect(str(auth_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, username FROM users ORDER BY created_at").fetchall()
    conn.close()

    _LOG.info("Found %d users to migrate", len(rows))

    # Load old workspace registry to find per-user workspace dirs
    registry_path = state_root / "runtime" / "workspaces.json"
    old_workspaces: dict[str, str] = {}  # username → default_workdir
    if registry_path.exists():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        for item in payload.get("items", []):
            owner = item.get("owner_user_id")
            if owner:
                old_workspaces[owner] = item.get("default_workdir", "")

    for row in rows:
        username = row["username"]
        _LOG.info("--- Migrating user: %s ---", username)

        new_workspace_dir = _create_user(username)

        old_dir_str = old_workspaces.get(username)
        old_dir = Path(old_dir_str) if old_dir_str else None
        _migrate_workspace_files(username, old_dir, new_workspace_dir)

        _update_workspace_registry(state_root, username, new_workspace_dir)

    _LOG.info("=== Migration complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate OpenScience users to tenant isolation")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path("/opt/ainrf/state"),
        help="OpenScience state root directory (default: /opt/ainrf/state)",
    )
    args = parser.parse_args()
    main(args.state_root)

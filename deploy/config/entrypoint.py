#!/usr/bin/env python3
"""OpenScience Docker entrypoint.

- Generates ~/.claude/settings.json, ~/.claude/CLAUDE.md and ~/.codex/ config files
  from templates, substituting environment variables where needed.
- Then execs the OpenScience server.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from re import Match

HOME = Path(os.environ.get("HOME", "/opt/ainrf"))


def _substitute(text: str) -> str:
    """Replace ${VAR} patterns with environment variable values."""

    def _repl(m: Match[str]) -> str:
        val: str | None = os.environ.get(m.group(1))
        if val is None:
            return m.group(0)
        return val

    return re.sub(r"\$\{(\w+)\}", _repl, text)


def _generate_claude_settings() -> None:
    """Generate ~/.claude/settings.json from template."""
    tpl_path = Path("/opt/ainrf/config/claude-settings.json")
    if not tpl_path.exists():
        return

    out_dir = HOME / ".claude"
    out_dir.mkdir(parents=True, exist_ok=True)

    text = _substitute(tpl_path.read_text(encoding="utf-8"))
    json.loads(text)  # validate
    (out_dir / "settings.json").write_text(text, encoding="utf-8")
    print(f"[entrypoint] Generated {out_dir / 'settings.json'}")


def _generate_codex_config() -> None:
    """Generate ~/.codex/config.toml and auth.json from templates."""
    cfg_tpl = Path("/opt/ainrf/config/codex-config.toml")
    auth_tpl = Path("/opt/ainrf/config/codex-auth.json")

    out_dir = HOME / ".codex"
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg_tpl.exists():
        text = _substitute(cfg_tpl.read_text(encoding="utf-8"))
        (out_dir / "config.toml").write_text(text, encoding="utf-8")
        print(f"[entrypoint] Generated {out_dir / 'config.toml'}")

    if auth_tpl.exists():
        text = _substitute(auth_tpl.read_text(encoding="utf-8"))
        json.loads(text)  # validate
        (out_dir / "auth.json").write_text(text, encoding="utf-8")
        print(f"[entrypoint] Generated {out_dir / 'auth.json'}")


def _generate_claude_md() -> None:
    """Copy the operator CLAUDE.md guardrail into ~/.claude/CLAUDE.md.

    This file is baked into the Docker image at ``/opt/ainrf/config/CLAUDE.md``
    and is re-applied on every container restart.  Unlike ``settings.json``,
    it does NOT use env-var substitution — it is a static document of behavioral
    constraints (PDF chunking, large-file handling, JSON buffer limits, etc.).
    """
    src = Path("/opt/ainrf/config/CLAUDE.md")
    if not src.is_file():
        print("[entrypoint] CLAUDE.md template not found, skipping")
        return

    out_dir = HOME / ".claude"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out_dir / "CLAUDE.md")
    print(f"[entrypoint] Installed {out_dir / 'CLAUDE.md'}")


def _start_sshd() -> None:
    """Start sshd on an alternate port so localhost self-test works.

    In host-network deployments the host sshd already owns port 22,
    so the container must use an alternate port.  The port is
    configurable via ``AINRF_SSHD_PORT`` (default: 2222) so that
    staging environments running alongside production on the same
    host can each bind their own port without collision.
    """
    if os.environ.get("OPENSCIENCE_NO_SSHD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        print("[entrypoint] sshd disabled for this process", flush=True)
        return

    port = os.environ.get("AINRF_SSHD_PORT", "2222")

    try:
        subprocess.Popen(
            ["/usr/sbin/sshd", "-p", port],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[entrypoint] sshd started on port {port}", flush=True)
    except FileNotFoundError:
        print("[entrypoint] sshd not found, skipping", flush=True)
    except OSError as exc:
        print(f"[entrypoint] sshd failed to start: {exc}", flush=True)


def _sync_aris_skills() -> None:
    """Sync ARIS skills from the bundled repo into the default workspace.

    On first startup, copies the bundled ARIS repo into the git-sync
    directory and syncs all skills to the load directory.
    On subsequent startups, compares the bundled repo's skill set with
    the installed manifest and re-syncs when the Docker image has been
    rebuilt with a newer ARIS version.

    Runs *before* privilege drop so it can write to the shared workspace.
    """
    from ainrf.skills.registry_models import DEFAULT_REGISTRIES
    from ainrf.skills.registry_sync import SkillRegistrySyncService

    aris_config = next((r for r in DEFAULT_REGISTRIES if r.registry_id == "aris"), None)
    if aris_config is None:
        return

    aris_source = Path("/opt/ainrf/aris-repo")
    if not (aris_source / "skills").is_dir():
        print("[entrypoint] ARIS skill source not found, skipping skill sync")
        return

    workspace_dir = HOME / ".ainrf_workspaces" / "default"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    load_dir = workspace_dir / "skills"

    service = SkillRegistrySyncService(
        registry=aris_config,
        workspace_dir=workspace_dir,
        load_dir=load_dir,
    )

    if not service.needs_resync(aris_source):
        print("[entrypoint] ARIS skills up to date")
        return

    try:
        added, removed = service.resync_from_source(aris_source)
        n_total = len(service._read_manifest().get("skills", []))
        parts: list[str] = [f"{n_total} skills"]
        if added:
            parts.append(f"{len(added)} added")
        if removed:
            parts.append(f"{len(removed)} removed")
        print(f"[entrypoint] ARIS skills synced ({', '.join(parts)})")
    except RuntimeError as exc:
        print(f"[entrypoint] ARIS skill sync failed: {exc}")


def _provision_tenant_users(state_root: str) -> None:
    """Ensure ainrf_tenants group and per-user Linux accounts exist.

    Called at container startup while still running as root.
    Container /etc/passwd resets on every restart, but the auth SQLite
    database persists in the named volume. This re-creates Linux users
    for every registered user, so tenant isolation works across restarts.
    """
    import sqlite3

    TENANT_GID = 2000
    TENANT_GROUP = "ainrf_tenants"
    HOME_ROOT = Path("/home/ainrf_tenants")
    auth_db = Path(state_root) / "runtime" / "auth.sqlite3"
    if not auth_db.exists():
        return

    # 1. Ensure the tenant group exists
    res = subprocess.run(["getent", "group", TENANT_GROUP],
                         capture_output=True, text=True)
    if res.returncode != 0:
        subprocess.run(["groupadd", "--gid", str(TENANT_GID), TENANT_GROUP],
                       check=True, capture_output=True, text=True)
        print(f"[entrypoint] Created group {TENANT_GROUP} (gid {TENANT_GID})",
              flush=True)

    # 2. Read all usernames from auth DB and ensure Linux users exist
    try:
        conn = sqlite3.connect(str(auth_db))
        rows = conn.execute("SELECT username FROM users").fetchall()
        conn.close()
    except Exception as exc:
        print(f"[entrypoint] Could not read auth DB for tenant provisioning: {exc}",
              flush=True)
        return

    created = 0
    for (username,) in rows:
        linux_user = f"ainrf_{username}"
        home = HOME_ROOT / username
        workspace = home / "workspaces" / "default"

        res = subprocess.run(["id", linux_user], capture_output=True, text=True)
        if res.returncode == 0:
            continue  # user already exists

        subprocess.run(
            [
                "useradd",
                "--gid", str(TENANT_GID),
                "--home-dir", str(home),
                "--create-home",
                "--shell", "/bin/bash",
                linux_user,
            ],
            check=True, capture_output=True, text=True,
        )
        home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["chown", "-R", f"{linux_user}:{TENANT_GROUP}", str(home)],
            check=True, capture_output=True, text=True,
        )
        created += 1

    if created:
        print(f"[entrypoint] Provisioned {created} tenant Linux user(s)", flush=True)

    # 3. Sync default Codex credentials into every tenant home so that
    #    sudo -u <tenant> codex app-server can read ~/.codex/config.toml
    #    and ~/.codex/auth.json after sudo resets HOME.  Refreshed on
    #    every container restart so credential rotation takes effect.
    codex_src = Path("/opt/ainrf/.codex")
    if codex_src.is_dir():
        synced = 0
        for (username,) in rows:
            tenant_codex = HOME_ROOT / username / ".codex"
            shutil.rmtree(tenant_codex, ignore_errors=True)
            shutil.copytree(str(codex_src), str(tenant_codex), symlinks=True)
            subprocess.run(
                ["chown", "-R", f"ainrf_{username}:{TENANT_GROUP}", str(tenant_codex)],
                check=False, capture_output=True, text=True,
            )
            synced += 1
        if synced:
            print(f"[entrypoint] Synced Codex credentials to {synced} tenant(s)", flush=True)


def main() -> None:
    _start_sshd()
    _generate_claude_settings()
    _generate_claude_md()
    _generate_codex_config()
    _sync_aris_skills()

    # Drop privileges to ainrf user (UID 1000) before exec-ing the server
    _uid = 1000
    _gid = 1000
    if os.getuid() == 0:
        import subprocess

        for d in ("/opt/ainrf/state", "/opt/ainrf/.ainrf_workspaces", "/opt/ainrf/.claude"):
            subprocess.run(
                ["chown", "-R", f"{_uid}:{_gid}", d],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Ensure tenant group and Linux users exist (container /etc/passwd
        # resets on restart — the auth DB in the named volume persists but
        # the Linux accounts do not).
        _provision_tenant_users("/opt/ainrf/state")

        os.setgid(_gid)
        os.setuid(_uid)
        os.environ["HOME"] = "/opt/ainrf"
        os.environ["USER"] = "ainrf"
        print("[entrypoint] Dropped privileges to ainrf (uid=1000)", flush=True)

    cmd = sys.argv[1:]
    if not cmd:
        cmd = [
            "python",
            "-m",
            "ainrf",
            "serve",
            "--host",
            os.environ.get("AINRF_HOST", "0.0.0.0"),
            "--port",
            os.environ.get("AINRF_PORT", "8000"),
            "--state-root",
            "/opt/ainrf/state",
        ]

    print(f"[entrypoint] Exec: {' '.join(cmd)}")
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()

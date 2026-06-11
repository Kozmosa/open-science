#!/usr/bin/env python3
"""AINRF Docker entrypoint.

- Generates ~/.claude/settings.json and ~/.codex/ config files
  from templates, substituting environment variables.
- Then execs the ainrf server.
"""

import json
import os
import re
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


def _start_sshd() -> None:
    """Start sshd on port 2222 so localhost self-test works.

    In host-network deployments the host sshd already owns port 22,
    so the container must use an alternate port.
    """
    import subprocess

    try:
        subprocess.Popen(
            ["/usr/sbin/sshd", "-p", "2222"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[entrypoint] sshd started on port 2222", flush=True)
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


def main() -> None:
    _start_sshd()
    _generate_claude_settings()
    _generate_codex_config()
    _sync_aris_skills()

    # Drop privileges to ainrf user (UID 1000) before exec-ing the server
    _uid = 1000
    _gid = 1000
    if os.getuid() == 0:
        # Ensure volume directories are owned by ainrf (Docker named volumes
        # may be owned by root on first mount)
        import subprocess

        for d in ("/opt/ainrf/state", "/opt/ainrf/.ainrf_workspaces"):
            subprocess.run(
                ["chown", "-R", f"{_uid}:{_gid}", d],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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

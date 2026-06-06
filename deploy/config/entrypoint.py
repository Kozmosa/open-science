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


def main() -> None:
    _generate_claude_settings()
    _generate_codex_config()

    # Exec the actual server command
    cmd = sys.argv[1:]
    if not cmd:
        cmd = [
            "python", "-m", "ainrf", "serve",
            "--host", os.environ.get("AINRF_HOST", "0.0.0.0"),
            "--port", os.environ.get("AINRF_PORT", "8000"),
            "--state-root", "/opt/ainrf/state",
        ]

    print(f"[entrypoint] Exec: {' '.join(cmd)}")
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()

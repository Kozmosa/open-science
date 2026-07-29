"""Linux tenant identity conventions shared by runtime adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path

TENANT_GROUP = "ainrf_tenants"
TENANT_GID = 2000
TENANT_HOME_ROOT = Path("/home/ainrf_tenants")


def is_container_environment() -> bool:
    """Return whether tenant Linux isolation is expected in this runtime."""

    return Path("/opt/ainrf/state").is_dir() or Path("/.dockerenv").exists()


def linux_user_exists(username: str) -> bool:
    """Return whether a Linux account exists without mutating host state."""

    return subprocess.run(["id", username], capture_output=True).returncode == 0


def tenant_linux_username(openscience_username: str) -> str:
    """Map an OpenScience username to its isolated Linux account name."""

    return f"ainrf_{openscience_username}"


def tenant_home_dir(openscience_username: str) -> Path:
    """Return the conventional home directory for an OpenScience tenant."""

    return TENANT_HOME_ROOT / openscience_username

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "install.sh"


def test_install_script_exists() -> None:
    assert SCRIPT_PATH.exists(), f"install.sh not found at {SCRIPT_PATH}"


def test_install_script_is_executable() -> None:
    assert SCRIPT_PATH.stat().st_mode & 0o111, "install.sh is not executable"


def test_install_script_help() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--yes" in result.stdout
    assert "--no-start" in result.stdout


def test_install_script_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_install_script_unknown_flag() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--unknown"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Unknown option" in result.stderr

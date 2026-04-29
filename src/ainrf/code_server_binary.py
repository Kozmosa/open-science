from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CodeServerBinarySource = Literal["configured", "path", "managed_install", "missing"]

MANAGED_CODE_SERVER_INSTALL_ROOT = Path.home() / ".local" / "ainrf" / "code-server"
_CODE_SERVER_DIR_PATTERN = re.compile(r"^code-server-(\d+)\.(\d+)\.(\d+)-linux-amd64$")
_CODE_SERVER_MISSING_DETAIL = (
    "Install code-server from Settings before using the workspace browser, or call "
    "POST /environments/env-localhost/install-code-server."
)


@dataclass(frozen=True, slots=True)
class CodeServerBinaryResolution:
    available: bool
    path: str | None
    source: CodeServerBinarySource
    detail: str | None = None


def resolve_local_code_server_binary(
    configured_path: str | None = None,
    *,
    managed_install_root: Path = MANAGED_CODE_SERVER_INSTALL_ROOT,
) -> CodeServerBinaryResolution:
    if (
        configured_path
        and Path(configured_path).is_file()
        and Path(configured_path).stat().st_mode & 0o111
    ):
        return CodeServerBinaryResolution(True, configured_path, "configured")

    path_binary = shutil.which("code-server")
    if path_binary is not None:
        return CodeServerBinaryResolution(True, path_binary, "path")

    managed_binary = newest_managed_code_server_binary(managed_install_root)
    if managed_binary is not None:
        return CodeServerBinaryResolution(True, str(managed_binary), "managed_install")

    return CodeServerBinaryResolution(False, None, "missing", _CODE_SERVER_MISSING_DETAIL)


def newest_managed_code_server_binary(managed_install_root: Path) -> Path | None:
    candidates: list[tuple[tuple[int, int, int], Path]] = []
    if not managed_install_root.exists():
        return None
    for child in managed_install_root.iterdir():
        match = _CODE_SERVER_DIR_PATTERN.fullmatch(child.name)
        if match is None:
            continue
        binary = child / "bin" / "code-server"
        if not binary.is_file() or not binary.stat().st_mode & 0o111:
            continue
        version = tuple(int(part) for part in match.groups())
        candidates.append((version, binary))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def code_server_missing_detail() -> str:
    return _CODE_SERVER_MISSING_DETAIL

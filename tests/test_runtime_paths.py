from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.runtime.paths import build_runtime_path_config


def test_runtime_path_config_workspace_root_uses_startup_cwd() -> None:
    startup_cwd = Path("/tmp/ainrf-project")

    paths = build_runtime_path_config(startup_cwd)

    assert paths.startup_cwd == startup_cwd
    assert paths.workspace_root == startup_cwd / "workspace"
    assert paths.default_workspace_dir == Path.home() / ".ainrf_workspaces" / "default"


def test_runtime_path_config_defaults_to_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    paths = build_runtime_path_config()

    assert paths.startup_cwd == tmp_path.resolve()
    assert paths.default_workspace_dir == Path.home() / ".ainrf_workspaces" / "default"

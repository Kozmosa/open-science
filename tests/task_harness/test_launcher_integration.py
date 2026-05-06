from __future__ import annotations

from pathlib import Path

from ainrf.task_harness.launcher import build_local_launcher


def test_build_local_launcher_prefers_ainrf_settings(tmp_path: Path) -> None:
    ainrf_dir = tmp_path / ".ainrf"
    ainrf_dir.mkdir(parents=True, exist_ok=True)
    ainrf_settings = ainrf_dir / "settings.json"
    ainrf_settings.write_text('{"permissionMode": "bypassPermissions"}', encoding="utf-8")

    other_settings = tmp_path / "other_settings.json"
    other_settings.write_text('{"permissionMode": "ask"}', encoding="utf-8")

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test prompt", encoding="utf-8")

    payload, _launch = build_local_launcher(
        working_directory=str(tmp_path),
        prompt_file=prompt_file,
        rendered_prompt="test prompt",
        settings_path=str(other_settings),
    )

    assert "--settings" in payload.command
    settings_idx = payload.command.index("--settings")
    assert payload.command[settings_idx + 1] == str(ainrf_settings)


def test_build_local_launcher_falls_back_to_settings_path(tmp_path: Path) -> None:
    other_settings = tmp_path / "other_settings.json"
    other_settings.write_text('{"permissionMode": "ask"}', encoding="utf-8")

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test prompt", encoding="utf-8")

    payload, _launch = build_local_launcher(
        working_directory=str(tmp_path),
        prompt_file=prompt_file,
        rendered_prompt="test prompt",
        settings_path=str(other_settings),
    )

    assert "--settings" in payload.command
    settings_idx = payload.command.index("--settings")
    assert payload.command[settings_idx + 1] == str(other_settings)


def test_build_local_launcher_no_settings(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test prompt", encoding="utf-8")

    payload, _launch = build_local_launcher(
        working_directory=str(tmp_path),
        prompt_file=prompt_file,
        rendered_prompt="test prompt",
        settings_path=None,
    )

    assert "--settings" not in payload.command

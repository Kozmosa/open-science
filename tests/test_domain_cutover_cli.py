"""CLI contract tests for the durable domain cutover controller."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ainrf.cli import app

pytestmark = [pytest.mark.cli]

runner = CliRunner()


class _Result:
    def __init__(self, state: str) -> None:
        self._state = state

    def as_dict(self) -> dict[str, object]:
        return {"state": self._state}


def test_domain_cutover_help_lists_controller_operations() -> None:
    result = runner.invoke(app, ["domain-cutover", "--help"])

    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "prepare" in result.stdout
    assert "commit" in result.stdout
    assert "abort" in result.stdout


def test_domain_cutover_prepare_passes_exact_bound_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class FakeController:
        def prepare(self, **kwargs: object) -> _Result:
            captured.update(kwargs)
            return _Result("prepared")

    monkeypatch.setattr("ainrf.cli._cutover_controller", lambda _: FakeController())
    archive = tmp_path / "backup.tar.gz"
    result = runner.invoke(
        app,
        [
            "domain-cutover",
            "prepare",
            "run-1",
            str(archive),
            "--actor-id",
            "operator-1",
            "--artifact-sha",
            "a" * 64,
            "--artifact-contract-min",
            "2",
            "--artifact-contract-max",
            "2",
            "--artifact-schema-min",
            "18",
            "--artifact-schema-max",
            "18",
            "--stability-window-seconds",
            "0",
            "--state-root",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"state": "prepared"}
    assert captured == {
        "actor_id": "operator-1",
        "run_id": "run-1",
        "backup_archive": archive,
        "artifact_sha": "a" * 64,
        "artifact_contract_min": 2,
        "artifact_contract_max": 2,
        "artifact_schema_min": 18,
        "artifact_schema_max": 18,
        "stability_window_seconds": 0.0,
    }

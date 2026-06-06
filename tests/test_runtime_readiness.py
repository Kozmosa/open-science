from __future__ import annotations

import pytest

from ainrf.runtime.readiness import check_runtime_readiness

pytestmark = [pytest.mark.unit]

def test_runtime_readiness_reports_missing_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ainrf.runtime.readiness.shutil.which", lambda name: None)

    readiness = check_runtime_readiness()

    payload = readiness.as_public_payload()
    assert payload["ready"] is False
    assert payload["dependencies"]["tmux"]["available"] is False
    assert payload["dependencies"]["uv"]["available"] is False
    tmux_detail = payload["dependencies"]["tmux"]["detail"]
    assert tmux_detail is not None
    assert "Install tmux" in tmux_detail


def test_runtime_readiness_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ainrf.runtime.readiness.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    readiness = check_runtime_readiness()

    payload = readiness.as_public_payload()
    assert payload["ready"] is True
    assert payload["dependencies"]["tmux"]["available"] is True
    assert payload["dependencies"]["uv"]["available"] is True

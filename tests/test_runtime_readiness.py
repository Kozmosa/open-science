from __future__ import annotations

import pytest

from ainrf.runtime.readiness import check_runtime_readiness


def test_runtime_readiness_reports_missing_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ainrf.runtime.readiness.shutil.which", lambda name: None)

    readiness = check_runtime_readiness()

    payload = readiness.as_public_payload()
    assert payload["ready"] is False
    assert payload["dependencies"]["tmux"]["available"] is False
    assert payload["dependencies"]["uv"]["available"] is False
    assert payload["dependencies"]["code_server"]["available"] is False
    tmux_detail = payload["dependencies"]["tmux"]["detail"]
    code_server_detail = payload["dependencies"]["code_server"]["detail"]
    assert tmux_detail is not None
    assert "Install tmux" in tmux_detail
    assert code_server_detail is not None
    assert "Settings" in code_server_detail
    assert "install-code-server" in code_server_detail


def test_runtime_readiness_uses_configured_code_server_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ainrf.runtime.readiness.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"tmux", "uv"} else None,
    )

    readiness = check_runtime_readiness("/opt/code-server/bin/code-server")

    payload = readiness.as_public_payload()
    assert payload["ready"] is True
    assert payload["dependencies"]["code_server"] == {
        "available": True,
        "path": "/opt/code-server/bin/code-server",
        "detail": None,
    }

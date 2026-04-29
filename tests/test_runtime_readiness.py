from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.code_server_binary import resolve_local_code_server_binary
from ainrf.runtime.readiness import check_runtime_readiness


def test_code_server_resolver_uses_newest_managed_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("ainrf.code_server_binary.shutil.which", lambda name: None)
    older = tmp_path / "code-server-4.116.1-linux-amd64" / "bin" / "code-server"
    newer = tmp_path / "code-server-4.117.0-linux-amd64" / "bin" / "code-server"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_text("", encoding="utf-8")
    newer.write_text("", encoding="utf-8")
    older.chmod(0o755)
    newer.chmod(0o755)

    result = resolve_local_code_server_binary(managed_install_root=tmp_path)

    assert result.available is True
    assert result.path == str(newer)
    assert result.source == "managed_install"


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
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "ainrf.runtime.readiness.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"tmux", "uv"} else None,
    )
    code_server = tmp_path / "bin" / "code-server"
    code_server.parent.mkdir()
    code_server.write_text("", encoding="utf-8")
    code_server.chmod(0o755)

    readiness = check_runtime_readiness(str(code_server))

    payload = readiness.as_public_payload()
    assert payload["ready"] is True
    assert payload["dependencies"]["code_server"] == {
        "available": True,
        "path": str(code_server),
        "detail": None,
    }

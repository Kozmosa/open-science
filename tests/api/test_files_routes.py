from __future__ import annotations

from pathlib import Path

import pytest

from tests.testutil import make_client
from ainrf.api.config import ApiConfig


pytestmark = [pytest.mark.api]


def _make_app_and_workdir(tmp_path: Path, *, max_file_size_bytes: int | None = None):
    """Backward compat: returns (app, workdir) from a throwaway ApiConfig."""
    api_config = ApiConfig(
        api_key_hashes=frozenset(),
        state_root=tmp_path,
    )
    workdir = api_config.runtime_paths.ensure_default_workspace_dir()
    return None, workdir


@pytest.mark.anyio
async def test_list_files_localhost(tmp_path: Path) -> None:
    _, workdir = _make_app_and_workdir(tmp_path)
    (workdir / "README.md").write_text("# Hello")
    subdir = workdir / "src"
    subdir.mkdir(exist_ok=True)
    (subdir / "main.py").write_text("print('hello')")

    async with make_client(tmp_path) as client:
        response = await client.get("/files/list?environment_id=env-localhost&path=")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(workdir)
    names = {e["name"] for e in payload["entries"]}
    assert "README.md" in names
    assert "src" in names


@pytest.mark.anyio
async def test_list_files_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/files/list?environment_id=env-localhost&path=/nonexistent")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_read_file_localhost(tmp_path: Path) -> None:
    _, workdir = _make_app_and_workdir(tmp_path)
    (workdir / "hello.txt").write_text("world")

    async with make_client(tmp_path) as client:
        response = await client.get("/files/read?environment_id=env-localhost&path=hello.txt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(workdir / "hello.txt")
    assert payload["content"] == "world"
    assert payload["is_binary"] is False
    assert payload["language"] is None


@pytest.mark.anyio
async def test_read_file_with_language(tmp_path: Path) -> None:
    _, workdir = _make_app_and_workdir(tmp_path)
    (workdir / "main.py").write_text("print('hello')")

    async with make_client(tmp_path) as client:
        response = await client.get("/files/read?environment_id=env-localhost&path=main.py")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "python"


@pytest.mark.anyio
async def test_read_file_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get("/files/read?environment_id=env-localhost&path=missing.txt")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_read_file_too_large(tmp_path: Path) -> None:
    _, workdir = _make_app_and_workdir(tmp_path, max_file_size_bytes=1_048_576)
    (workdir / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    async with make_client(tmp_path, max_file_size_bytes=1_048_576) as client:
        response = await client.get("/files/read?environment_id=env-localhost&path=big.bin")

    assert response.status_code == 413


@pytest.mark.anyio
async def test_stream_file_localhost_sets_frame_options(tmp_path: Path) -> None:
    _, workdir = _make_app_and_workdir(tmp_path)
    (workdir / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf content")

    async with make_client(tmp_path) as client:
        response = await client.get("/files/stream?environment_id=env-localhost&path=report.pdf")

    assert response.status_code == 200
    assert response.headers.get("x-frame-options") == "SAMEORIGIN"
    assert response.headers.get("content-type") == "application/pdf"

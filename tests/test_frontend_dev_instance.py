from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ainrf.development import instance as instance_module
from ainrf.development.instance import (
    ensure_frontend_dev_instance,
    resolve_frontend_dev_instance,
)


pytestmark = [pytest.mark.cli]


def _stub_git(monkeypatch: pytest.MonkeyPatch, branch: str, head: str = "a" * 40) -> None:
    def fake_git_value(repo_root: Path, *args: str) -> str:
        del repo_root
        if args == ("rev-parse", "HEAD"):
            return head
        if args == ("branch", "--show-current"):
            return branch
        raise AssertionError(args)

    monkeypatch.setattr(instance_module, "_git_value", fake_git_value)


def test_instance_identity_and_ports_are_stable_per_worktree_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    development_root = tmp_path / "runtime"
    _stub_git(monkeypatch, "feat/frontend-phases")
    env = {"OPENSCIENCE_DEV_ROOT": str(development_root)}

    first = resolve_frontend_dev_instance(repo_root, profile="full", env=env)
    second = resolve_frontend_dev_instance(repo_root, profile="full", env=env)
    empty = resolve_frontend_dev_instance(repo_root, profile="empty", env=env)

    assert second == first
    assert first.instance_id.startswith("feat-frontend-phases-full-")
    assert first.instance_root.parent == development_root
    assert first.state_root == first.instance_root / "state"
    assert first.login_credentials_path == (
        first.instance_root / "runtime" / "frontend-login-identities.json"
    )
    assert 41000 <= first.ports.frontend <= 43997
    assert first.ports.api == first.ports.frontend + 1
    assert first.ports.cdp == first.ports.frontend + 2
    assert empty.instance_id != first.instance_id
    assert empty.ports != first.ports


def test_instance_supports_detached_head_and_explicit_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    _stub_git(monkeypatch, "", head="12345678" + "b" * 32)

    instance = resolve_frontend_dev_instance(
        repo_root,
        env={
            "OPENSCIENCE_DEV_ROOT": str(tmp_path / "runtime"),
            "OPENSCIENCE_DEV_FRONTEND_PORT": "45173",
            "OPENSCIENCE_DEV_API_PORT": "48000",
            "OPENSCIENCE_DEV_CDP_PORT": "49222",
            "OPENSCIENCE_DEV_BIND_HOST": "0.0.0.0",
        },
    )

    assert instance.branch == "detached-12345678"
    assert instance.ports.frontend == 45173
    assert instance.ports.api == 48000
    assert instance.ports.cdp == 49222
    assert instance.bind_host == "0.0.0.0"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENSCIENCE_DEV_FRONTEND_PORT", "abc"),
        ("OPENSCIENCE_DEV_API_PORT", "80"),
        ("OPENSCIENCE_DEV_CDP_PORT", "70000"),
    ],
)
def test_instance_rejects_invalid_port_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    _stub_git(monkeypatch, "feat/frontend-phases")

    with pytest.raises(ValueError, match=name):
        resolve_frontend_dev_instance(
            repo_root,
            env={
                "OPENSCIENCE_DEV_ROOT": str(tmp_path / "runtime"),
                name: value,
            },
        )


def test_instance_rejects_runtime_root_inside_git_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    (repo_root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    _stub_git(monkeypatch, "feat/frontend-phases")

    with pytest.raises(ValueError, match="outside every Git worktree"):
        resolve_frontend_dev_instance(
            repo_root,
            env={"OPENSCIENCE_DEV_ROOT": str(repo_root / ".runtime")},
        )


def test_instance_key_is_stable_private_and_absent_from_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()
    _stub_git(monkeypatch, "feat/frontend-phases")
    instance = resolve_frontend_dev_instance(
        repo_root,
        env={"OPENSCIENCE_DEV_ROOT": str(tmp_path / "runtime")},
    )

    first_key = ensure_frontend_dev_instance(instance)
    second_key = ensure_frontend_dev_instance(instance)
    marker = json.loads(instance.marker_path.read_text(encoding="utf-8"))

    assert second_key == first_key
    assert first_key not in instance.marker_path.read_text(encoding="utf-8")
    assert marker["instance_id"] == instance.instance_id
    assert marker["ports"] == {
        "api": instance.ports.api,
        "cdp": instance.ports.cdp,
        "frontend": instance.ports.frontend,
    }
    assert marker["login_credentials_path"] == str(instance.login_credentials_path)
    assert stat.S_IMODE(instance.credential_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((instance.runtime_root / "home").stat().st_mode) == 0o700

from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path
from typing import cast

import pytest

from ainrf.api.config import hash_api_key
from ainrf.development import instance as instance_module
from ainrf.development import stack as stack_module
from ainrf.development.instance import (
    FrontendDevInstance,
    ensure_frontend_dev_instance,
    resolve_frontend_dev_instance,
)
from ainrf.development.stack import (
    DevelopmentProcessRecord,
    DevelopmentStack,
    DevelopmentStackError,
    DevelopmentStackMode,
    DevelopmentStackStatus,
)


pytestmark = [pytest.mark.cli]


def _instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FrontendDevInstance:
    repo_root = tmp_path / "worktree"
    repo_root.mkdir()

    def fake_git_value(path: Path, *args: str) -> str:
        assert path == repo_root
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        if args == ("branch", "--show-current"):
            return "feat/frontend-phases"
        raise AssertionError(args)

    monkeypatch.setattr(instance_module, "_git_value", fake_git_value)
    return resolve_frontend_dev_instance(
        repo_root,
        env={"OPENSCIENCE_DEV_ROOT": str(tmp_path / "runtime")},
    )


def test_stack_environment_keeps_proxy_key_out_of_browser_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(instance, artifact_sha="b" * 64, api_key="private-dev-key")

    environment = stack.environment()

    assert environment["OPENSCIENCE_STATE_ROOT"] == str(instance.state_root)
    assert environment["OPENSCIENCE_WEBUI_API_KEY"] == "private-dev-key"
    assert environment["OPENSCIENCE_API_KEY_HASHES"] == hash_api_key("private-dev-key")
    assert environment["OPENSCIENCE_DOMAIN_MODEL_MODE"] == "v2"
    assert environment["OPENSCIENCE_DOMAIN_ARTIFACT_SHA"] == "b" * 64
    assert "VITE_OPENSCIENCE_API_KEY" not in environment
    assert "VITE_AINRF_API_KEY" not in environment


def test_stack_prepare_runs_selected_profile_and_parses_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(instance, artifact_sha="c" * 64, api_key="fixture-key")
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            command=command,
            cwd=cwd,
            env=env,
            check=check,
            capture_output=capture_output,
            text=text,
        )
        return subprocess.CompletedProcess(command, 0, '{"profile":"full","counts":{}}\n', "")

    monkeypatch.setattr(stack_module.subprocess, "run", fake_run)

    payload = stack.prepare()

    assert payload["profile"] == "full"
    assert captured["cwd"] == instance.repo_root
    assert captured["command"] == [
        "uv",
        "run",
        "openscience",
        "frontend-dev",
        "prepare",
        "--state-root",
        str(instance.state_root),
        "--api-key",
        "fixture-key",
        "--credentials-path",
        str(instance.login_credentials_path),
        "--artifact-sha",
        "c" * 64,
        "--profile",
        "full",
    ]


def test_stack_status_manifest_is_machine_readable_and_secret_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(instance, artifact_sha="d" * 64, api_key="never-in-manifest")
    records = [
        DevelopmentProcessRecord("api", 101, "1", ("api",), str(instance.log_root / "api.log")),
        DevelopmentProcessRecord(
            "worker", 102, "2", ("worker",), str(instance.log_root / "worker.log")
        ),
        DevelopmentProcessRecord(
            "frontend", 103, "3", ("frontend",), str(instance.log_root / "frontend.log")
        ),
    ]
    monkeypatch.setattr(stack_module, "_record_is_alive", lambda record: True)
    monkeypatch.setattr(stack_module, "_http_healthy", lambda url: True)
    stack._write_manifest(records)

    status = stack.status()
    manifest_text = stack.manifest_path.read_text(encoding="utf-8")

    assert status.state == "healthy"
    assert status.payload["schema_version"] == 1
    services = cast(dict[str, object], status.payload["services"])
    assert set(services) == {"api", "worker", "frontend"}
    assert "never-in-manifest" not in manifest_text
    assert json.loads(manifest_text)["instance_id"] == instance.instance_id


def test_stack_down_only_signals_owned_manifest_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(instance, artifact_sha="e" * 64, api_key="fixture-key")
    records = [
        DevelopmentProcessRecord("api", 201, "1", ("api",), str(instance.log_root / "api.log")),
        DevelopmentProcessRecord(
            "frontend", 202, "2", ("frontend",), str(instance.log_root / "frontend.log")
        ),
    ]
    stack._write_manifest(records)
    alive = {201: True, 202: True}
    signals: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr(stack_module, "_record_is_alive", lambda record: alive[record.pid])
    monkeypatch.setattr(stack_module.os, "getpgid", lambda pid: pid + 1000)

    def fake_killpg(pgid: int, sig: signal.Signals) -> None:
        signals.append((pgid, sig))
        alive[pgid - 1000] = False

    monkeypatch.setattr(stack_module.os, "killpg", fake_killpg)

    status = stack.down()

    assert status.state == "stopped"
    assert signals == [(1202, signal.SIGTERM), (1201, signal.SIGTERM)]
    assert not stack.manifest_path.exists()


def test_stack_reset_refuses_personal_or_unmarked_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    personal = DevelopmentStack(
        instance,
        artifact_sha="f" * 64,
        api_key="fixture-key",
        personal_state_root=tmp_path / "personal",
    )
    managed = DevelopmentStack(instance, artifact_sha="f" * 64, api_key="fixture-key")
    instance.instance_root.mkdir(parents=True)

    with pytest.raises(DevelopmentStackError, match="personal"):
        personal.reset()
    with pytest.raises(DevelopmentStackError, match="managed instance marker"):
        managed.reset()


def test_stack_refuses_to_take_over_unowned_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    ensure_frontend_dev_instance(instance)
    stack = DevelopmentStack(instance, artifact_sha="1" * 64, api_key="fixture-key")
    monkeypatch.setattr(stack_module, "_port_available", lambda host, port: False)

    with pytest.raises(DevelopmentStackError, match="unowned process"):
        stack.up()


def test_stack_uses_reload_for_dev_and_stable_server_for_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    development = DevelopmentStack(
        instance,
        artifact_sha="2" * 64,
        api_key="fixture-key",
        mode=DevelopmentStackMode.DEV,
    )
    preview = DevelopmentStack(
        instance,
        artifact_sha="2" * 64,
        api_key="fixture-key",
        mode=DevelopmentStackMode.PREVIEW,
    )

    dev_command = development._api_command()
    preview_command = preview._api_command()

    assert dev_command[:5] == (
        "uv",
        "run",
        "uvicorn",
        "ainrf.server:create_development_app",
        "--factory",
    )
    assert "--reload" in dev_command
    assert str(instance.repo_root / "src" / "ainrf") in dev_command
    assert preview_command[:4] == ("uv", "run", "openscience", "serve")
    assert "--reload" not in preview_command


def test_preview_build_runs_production_frontend_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(
        instance,
        artifact_sha="3" * 64,
        api_key="fixture-key",
        mode=DevelopmentStackMode.PREVIEW,
    )
    captured: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(stack_module.subprocess, "run", fake_run)

    stack._build_frontend_preview()

    assert captured["command"] == (
        "npm",
        "--prefix",
        str(instance.repo_root / "frontend"),
        "run",
        "build",
    )
    assert (instance.log_root / "frontend-build.log").exists()


def test_stack_smoke_reads_v2_projections_through_frontend_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path, monkeypatch)
    stack = DevelopmentStack(instance, artifact_sha="4" * 64, api_key="fixture-key")
    monkeypatch.setattr(
        stack,
        "status",
        lambda: DevelopmentStackStatus(state="healthy", payload={"state": "healthy"}),
    )

    def fake_text(url: str) -> str:
        if url.endswith("/"):
            return '<html><div id="root"></div><script src="/src/main.tsx"></script></html>'
        if url.endswith("/src/main.tsx"):
            return "export {}"
        raise AssertionError(url)

    def fake_json(url: str) -> dict[str, object]:
        if url.endswith("/api/health"):
            return {"status": "ok"}
        if url.endswith("/api/domain/capabilities"):
            return {"domain_contract_version": 2, "mode": "v2"}
        if url.endswith("/api/domain/projects"):
            return {"items": [{"project_id": "project-1"}]}
        if url.endswith("/api/domain/workspaces"):
            return {"items": [{"workspace_id": "workspace-1"}]}
        raise AssertionError(url)

    monkeypatch.setattr(stack_module, "_fetch_http_text", fake_text)
    monkeypatch.setattr(stack_module, "_fetch_http_json", fake_json)

    payload = stack.smoke()

    checks = cast(dict[str, object], payload["checks"])
    assert checks["frontend_index"] is True
    assert checks["projects"] == 1
    assert checks["workspaces"] == 1

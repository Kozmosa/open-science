import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "deepxiv_fetch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("deepxiv_fetch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ensure_deepxiv_installed_returns_error_when_binary_missing(monkeypatch):
    deepxiv_fetch = load_module()
    monkeypatch.setattr(deepxiv_fetch.shutil, "which", lambda _: None)

    info = deepxiv_fetch.ensure_deepxiv_installed()

    assert info["ok"] is False
    assert "pip install deepxiv-sdk" in info["message"]


def test_run_cli_json_returns_decoded_payload(monkeypatch):
    deepxiv_fetch = load_module()
    monkeypatch.setattr(deepxiv_fetch.shutil, "which", lambda _: "deepxiv")

    def fake_run(*args, **kwargs):
        return CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"results": []}),
            stderr="",
        )

    monkeypatch.setattr(deepxiv_fetch.subprocess, "run", fake_run)

    payload = deepxiv_fetch.run_cli_json(["search", "agent memory", "--format", "json"])

    assert payload == {"results": []}


def test_run_cli_json_raises_when_stdout_is_not_json(monkeypatch):
    deepxiv_fetch = load_module()
    monkeypatch.setattr(deepxiv_fetch.shutil, "which", lambda _: "deepxiv")

    def fake_run(*args, **kwargs):
        return CompletedProcess(args=args[0], returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr(deepxiv_fetch.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="invalid JSON"):
        deepxiv_fetch.run_cli_json(["search", "agent memory", "--format", "json"])


def test_run_cli_text_returns_stdout(monkeypatch):
    deepxiv_fetch = load_module()
    monkeypatch.setattr(deepxiv_fetch.shutil, "which", lambda _: "deepxiv")

    def fake_run(*args, **kwargs):
        return CompletedProcess(args=args[0], returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(deepxiv_fetch.subprocess, "run", fake_run)

    payload = deepxiv_fetch.run_cli_text(["health"])

    assert payload == "ok"


def test_cli_parser_builds_help_without_traceback():
    deepxiv_fetch = load_module()

    parser = deepxiv_fetch.build_parser()

    help_text = parser.format_help()

    assert "search" in help_text
    assert "paper-brief" in help_text


@pytest.mark.parametrize(
    "argv, expected_args",
    [
        (
            ["paper-brief", "2409.05591"],
            ["paper", "2409.05591", "--brief", "--format", "json"],
        ),
        (
            ["paper-head", "2409.05591"],
            ["paper", "2409.05591", "--head", "--format", "json"],
        ),
        (
            ["paper-section", "2409.05591", "Introduction"],
            ["paper", "2409.05591", "--section", "Introduction", "--format", "json"],
        ),
        (
            ["search", "agent memory", "--max", "5"],
            ["search", "agent memory", "--limit", "5", "--mode", "hybrid", "--format", "json"],
        ),
        (
            ["trending", "--days", "14", "--max", "3"],
            ["trending", "--days", "14", "--limit", "3", "--output", "json"],
        ),
        (
            ["wsearch", "karpathy"],
            ["wsearch", "karpathy", "--output", "json"],
        ),
        (
            ["sc", "258001"],
            ["sc", "258001", "--output", "json"],
        ),
    ],
)
def test_dispatch_json_uses_expected_cli_flags(monkeypatch, argv, expected_args):
    deepxiv_fetch = load_module()
    parser = deepxiv_fetch.build_parser()
    parsed = parser.parse_args(argv)

    captured = {}

    def fake_run_cli_json(cli_args):
        captured["args"] = cli_args
        return {"ok": True}

    monkeypatch.setattr(deepxiv_fetch, "run_cli_json", fake_run_cli_json)

    payload = deepxiv_fetch._dispatch_json(parsed)

    assert payload == {"ok": True}
    assert captured["args"] == expected_args


def test_run_cli_json_raises_on_nonzero_exit(monkeypatch):
    deepxiv_fetch = load_module()
    monkeypatch.setattr(deepxiv_fetch.shutil, "which", lambda _: "deepxiv")

    def fake_run(*args, **kwargs):
        return CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="API error: quota exceeded"
        )

    monkeypatch.setattr(deepxiv_fetch.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="quota exceeded"):
        deepxiv_fetch.run_cli_json(["search", "test", "--format", "json"])


def test_dispatch_health_uses_run_cli_text(monkeypatch):
    deepxiv_fetch = load_module()
    parser = deepxiv_fetch.build_parser()
    parsed = parser.parse_args(["health"])

    monkeypatch.setattr(
        deepxiv_fetch, "run_cli_text", lambda _: "✅ Health check passed"
    )

    payload = deepxiv_fetch._dispatch_json(parsed)

    assert payload == {"ok": True, "output": "✅ Health check passed"}


def test_dispatch_health_json_flag(monkeypatch):
    deepxiv_fetch = load_module()
    parser = deepxiv_fetch.build_parser()
    parsed = parser.parse_args(["health", "--json"])

    monkeypatch.setattr(
        deepxiv_fetch, "run_cli_text", lambda _: "✅ Health check passed"
    )

    payload = deepxiv_fetch._dispatch_json(parsed)

    assert payload["ok"] is True

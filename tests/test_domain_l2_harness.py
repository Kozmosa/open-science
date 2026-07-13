"""Static safety and planning checks for the isolated domain L2 harness."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def _l2_environment(evidence_dir: Path) -> dict[str, str]:
    """Return valid immutable-looking L2 inputs for a non-Docker harness test."""

    return os.environ | {
        "OPENSCIENCE_L2_GIT_SHA": "a" * 40,
        "OPENSCIENCE_L2_BACKEND_IMAGE_DIGEST": "example/backend@sha256:" + "b" * 64,
        "OPENSCIENCE_L2_SCENARIO_IMAGE_DIGEST": "example/scenario@sha256:" + "c" * 64,
        "OPENSCIENCE_L2_PRIOR_FRONTEND_IMAGE_DIGEST": "example/frontend@sha256:" + "d" * 64,
        "OPENSCIENCE_L2_PRIOR_FRONTEND_ARTIFACT_SHA256": "e" * 64,
        "OPENSCIENCE_L2_EVIDENCE_DIR": str(evidence_dir),
    }


def _run_harness(
    repository_root: Path, environment: dict[str, str], mode: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repository_root / "testing" / "domain_l2" / "run_cell.sh"), mode],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_fake_docker(directory: Path) -> Path:
    """Install a command logger so execute-gate tests never contact Docker."""

    bin_dir = directory / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${OPENSCIENCE_L2_FAKE_DOCKER_LOG}"
compose_env=""
previous=""
for argument in "$@"; do
  if [[ "${previous}" == "--env-file" ]]; then
    compose_env="${argument}"
    break
  fi
  previous="${argument}"
done
if [[ -n "${OPENSCIENCE_L2_CAPTURED_RUNTIME_ENV:-}" && -n "${compose_env}" ]]; then
  runtime_env="$(awk -F= '/^OPENSCIENCE_L2_RUNTIME_ENV_FILE=/{print substr($0, index($0, "=") + 1); exit}' "${compose_env}")"
  cp "${runtime_env}" "${OPENSCIENCE_L2_CAPTURED_RUNTIME_ENV}"
fi
case " $* " in
  *" compose "*)
    case " $* " in
      *" config --quiet"*) exit 0 ;;
      *" up --detach --wait --remove-orphans"*) exit 73 ;;
      *" down --volumes --remove-orphans"*) exit 0 ;;
    esac
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return bin_dir


def test_l2_plan_accepts_a_full_git_commit_sha_without_contacting_docker(tmp_path: Path) -> None:
    """The non-executing plan must accept a normal SHA-1 Git commit ID.

    This regression deliberately supplies only immutable-looking artifact
    identities.  ``plan`` must create a redacted manifest without resolving a
    Docker context or running a container.
    """

    repository_root = Path(__file__).resolve().parents[1]
    evidence_dir = tmp_path / "evidence"
    completed = _run_harness(repository_root, _l2_environment(evidence_dir), "plan")

    assert completed.returncode == 0, completed.stderr
    manifests = list(evidence_dir.glob("evidence-*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["git_sha"] == "a" * 40
    assert manifest["mode"] == "plan"
    assert manifest["status"] == "planned"
    assert all(item["status"] == "planned" for item in manifest["scenarios"])
    assert [item["id"] for item in manifest["scenarios"]] == [
        "backup-migration-restart-reconcile-restore",
        "importer-crash-resume",
        "double-dispatcher-claim-expiry",
        "launch-after-crash",
        "literature-saga-crash-recovery",
        "prior-frontend-artifact-contract",
    ]
    assert manifest["frontend_route_contract"] == {
        "api_path_prefix": "/api",
        "api_upstream_service": "api",
        "artifact_manifest_path": "/.well-known/openscience-artifact.json",
        "entrypoint_service": "frontend-gateway",
        "prior_frontend_upstream_service": "prior-frontend",
    }


def test_l2_plan_refuses_evidence_inside_any_registered_worktree_or_common_dir(
    tmp_path: Path,
) -> None:
    """Safety validation must not create evidence in any repository metadata area."""

    repository_root = Path(__file__).resolve().parents[1]
    worktree_output = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    prohibited_paths = [
        Path(line.removeprefix("worktree ")).resolve()
        for line in worktree_output.splitlines()
        if line.startswith("worktree ")
    ]
    common_dir = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = repository_root / common_path
    prohibited_paths.append(common_path.resolve())

    for index, prohibited_path in enumerate(prohibited_paths):
        evidence_dir = prohibited_path / f"l2-evidence-must-not-exist-{index}"
        assert not evidence_dir.exists()
        completed = _run_harness(repository_root, _l2_environment(evidence_dir), "plan")

        assert completed.returncode == 2
        assert "outside every repository worktree and Git common directory" in completed.stderr
        assert not evidence_dir.exists()


def test_l2_execute_rejects_default_context_before_contacting_docker(tmp_path: Path) -> None:
    """The shared default daemon cannot be selected even with execute opt-in."""

    repository_root = Path(__file__).resolve().parents[1]
    docker_log = tmp_path / "docker.log"
    fake_bin = _write_fake_docker(tmp_path)
    environment = _l2_environment(tmp_path / "evidence") | {
        "OPENSCIENCE_L2_EXECUTE": "1",
        "OPENSCIENCE_L2_DOCKER_CONTEXT": "default",
        "DOCKER_CONTEXT": "default",
        "OPENSCIENCE_L2_CONTEXT_ACK": "isolated",
        "OPENSCIENCE_L2_FAKE_DOCKER_LOG": str(docker_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    completed = _run_harness(repository_root, environment, "execute")

    assert completed.returncode == 2
    assert "isolated openscience-l2-* naming contract" in completed.stderr
    assert not docker_log.exists()


def test_l2_execute_cleans_partial_cell_when_compose_up_fails(tmp_path: Path) -> None:
    """A failed `compose up --wait` must still issue project-scoped cleanup."""

    repository_root = Path(__file__).resolve().parents[1]
    docker_log = tmp_path / "docker.log"
    fake_bin = _write_fake_docker(tmp_path)
    environment = _l2_environment(tmp_path / "evidence") | {
        "OPENSCIENCE_L2_EXECUTE": "1",
        "OPENSCIENCE_L2_DOCKER_CONTEXT": "openscience-l2-unit",
        "DOCKER_CONTEXT": "openscience-l2-unit",
        "OPENSCIENCE_L2_CONTEXT_ACK": "isolated",
        "OPENSCIENCE_L2_FAKE_DOCKER_LOG": str(docker_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    completed = _run_harness(repository_root, environment, "execute")

    assert completed.returncode == 73
    commands = docker_log.read_text(encoding="utf-8")
    assert "context inspect openscience-l2-unit" in commands
    assert "compose" in commands
    assert "up --detach --wait --remove-orphans" in commands
    assert "down --volumes --remove-orphans" in commands
    manifests = list((tmp_path / "evidence").glob("evidence-*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_l2_runtime_env_emits_current_and_legacy_auth_aliases(tmp_path: Path) -> None:
    """The API entrypoint must not fall into onboarding inside a read-only cell."""

    repository_root = Path(__file__).resolve().parents[1]
    docker_log = tmp_path / "docker.log"
    runtime_env = tmp_path / "captured-runtime.env"
    fake_bin = _write_fake_docker(tmp_path)
    environment = _l2_environment(tmp_path / "evidence") | {
        "OPENSCIENCE_L2_EXECUTE": "1",
        "OPENSCIENCE_L2_DOCKER_CONTEXT": "openscience-l2-unit",
        "DOCKER_CONTEXT": "openscience-l2-unit",
        "OPENSCIENCE_L2_CONTEXT_ACK": "isolated",
        "OPENSCIENCE_L2_FAKE_DOCKER_LOG": str(docker_log),
        "OPENSCIENCE_L2_CAPTURED_RUNTIME_ENV": str(runtime_env),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    completed = _run_harness(repository_root, environment, "execute")

    assert completed.returncode == 73
    values = dict(
        line.split("=", maxsplit=1)
        for line in runtime_env.read_text(encoding="utf-8").splitlines()
        if line
    )
    assert values["AINRF_API_KEY_HASHES"] == values["OPENSCIENCE_API_KEY_HASHES"]
    assert values["AINRF_JWT_SECRET"] == values["OPENSCIENCE_JWT_SECRET"]
    assert len(values["AINRF_API_KEY_HASHES"]) == 64
    assert len(values["AINRF_JWT_SECRET"]) == 64

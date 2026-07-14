#!/usr/bin/env bash
# Trusted, isolated Docker L2 recovery cell.
#
# Default invocation is a non-Docker planning operation.  It creates a
# redacted evidence manifest under /tmp and exits.  A caller must provide both
# the `execute` subcommand and OPENSCIENCE_L2_EXECUTE=1 before this script even
# resolves a Docker context.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
COMPOSE_FILE="${ROOT}/testing/domain_l2/docker-compose.l2.yml"
SCENARIO_LIBRARY="${ROOT}/testing/domain_l2/scenarios.sh"

readonly BACKEND_DIGEST_VAR="OPENSCIENCE_L2_BACKEND_IMAGE_DIGEST"
readonly SCENARIO_DIGEST_VAR="OPENSCIENCE_L2_SCENARIO_IMAGE_DIGEST"
readonly FRONTEND_DIGEST_VAR="OPENSCIENCE_L2_PRIOR_FRONTEND_IMAGE_DIGEST"
readonly FRONTEND_SHA_VAR="OPENSCIENCE_L2_PRIOR_FRONTEND_ARTIFACT_SHA256"

MODE="${1:-plan}"
case "${MODE}" in
  plan|execute) ;;
  *)
    printf 'Usage: %s [plan|execute]\n' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

die() {
  printf 'domain L2 cell refused: %s\n' "$*" >&2
  exit 2
}

require_file() {
  [[ -f "$1" ]] || die "required harness file is missing: $1"
}

require_digest() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] || \
    die "${name} must be an immutable image@sha256 digest"
}

require_sha256() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[0-9a-f]{64}$ ]] || die "${name} must be a lowercase SHA-256"
}

require_git_commit_sha() {
  local name="$1"
  local value="$2"
  # Current repositories use SHA-1 commits, while SHA-256 Git repositories
  # are also valid.  A release evidence record needs the exact commit object,
  # not a content SHA-256, so never validate it with require_sha256().
  [[ "${value}" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]] || \
    die "${name} must be a full lowercase Git commit SHA"
}

random_hex() {
  local bytes="$1"
  od -An -N "${bytes}" -tx1 /dev/urandom | tr -d ' \n'
}

sha256_text() {
  python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

sha256_file() {
  python3 - "$1" <<'PY'
from __future__ import annotations

import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

canonical_path() {
  # ``Path.resolve(strict=False)`` canonicalizes an as-yet-uncreated output
  # path without first creating it inside a repository.  This is important:
  # refusing an unsafe evidence destination must not leave an untracked
  # directory behind as a side effect of the safety check.
  python3 - "$1" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

path_is_within() {
  local candidate="$1"
  local parent="$2"
  [[ "${candidate}/" == "${parent}/"* ]]
}

canonical_dir_outside_repo() {
  local directory="$1"
  local resolved
  resolved="$(canonical_path "${directory}")"

  # A linked worktree's ``ROOT`` is not the only repository path which must
  # stay clean.  Evidence must also stay out of the main worktree, every other
  # linked worktree, and the shared Git directory.  `git worktree list` is the
  # authoritative source for all currently registered worktrees.
  local line
  local worktree
  while IFS= read -r line; do
    [[ "${line}" == worktree\ * ]] || continue
    worktree="$(canonical_path "${line#worktree }")"
    if path_is_within "${resolved}" "${worktree}"; then
      die "evidence must be outside every repository worktree and Git common directory"
    fi
  done < <(git -C "${ROOT}" worktree list --porcelain)

  local common_dir
  common_dir="$(git -C "${ROOT}" rev-parse --git-common-dir)"
  if [[ "${common_dir}" != /* ]]; then
    common_dir="${ROOT}/${common_dir}"
  fi
  common_dir="$(canonical_path "${common_dir}")"
  if path_is_within "${resolved}" "${common_dir}"; then
    die "evidence must be outside every repository worktree and Git common directory"
  fi

  mkdir -p "${resolved}"
  resolved="$(cd "${resolved}" && pwd -P)"
  printf '%s\n' "${resolved}"
}

validate_compose_template() {
  # Keep this static guard dependency-free: it runs during plan and prevents
  # a future template edit from silently introducing a source bind or Docker
  # socket before anyone is allowed to execute it.
  if grep -Eq '(^|[^[:alnum:]_])container_name:|docker\.sock|/var/run/docker|type:[[:space:]]*bind' "${COMPOSE_FILE}"; then
    die "Compose template contains a forbidden container name, bind mount, or Docker socket"
  fi
  if grep -Eq '(^|[^[:alnum:]_])(production|staging)[^[:alnum:]_].*\.env|\.env.*(production|staging)' "${COMPOSE_FILE}"; then
    die "Compose template references a production or staging env file"
  fi
  if ! grep -q 'name: ${OPENSCIENCE_L2_STATE_VOLUME' "${COMPOSE_FILE}"; then
    die "Compose template does not declare the generated state volume"
  fi
  if ! grep -q '^  frontend-gateway:$' "${COMPOSE_FILE}" || \
    ! grep -Fq '"/opt/openscience-l2/run-frontend-gateway"' "${COMPOSE_FILE}" || \
    ! grep -Fq '"http://prior-frontend:80"' "${COMPOSE_FILE}" || \
    ! grep -Fq '"http://api:8000"' "${COMPOSE_FILE}"; then
    die "Compose template lacks the immutable same-origin frontend/API gateway contract"
  fi
}

validate_execution_gate() {
  [[ "${OPENSCIENCE_L2_EXECUTE:-}" == "1" ]] || \
    die "execute requires OPENSCIENCE_L2_EXECUTE=1"
  local context="${OPENSCIENCE_L2_DOCKER_CONTEXT:-}"
  [[ -n "${context}" ]] || die "execute requires OPENSCIENCE_L2_DOCKER_CONTEXT"
  [[ "${DOCKER_CONTEXT:-}" == "${context}" ]] || \
    die "DOCKER_CONTEXT must explicitly equal OPENSCIENCE_L2_DOCKER_CONTEXT"
  [[ "${OPENSCIENCE_L2_CONTEXT_ACK:-}" == "isolated" ]] || \
    die "execute requires OPENSCIENCE_L2_CONTEXT_ACK=isolated"
  [[ "${context}" =~ ^openscience-l2-[a-z0-9][a-z0-9_-]*$ ]] || \
    die "Docker context must use the isolated openscience-l2-* naming contract"
  case "${context}" in
    *prod*|*production*|*stage*|*staging*|default|shared) \
      die "Docker context name is reserved for a non-L2 environment" ;;
  esac
  command -v docker >/dev/null 2>&1 || die "docker is unavailable"
  docker --context "${context}" context inspect "${context}" >/dev/null
}

GIT_SHA="${OPENSCIENCE_L2_GIT_SHA:-$(git -C "${ROOT}" rev-parse HEAD)}"
require_git_commit_sha "OPENSCIENCE_L2_GIT_SHA" "${GIT_SHA}"

BACKEND_DIGEST="${!BACKEND_DIGEST_VAR:-}"
SCENARIO_DIGEST="${!SCENARIO_DIGEST_VAR:-}"
FRONTEND_DIGEST="${!FRONTEND_DIGEST_VAR:-}"
FRONTEND_ARTIFACT_SHA="${!FRONTEND_SHA_VAR:-}"
require_digest "${BACKEND_DIGEST_VAR}" "${BACKEND_DIGEST}"
require_digest "${SCENARIO_DIGEST_VAR}" "${SCENARIO_DIGEST}"
require_digest "${FRONTEND_DIGEST_VAR}" "${FRONTEND_DIGEST}"
require_sha256 "${FRONTEND_SHA_VAR}" "${FRONTEND_ARTIFACT_SHA}"
require_file "${COMPOSE_FILE}"
require_file "${SCENARIO_LIBRARY}"
validate_compose_template

SHORT_SHA="${GIT_SHA:0:12}"
NONCE="$(random_hex 6)"
RUN_ID="l2-${SHORT_SHA}-${NONCE}"
COMPOSE_PROJECT="openscience_l2_${SHORT_SHA}_${NONCE}"
PORT_SEED=$((16#${NONCE:0:6}))
API_PORT=$((20000 + PORT_SEED % 5000))
FRONTEND_PORT=$((30000 + PORT_SEED % 5000))
STATE_VOLUME="${COMPOSE_PROJECT}_state"
TENANT_VOLUME="${COMPOSE_PROJECT}_tenants"
WORKSPACE_VOLUME="${COMPOSE_PROJECT}_workspaces"
ARTIFACT_TAG="openscience-l2:${SHORT_SHA}-${NONCE}"

if [[ -n "${OPENSCIENCE_L2_EVIDENCE_DIR:-}" ]]; then
  EVIDENCE_DIR="$(canonical_dir_outside_repo "${OPENSCIENCE_L2_EVIDENCE_DIR}")"
else
  EVIDENCE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openscience-domain-l2-evidence.${RUN_ID}.XXXXXX")"
fi
EVIDENCE_MANIFEST="${EVIDENCE_DIR}/evidence-${RUN_ID}.json"
CELL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/openscience-domain-l2-cell.${RUN_ID}.XXXXXX")"
RUNTIME_ENV="${CELL_ROOT}/runtime.env"
COMPOSE_ENV="${CELL_ROOT}/compose.env"
SCENARIO_RESULTS="${CELL_ROOT}/scenario-results.tsv"
touch "${SCENARIO_RESULTS}"
chmod 700 "${CELL_ROOT}"
umask 077

API_KEY="$(random_hex 32)"
JWT_SECRET="$(random_hex 32)"
API_KEY_HASH="$(printf '%s' "${API_KEY}" | sha256_text)"
CREDENTIAL_DIGEST="$(printf '%s\n%s\n' "${API_KEY}" "${JWT_SECRET}" | sha256_text)"

# ApiConfig accepts the OpenScience names first, but the current `serve`
# preflight and JWT helper still consume the legacy aliases.  Keep both names
# in this generated, private env file and bind each pair to the same random
# value so the immutable L2 API can start without onboarding or a writable
# home directory.
printf '%s\n' \
  'OPENSCIENCE_DOMAIN_MODEL_MODE=v2' \
  "OPENSCIENCE_DOMAIN_ARTIFACT_SHA=${BACKEND_DIGEST#*@sha256:}" \
  "OPENSCIENCE_L2_RUN_ID=${RUN_ID}" \
  "OPENSCIENCE_L2_ARTIFACT_TAG=${ARTIFACT_TAG}" \
  "OPENSCIENCE_L2_API_KEY=${API_KEY}" \
  "OPENSCIENCE_API_KEY_HASHES=${API_KEY_HASH}" \
  "AINRF_API_KEY_HASHES=${API_KEY_HASH}" \
  "OPENSCIENCE_JWT_SECRET=${JWT_SECRET}" \
  "AINRF_JWT_SECRET=${JWT_SECRET}" \
  'OPENSCIENCE_STATE_ROOT=/var/lib/openscience' \
  'OPENSCIENCE_NO_SSHD=1' \
  'OPENSCIENCE_L2_SYNTHETIC_FIXTURES_ONLY=1' \
  'OPENSCIENCE_L2_API_BASE_URL=http://api:8000' \
  'OPENSCIENCE_L2_PRIOR_FRONTEND_URL=http://frontend-gateway:8080' \
  'OPENSCIENCE_L2_PRIOR_FRONTEND_API_URL=http://frontend-gateway:8080/api' \
  'OPENSCIENCE_L2_FRONTEND_ARTIFACT_MANIFEST_PATH=/.well-known/openscience-artifact.json' \
  "OPENSCIENCE_L2_PRIOR_FRONTEND_ARTIFACT_SHA256=${FRONTEND_ARTIFACT_SHA}" \
  > "${RUNTIME_ENV}"
chmod 600 "${RUNTIME_ENV}"

printf '%s\n' \
  "OPENSCIENCE_L2_BACKEND_IMAGE_DIGEST=${BACKEND_DIGEST}" \
  "OPENSCIENCE_L2_SCENARIO_IMAGE_DIGEST=${SCENARIO_DIGEST}" \
  "OPENSCIENCE_L2_PRIOR_FRONTEND_IMAGE_DIGEST=${FRONTEND_DIGEST}" \
  "OPENSCIENCE_L2_RUNTIME_ENV_FILE=${RUNTIME_ENV}" \
  "OPENSCIENCE_L2_API_PORT=${API_PORT}" \
  "OPENSCIENCE_L2_FRONTEND_PORT=${FRONTEND_PORT}" \
  "OPENSCIENCE_L2_STATE_VOLUME=${STATE_VOLUME}" \
  "OPENSCIENCE_L2_TENANT_VOLUME=${TENANT_VOLUME}" \
  "OPENSCIENCE_L2_WORKSPACE_VOLUME=${WORKSPACE_VOLUME}" \
  > "${COMPOSE_ENV}"
chmod 600 "${COMPOSE_ENV}"

write_evidence() {
  local status="$1"
  python3 - \
    "${EVIDENCE_MANIFEST}" "${RUN_ID}" "${GIT_SHA}" "${MODE}" "${status}" \
    "${OPENSCIENCE_L2_DOCKER_CONTEXT:-}" "${COMPOSE_PROJECT}" "${API_PORT}" "${FRONTEND_PORT}" \
    "${STATE_VOLUME}" "${TENANT_VOLUME}" "${WORKSPACE_VOLUME}" "${ARTIFACT_TAG}" \
    "${BACKEND_DIGEST}" "${SCENARIO_DIGEST}" "${FRONTEND_DIGEST}" "${FRONTEND_ARTIFACT_SHA}" \
    "${CREDENTIAL_DIGEST}" "$(sha256_file "${COMPOSE_FILE}")" "${SCENARIO_RESULTS}" <<'PY'
from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime

(
    output,
    run_id,
    git_sha,
    mode,
    status,
    docker_context,
    compose_project,
    api_port,
    frontend_port,
    state_volume,
    tenant_volume,
    workspace_volume,
    artifact_tag,
    backend_digest,
    scenario_digest,
    frontend_digest,
    frontend_artifact_sha,
    credential_digest,
    compose_sha,
    result_file,
) = sys.argv[1:]

scenario_ids = (
    "backup-migration-restart-reconcile-restore",
    "importer-crash-resume",
    "double-dispatcher-claim-expiry",
    "launch-after-crash",
    "literature-saga-crash-recovery",
    "prior-frontend-artifact-contract",
)
results: dict[str, str] = {}
for line in pathlib.Path(result_file).read_text(encoding="utf-8").splitlines():
    scenario, separator, outcome = line.partition("\t")
    if separator and scenario in scenario_ids and outcome:
        results[scenario] = outcome
default = "planned" if status == "planned" else "not-completed"
payload = {
    "version": 1,
    "created_at": datetime.now(UTC).isoformat(),
    "run_id": run_id,
    "git_sha": git_sha,
    "mode": mode,
    "status": status,
    "docker_context": docker_context or None,
    "compose_project": compose_project,
    "ports": {"api": int(api_port), "frontend_gateway": int(frontend_port)},
    "volumes": {
        "state": state_volume,
        "tenants": tenant_volume,
        "workspaces": workspace_volume,
    },
    "artifacts": {
        "cell_artifact_tag": artifact_tag,
        "backend_image_digest": backend_digest,
        "scenario_image_digest": scenario_digest,
        "prior_frontend_image_digest": frontend_digest,
        "prior_frontend_artifact_sha256": frontend_artifact_sha,
        "compose_template_sha256": compose_sha,
    },
    "frontend_route_contract": {
        "entrypoint_service": "frontend-gateway",
        "prior_frontend_upstream_service": "prior-frontend",
        "api_upstream_service": "api",
        "api_path_prefix": "/api",
        "artifact_manifest_path": "/.well-known/openscience-artifact.json",
    },
    "credentials": {"redacted": True, "material_sha256": credential_digest},
    "safety": {
        "synthetic_or_deidentified_fixture_only": True,
        "source_bind_mounts": False,
        "docker_socket": False,
        "production_or_staging_env_file": False,
        "production_or_shared_volumes": False,
    },
    "scenarios": [
        {"id": scenario, "status": results.get(scenario, default)} for scenario in scenario_ids
    ],
}
pathlib.Path(output).write_text(
    json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

# Set this before `compose up`: the command can create containers, networks,
# and volumes before it reports a failed health check.  The EXIT trap must
# still tear down that partial cell rather than leak uniquely named resources.
COMPOSE_MAY_HAVE_STARTED=0
EXECUTION_STARTED=0
FINAL_STATUS="planned"
DOCKER_CONTEXT="${OPENSCIENCE_L2_DOCKER_CONTEXT:-}"

l2_compose() {
  docker --context "${DOCKER_CONTEXT}" compose \
    --project-name "${COMPOSE_PROJECT}" \
    --env-file "${COMPOSE_ENV}" \
    --file "${COMPOSE_FILE}" \
    "$@"
}

cleanup() {
  local exit_code=$?
  if [[ "${EXECUTION_STARTED}" == "1" ]]; then
    if [[ "${exit_code}" == "0" && "${FINAL_STATUS}" == "passed" ]]; then
      write_evidence "passed"
    else
      write_evidence "failed"
    fi
  fi
  if [[ "${COMPOSE_MAY_HAVE_STARTED}" == "1" ]]; then
    l2_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "${CELL_ROOT}"
}
trap cleanup EXIT

write_evidence "planned"
if [[ "${MODE}" == "plan" ]]; then
  printf 'L2 plan created without Docker execution. Evidence manifest: %s\n' "${EVIDENCE_MANIFEST}"
  printf 'To execute, pass `execute` and explicitly set OPENSCIENCE_L2_EXECUTE=1 plus an isolated Docker context.\n'
  exit 0
fi

validate_execution_gate
EXECUTION_STARTED=1
write_evidence "running"
export OPENSCIENCE_L2_SCENARIO_RESULTS="${SCENARIO_RESULTS}"
source "${SCENARIO_LIBRARY}"

l2_compose config --quiet
COMPOSE_MAY_HAVE_STARTED=1
l2_compose up --detach --wait --remove-orphans
run_l2_scenarios
FINAL_STATUS="passed"
printf 'L2 recovery cell passed. Evidence manifest: %s\n' "${EVIDENCE_MANIFEST}"

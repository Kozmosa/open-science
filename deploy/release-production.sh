#!/usr/bin/env bash
# Build all production artifacts first, then deploy the matching release set.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.cpu.yml"

# shellcheck source=lib/health.sh
source "${REPO_ROOT}/deploy/lib/health.sh"

load_runtime_env_from_container ainrf

if [[ -z "${OPENSCIENCE_RELEASE_MANIFEST:-}" ]]; then
  RELEASE_ID="${OPENSCIENCE_RELEASE_ID:-$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)}"
  export OPENSCIENCE_RELEASE_MANIFEST="/tmp/openscience-release-${RELEASE_ID}.env"
fi

"${REPO_ROOT}/deploy/build-production.sh"
set -a
# shellcheck disable=SC1090
source "${OPENSCIENCE_RELEASE_MANIFEST}"
set +a

docker compose -f "${COMPOSE_FILE}" up -d --no-build
wait_for_compose_service "${COMPOSE_FILE}" ainrf 60 2
wait_for_compose_service "${COMPOSE_FILE}" nginx 60 2
wait_for_url "http://localhost:18000/health" 60 2
wait_for_url "http://localhost:8192/health" 60 2

echo "Production release ${OPENSCIENCE_RELEASE_ID} is healthy."
echo "Keep ${OPENSCIENCE_RELEASE_MANIFEST} for audit and rollback."

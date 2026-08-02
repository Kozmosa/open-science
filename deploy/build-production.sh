#!/usr/bin/env bash
# Build one immutable production release without starting any containers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_ID="${OPENSCIENCE_RELEASE_ID:-$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)}"
COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD)"
IMAGE_PREFIX="${OPENSCIENCE_IMAGE_PREFIX:-openscience}"
MANIFEST_PATH="${OPENSCIENCE_RELEASE_MANIFEST:-/tmp/openscience-release-${RELEASE_ID}.env}"

if [[ -n "$(git -C "${REPO_ROOT}" status --short)" && "${OPENSCIENCE_ALLOW_DIRTY_BUILD:-0}" != "1" ]]; then
  echo "Refusing a production build from a dirty worktree." >&2
  exit 2
fi

build_target() {
  local target="$1"
  local image="$2"
  docker build \
    --file "${REPO_ROOT}/deploy/Dockerfile" \
    --target "${target}" \
    --build-arg "AINRF_BUILD_COMMIT=${RELEASE_ID}" \
    --build-arg "AINRF_BUILD_COMMITTED_AT=${COMMITTED_AT}" \
    --tag "${image}" \
    "${REPO_ROOT}"
}

API_IMAGE="${IMAGE_PREFIX}-api:${RELEASE_ID}"
WEB_IMAGE="${IMAGE_PREFIX}-web:${RELEASE_ID}"
PROMETHEUS_IMAGE="${IMAGE_PREFIX}-prometheus:${RELEASE_ID}"
GRAFANA_IMAGE="${IMAGE_PREFIX}-grafana:${RELEASE_ID}"
GATUS_IMAGE="${IMAGE_PREFIX}-gatus:${RELEASE_ID}"

build_target runtime "${API_IMAGE}"
build_target web "${WEB_IMAGE}"
build_target prometheus "${PROMETHEUS_IMAGE}"
build_target grafana "${GRAFANA_IMAGE}"
build_target gatus "${GATUS_IMAGE}"

image_id() {
  docker image inspect --format '{{.Id}}' "$1"
}

API_IMAGE_ID="$(image_id "${API_IMAGE}")"
WEB_IMAGE_ID="$(image_id "${WEB_IMAGE}")"
PROMETHEUS_IMAGE_ID="$(image_id "${PROMETHEUS_IMAGE}")"
GRAFANA_IMAGE_ID="$(image_id "${GRAFANA_IMAGE}")"
GATUS_IMAGE_ID="$(image_id "${GATUS_IMAGE}")"

umask 077
mkdir -p "$(dirname "${MANIFEST_PATH}")"
{
  printf 'OPENSCIENCE_RELEASE_ID=%s\n' "${RELEASE_ID}"
  printf 'OPENSCIENCE_RELEASE_GIT_SHA=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  printf 'OPENSCIENCE_API_IMAGE=%s\n' "${API_IMAGE}"
  printf 'OPENSCIENCE_API_IMAGE_ID=%s\n' "${API_IMAGE_ID}"
  printf 'OPENSCIENCE_WEB_IMAGE=%s\n' "${WEB_IMAGE}"
  printf 'OPENSCIENCE_WEB_IMAGE_ID=%s\n' "${WEB_IMAGE_ID}"
  printf 'OPENSCIENCE_PROMETHEUS_IMAGE=%s\n' "${PROMETHEUS_IMAGE}"
  printf 'OPENSCIENCE_PROMETHEUS_IMAGE_ID=%s\n' "${PROMETHEUS_IMAGE_ID}"
  printf 'OPENSCIENCE_GRAFANA_IMAGE=%s\n' "${GRAFANA_IMAGE}"
  printf 'OPENSCIENCE_GRAFANA_IMAGE_ID=%s\n' "${GRAFANA_IMAGE_ID}"
  printf 'OPENSCIENCE_GATUS_IMAGE=%s\n' "${GATUS_IMAGE}"
  printf 'OPENSCIENCE_GATUS_IMAGE_ID=%s\n' "${GATUS_IMAGE_ID}"
} >"${MANIFEST_PATH}"
chmod 600 "${MANIFEST_PATH}"

echo "Built production release ${RELEASE_ID}"
echo "Release manifest: ${MANIFEST_PATH}"

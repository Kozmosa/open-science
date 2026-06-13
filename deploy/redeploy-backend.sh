#!/usr/bin/env bash
# ── Rebuild + redeploy the ainrf BACKEND image ───────────────────
#
# Stamps the host git commit into the image (baked as
# /opt/ainrf/backend-build-info.json) so /settings/deployment-version
# reports the commit the backend was actually built from.
#
# Usage:
#   bash deploy/redeploy-backend.sh                  # production (default)
#   bash deploy/redeploy-backend.sh --target staging  # staging
#
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

TARGET="production"
EXTRA_ARGS=()

while (($# > 0)); do
  case "$1" in
    --target)
      TARGET="${2:?--target requires a value (production|staging)}"
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

case "$TARGET" in
  production)
    COMPOSE_FILE="docker-compose.cpu.yml"
    SERVICE="ainrf"
    ;;
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    SERVICE="ainrf-staging"
    ;;
  *)
    echo "Unknown target: $TARGET (use 'production' or 'staging')" >&2
    exit 1
    ;;
esac

export AINRF_BUILD_COMMIT
export AINRF_BUILD_COMMITTED_AT
AINRF_BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short=6 HEAD)"
AINRF_BUILD_COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD)"

echo "=== Backend build provenance ==="
echo "  commit:       ${AINRF_BUILD_COMMIT}"
echo "  committed_at: ${AINRF_BUILD_COMMITTED_AT}"
echo "  target:       ${TARGET} (${SERVICE})"
echo

exec docker compose -f "${COMPOSE_FILE}" up -d --build "${SERVICE}" "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

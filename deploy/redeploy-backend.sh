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

# Load shared health helpers.
# shellcheck source=lib/health.sh
source "${REPO_ROOT}/deploy/lib/health.sh"

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
    NGINX_SERVICE="nginx"
    BACKEND_HEALTH_URL="http://localhost:18000/health"
    NGINX_HEALTH_URL="http://localhost:8192/health"
    ;;
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    SERVICE="ainrf-staging"
    NGINX_SERVICE="nginx-staging"
    BACKEND_HEALTH_URL="http://localhost:17000/health"
    NGINX_HEALTH_URL="http://localhost:7192/health"
    ;;
  *)
    _ainrf_error "Unknown target: $TARGET (use 'production' or 'staging')"
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

docker compose -f "${COMPOSE_FILE}" up -d --build "${SERVICE}" "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

# Production nginx serves the host frontend/dist, not the dist baked into the
# backend image. Rebuild it here so the frontend build-info matches the backend
# commit and the user sees a consistent deployment version.
echo "=== Building frontend on host ==="
cd "${REPO_ROOT}/frontend"
npm run build
cd "${REPO_ROOT}/deploy"

# Propagate nginx config changes too.  A plain 'docker compose up --build ainrf'
# leaves the nginx container untouched, which can hide stale configs (e.g. the
# container still references litefuse-web while the host config was switched to
# 127.0.0.1).
echo "=== Recreating ${NGINX_SERVICE} to pick up latest nginx config ==="
docker compose -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate "${NGINX_SERVICE}"

# Wait for both backend and nginx to be responsive.
wait_for_compose_service "${COMPOSE_FILE}" "${SERVICE}" 30 2
wait_for_url "${BACKEND_HEALTH_URL}" 30 2
wait_for_url "${NGINX_HEALTH_URL}" 30 2

echo
echo "=== ${TARGET} backend redeploy complete ==="
echo "  Backend: ${BACKEND_HEALTH_URL}"
echo "  Nginx:   ${NGINX_HEALTH_URL}"

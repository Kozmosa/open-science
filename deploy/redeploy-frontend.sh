#!/usr/bin/env bash
# ── Rebuild + redeploy the FRONTEND (nginx static) ───────────────
#
# The frontend ships its own build-info (frontend/dist/build-info.json),
# captured at `npm run build` time. nginx bind-mounts the host
# frontend/dist, so a rebuild + nginx recreate is enough — no image
# rebuild needed.
#
# Usage:
#   bash deploy/redeploy-frontend.sh                  # production (default)
#   bash deploy/redeploy-frontend.sh --target staging  # staging
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
    SERVICE="nginx"
    NGINX_HEALTH_URL="http://localhost:8192/health"
    ;;
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    SERVICE="nginx-staging"
    NGINX_HEALTH_URL="http://localhost:7192/health"
    ;;
  *)
    _ainrf_error "Unknown target: $TARGET (use 'production' or 'staging')"
    exit 1
    ;;
esac

echo "=== Building frontend (host) ==="
cd "${REPO_ROOT}/frontend"
npm run build

echo
echo "=== Recreating ${SERVICE} (${TARGET}) ==="
cd "${REPO_ROOT}/deploy"
# Use --force-recreate so nginx picks up any changes to nginx-host.conf or
# nginx-staging.conf, not just the updated frontend/dist.
docker compose -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate "${SERVICE}" "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

# Verify nginx serves traffic through the reverse proxy.
wait_for_url "${NGINX_HEALTH_URL}" 30 2

echo
echo "=== ${TARGET} frontend redeploy complete ==="
echo "  Nginx: ${NGINX_HEALTH_URL}"

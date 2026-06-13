#!/usr/bin/env bash
# ── Rebuild + redeploy the FRONTEND (nginx static) ───────────────
#
# The frontend ships its own build-info (frontend/dist/build-info.json),
# captured at `npm run build` time. nginx bind-mounts the host
# frontend/dist, so a rebuild + nginx restart is enough — no image
# rebuild needed.
#
# Usage:
#   bash deploy/redeploy-frontend.sh                  # production (default)
#   bash deploy/redeploy-frontend.sh --target staging  # staging
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
    SERVICE="nginx"
    ;;
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    SERVICE="nginx-staging"
    ;;
  *)
    echo "Unknown target: $TARGET (use 'production' or 'staging')" >&2
    exit 1
    ;;
esac

echo "=== Building frontend (host) ==="
cd "${REPO_ROOT}/frontend"
npm run build

echo
echo "=== Restarting ${SERVICE} (${TARGET}) ==="
cd "${REPO_ROOT}/deploy"
exec docker compose -f "${COMPOSE_FILE}" restart "${SERVICE}" "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

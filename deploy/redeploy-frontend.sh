#!/usr/bin/env bash
# ── Rebuild + redeploy the FRONTEND (nginx static) ───────────────
#
# The frontend ships its own build-info, captured at `npm run build` time.
# Each deployment target has a separate host output directory, so rebuilding
# staging cannot replace the assets served by production nginx.
# rebuild needed.
#
# Usage:
#   bash deploy/redeploy-frontend.sh                  # production (default)
#   bash deploy/redeploy-frontend.sh --target staging  # staging
#   bash deploy/redeploy-frontend.sh --target gpu      # GPU lab (bridge network)
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

if [[ "${TARGET}" == "staging" ]]; then
  _ainrf_error "Direct staging redeploy is disabled. Use scripts/staging.sh with OPENSCIENCE_STAGING_ENV_FILE."
  exit 2
fi

case "$TARGET" in
  production)
    COMPOSE_FILE="docker-compose.cpu.yml"
    SERVICE="nginx"
    NGINX_HEALTH_URL="http://localhost:8192/health"
    FRONTEND_OUT_DIR="dist/production"
    RUNTIME_CONTAINER="ainrf"
    ;;
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    SERVICE="nginx-staging"
    NGINX_HEALTH_URL="http://localhost:7192/health"
    FRONTEND_OUT_DIR="dist/staging"
    RUNTIME_CONTAINER="ainrf-staging"
    ;;
  gpu)
    COMPOSE_FILE="docker-compose.gpu.yml"
    SERVICE="nginx"
    NGINX_HEALTH_URL="http://localhost:8192/health"
    FRONTEND_OUT_DIR="dist/gpu"
    RUNTIME_CONTAINER="ainrf"
    ;;
  *)
    _ainrf_error "Unknown target: $TARGET (use 'production' or 'staging')"
    exit 1
    ;;
esac

load_runtime_env_from_container "${RUNTIME_CONTAINER}"

export AINRF_BUILD_COMMIT
export AINRF_BUILD_COMMITTED_AT
AINRF_BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short=6 HEAD)"
AINRF_BUILD_COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD)"

echo "=== Building frontend (host) ==="
echo "  commit:       ${AINRF_BUILD_COMMIT}"
echo "  committed_at: ${AINRF_BUILD_COMMITTED_AT}"

# GPU deployments require the legacy nvidia container runtime (nvidia-docker2).
if [ "${TARGET}" = "gpu" ]; then
    if ! docker info --format '{{range $k,$v := .Runtimes}}{{$k}} {{end}}' 2>/dev/null | grep -qw nvidia; then
        _ainrf_error "GPU target requires the nvidia container runtime."
        _ainrf_error "Install it with:"
        _ainrf_error "  sudo apt-get install -y nvidia-container-toolkit"
        _ainrf_error "  sudo nvidia-ctk runtime configure --runtime=docker"
        _ainrf_error "  sudo systemctl restart docker"
        exit 1
    fi
fi

cd "${REPO_ROOT}/frontend"
VITE_OPENSCIENCE_API_KEY= VITE_AINRF_API_KEY= \
  OPENSCIENCE_FRONTEND_OUT_DIR="${FRONTEND_OUT_DIR}" npm run build
chmod -R a+rX "${REPO_ROOT}/frontend/${FRONTEND_OUT_DIR}"

echo
echo "=== Recreating ${SERVICE} (${TARGET}) ==="
cd "${REPO_ROOT}/deploy"
# Use --force-recreate so nginx picks up any changes to nginx-host.conf or
# nginx-staging.conf, not just the updated target-specific frontend bundle.
docker compose -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate "${SERVICE}" "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

# Verify nginx serves traffic through the reverse proxy.
wait_for_url "${NGINX_HEALTH_URL}" 30 2

echo
echo "=== ${TARGET} frontend redeploy complete ==="
echo "  Nginx: ${NGINX_HEALTH_URL}"

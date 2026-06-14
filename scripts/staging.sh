#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
# AINRF Staging Environment — Lifecycle Manager
# ══════════════════════════════════════════════════════════════════
#
# Usage:
#   bash scripts/staging.sh up        # build + start, wait for healthy
#   bash scripts/staging.sh down      # destroy containers + volumes
#   bash scripts/staging.sh status    # show running state and URLs
#   bash scripts/staging.sh logs      # tail ainrf-staging logs
#   bash scripts/staging.sh rebuild   # rebuild image, keep data
#   bash scripts/staging.sh creds     # print admin initial password
#   bash scripts/staging.sh test      # run integration tests against staging
#
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.staging.yml"

# shellcheck source=../deploy/lib/health.sh
source "${REPO_ROOT}/deploy/lib/health.sh"

COMPOSE_CMD=(docker compose -f "${COMPOSE_FILE}")

# ── Colors ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'  # No Color

_info()  { echo -e "${GREEN}[staging]${NC} $*"; }
_warn()  { echo -e "${YELLOW}[staging]${NC} $*"; }
_error() { echo -e "${RED}[staging]${NC} $*" >&2; }

# ── Commands ───────────────────────────────────────────────────────

cmd_up() {
  _info "Building and starting staging environment..."

  # Ensure frontend dist exists
  if [[ ! -d "${REPO_ROOT}/frontend/dist" ]]; then
    _warn "frontend/dist not found — building frontend first..."
    (cd "${REPO_ROOT}/frontend" && npm run build)
  fi

  # Stamp git provenance (same as redeploy-backend.sh)
  export AINRF_BUILD_COMMIT
  export AINRF_BUILD_COMMITTED_AT
  AINRF_BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short=6 HEAD 2>/dev/null || echo unknown)"
  AINRF_BUILD_COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD 2>/dev/null || echo unknown)"

  "${COMPOSE_CMD[@]}" up -d --build

  _info "Waiting for backend to become healthy..."
  wait_for_compose_service "${COMPOSE_FILE}" "ainrf-staging" 60 2
  wait_for_url "http://localhost:17000/health" 60 2

  echo
  _info "${BOLD}Staging environment is ready!${NC}"
  echo
  echo "  App:       http://localhost:7192/"
  echo "  API:       http://localhost:7192/api/"
  echo "  Metrics:   http://localhost:7192/metrics"
  echo "  Grafana:   http://localhost:7192/monitoring"
  echo "  Backend:   http://localhost:17000/health"
  echo
  _info "Admin password:"
  "${COMPOSE_CMD[@]}" exec ainrf-staging cat /opt/ainrf/state/admin_initial_password.txt 2>/dev/null || _warn "(not yet available — check again shortly)"
}

cmd_down() {
  _info "Stopping staging environment and removing volumes..."
  "${COMPOSE_CMD[@]}" down -v --remove-orphans
  _info "Done. All staging containers and data removed."
}

cmd_status() {
  echo -e "${BOLD}AINRF Staging Environment Status${NC}"
  echo
  "${COMPOSE_CMD[@]}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
  echo

  if wait_for_url "http://localhost:17000/health" 1 0 >/dev/null 2>&1; then
    _info "Backend: ${GREEN}healthy${NC}"
  else
    _warn "Backend: not responding"
  fi

  if wait_for_url "http://localhost:7192/" 1 0 >/dev/null 2>&1; then
    _info "Nginx:   ${GREEN}healthy${NC}"
  else
    _warn "Nginx:   not responding"
  fi
  echo
  echo "  App:     http://localhost:7192/"
  echo "  Grafana: http://localhost:7192/monitoring"
}

cmd_logs() {
  "${COMPOSE_CMD[@]}" logs -f ainrf-staging "$@"
}

cmd_rebuild() {
  _info "Rebuilding staging backend image (preserving data)..."

  export AINRF_BUILD_COMMIT
  export AINRF_BUILD_COMMITTED_AT
  AINRF_BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short=6 HEAD 2>/dev/null || echo unknown)"
  AINRF_BUILD_COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD 2>/dev/null || echo unknown)"

  "${COMPOSE_CMD[@]}" up -d --build ainrf-staging
  _info "Backend image rebuilt and restarted."
  _info "Hot-reload is active — source changes in src/ainrf/ are picked up automatically."
  _info "For dependency changes, rebuild again or restart manually."
}

cmd_creds() {
  _info "Admin initial password:"
  "${COMPOSE_CMD[@]}" exec ainrf-staging cat /opt/ainrf/state/admin_initial_password.txt 2>/dev/null || _warn "Not available yet. Is the staging environment running?"
}

cmd_test() {
  local base_url="http://localhost:17000"
  if ! wait_for_url "${base_url}/health" 1 0 >/dev/null 2>&1; then
    _error "Staging backend is not healthy at ${base_url}"
    _error "Run: bash scripts/staging.sh up"
    exit 1
  fi

  _info "Running integration tests against staging at ${base_url}"
  cd "${REPO_ROOT}"
  AINRF_STAGING_URL="${base_url}" uv run pytest -m integration -q --timeout=180
}

# ── Main ───────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: bash scripts/staging.sh <command>

Commands:
  up        Build and start the staging environment
  down      Stop and remove all staging containers and data
  status    Show running state and access URLs
  logs      Tail ainrf-staging container logs
  rebuild   Rebuild backend image (keep data volumes)
  creds     Print the admin initial password
  test      Run integration tests against the running staging backend
EOF
}

case "${1:-}" in
  up)       shift || true; cmd_up "$@" ;;
  down)     shift || true; cmd_down "$@" ;;
  status)   shift || true; cmd_status "$@" ;;
  logs)     shift || true; cmd_logs "$@" ;;
  rebuild)  shift || true; cmd_rebuild "$@" ;;
  creds)    shift || true; cmd_creds "$@" ;;
  test)     shift || true; cmd_test "$@" ;;
  -h|--help|help)
    usage
    ;;
  *)
    _error "Unknown command: ${1:-}"
    usage
    exit 1
    ;;
esac

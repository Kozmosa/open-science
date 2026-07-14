#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
# OpenScience Staging Environment — Lifecycle Manager
# ══════════════════════════════════════════════════════════════════
#
# Usage:
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh up
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh down
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env OPENSCIENCE_STAGING_ALLOW_VOLUME_REMOVAL=1 bash scripts/staging.sh purge
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh status
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh logs
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh rebuild
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh creds
#   OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh smoke
#
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.staging.yml"
STAGING_FRONTEND_OUT_DIR="dist/staging"

# shellcheck source=../deploy/lib/health.sh
source "${REPO_ROOT}/deploy/lib/health.sh"

# ── Colors ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'  # No Color

_info()  { echo -e "${GREEN}[staging]${NC} $*"; }
_warn()  { echo -e "${YELLOW}[staging]${NC} $*"; }
_error() { echo -e "${RED}[staging]${NC} $*" >&2; }

_validate_staging_volume_config() {
  # Validate the rendered Compose model rather than only shell variables: an
  # explicit env file can define seed volumes too.  Keep the result off stdout
  # so this preflight never prints credentials from the rendered environment.
  "${COMPOSE_CMD[@]}" config --format json | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
volumes = payload.get("volumes", {})
for key in ("staging-ainrf-state", "staging-ainrf-workspaces", "staging-ainrf-tenants"):
    entry = volumes.get(key, {})
    name = entry.get("name", key) if isinstance(entry, dict) else key
    if not isinstance(name, str) or not name.startswith(("openscience-staging_", "openscience-staging-")):
        raise SystemExit(f"unsafe staging volume name for {key}")
services = payload.get("services", {})
api = services.get("ainrf-staging", {})
environment = api.get("environment", {}) if isinstance(api, dict) else {}
state_root = environment.get("AINRF_STATE_ROOT") if isinstance(environment, dict) else None
public_state_root = environment.get("OPENSCIENCE_STATE_ROOT") if isinstance(environment, dict) else None
if not isinstance(state_root, str) or state_root != public_state_root:
    raise SystemExit("staging state-root aliases must agree")
if not isinstance(state_root, str) or not (
    state_root == "/opt/ainrf/state"
    or __import__("re").fullmatch(r"/opt/ainrf/state/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", state_root)
):
    raise SystemExit("unsafe staging state-root generation")
'
}

_assert_no_background_worker_profiles() {
  local running_service
  local running_services
  running_services="$("${COMPOSE_CMD[@]}" ps --services --status running 2>/dev/null || true)"
  while IFS= read -r running_service; do
    case "${running_service}" in
      domain-worker-staging|literature-worker-staging|literature-planner-staging|literature-redis-staging)
        _error "Refusing staging lifecycle action while ${running_service} is running."
        _error "Stop the project first; a clone smoke must not run background runtime/Literature workers."
        return 1
        ;;
    esac
  done <<< "${running_services}"
}

# Do not let Compose silently load the repository's default .env.  On this
# host that file may contain production-only values.  A staging lifecycle
# caller must deliberately provide an independent file outside the repository.
STAGING_ENV_FILE="${OPENSCIENCE_STAGING_ENV_FILE:-}"
COMPOSE_CMD=()
if [[ "${1:-}" != "-h" && "${1:-}" != "--help" && "${1:-}" != "help" \
  && "${1:-}" != "smoke" && "${1:-}" != "test" ]]; then
  if [[ -z "${STAGING_ENV_FILE}" || ! -f "${STAGING_ENV_FILE}" ]]; then
    _error "Set OPENSCIENCE_STAGING_ENV_FILE to an existing staging-only env file."
    exit 2
  fi
  STAGING_ENV_FILE="$(realpath "${STAGING_ENV_FILE}")"
  REPO_ROOT_REAL="$(realpath "${REPO_ROOT}")"
  if [[ "${STAGING_ENV_FILE}" == "${REPO_ROOT_REAL}" || "${STAGING_ENV_FILE}" == "${REPO_ROOT_REAL}/"* ]]; then
    _error "OPENSCIENCE_STAGING_ENV_FILE must live outside the repository."
    exit 2
  fi
  env_mode="$(stat -c '%a' "${STAGING_ENV_FILE}")"
  if (( (8#${env_mode}) & 8#077 )); then
    _error "OPENSCIENCE_STAGING_ENV_FILE must not be group- or world-readable."
    exit 2
  fi
  if rg -q '^(AINRF_JWT_SECRET|OPENSCIENCE_JWT_SECRET|AINRF_API_KEY_HASHES|OPENSCIENCE_API_KEY_HASHES|ANTHROPIC_API_KEY|CODEX_API_KEY|GRAFANA_ADMIN_(USER|PASSWORD))=' "${STAGING_ENV_FILE}"; then
    _error "Staging env file contains a forbidden unprefixed production credential key."
    exit 2
  fi
  if [[ -n "${COMPOSE_PROFILES:-}" ]]; then
    _error "COMPOSE_PROFILES must be empty for an isolated staging lifecycle action."
    exit 2
  fi
  COMPOSE_CMD=(docker compose --env-file "${STAGING_ENV_FILE}" -f "${COMPOSE_FILE}")
  if ! _validate_staging_volume_config; then
    _error "Staging config must use an isolated openscience-staging_* volume."
    exit 2
  fi
fi

# ── Commands ───────────────────────────────────────────────────────

cmd_up() {
  _info "Building and starting staging environment..."
  _assert_no_background_worker_profiles

  # Ensure the staging-only frontend bundle exists. Production mounts a
  # different directory, so this build cannot replace production assets.
  if [[ ! -d "${REPO_ROOT}/frontend/${STAGING_FRONTEND_OUT_DIR}" ]]; then
    _warn "frontend/${STAGING_FRONTEND_OUT_DIR} not found — building staging frontend first..."
    VITE_OPENSCIENCE_API_KEY= VITE_AINRF_API_KEY= \
      OPENSCIENCE_FRONTEND_OUT_DIR="${STAGING_FRONTEND_OUT_DIR}" \
      npm --prefix "${REPO_ROOT}/frontend" run build
    chmod -R a+rX "${REPO_ROOT}/frontend/${STAGING_FRONTEND_OUT_DIR}"
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
  _info "Stopping staging environment and preserving its isolated volumes..."
  "${COMPOSE_CMD[@]}" down --remove-orphans
  _info "Done. Volumes were preserved; use purge with explicit confirmation to remove them."
}

cmd_purge() {
  if [[ "${OPENSCIENCE_STAGING_ALLOW_VOLUME_REMOVAL:-}" != "1" ]]; then
    _error "Set OPENSCIENCE_STAGING_ALLOW_VOLUME_REMOVAL=1 to remove isolated staging volumes."
    exit 2
  fi
  _info "Stopping staging environment and removing isolated volumes..."
  "${COMPOSE_CMD[@]}" down -v --remove-orphans
  _info "Done. Isolated staging volumes removed."
}

cmd_status() {
  echo -e "${BOLD}OpenScience Staging Environment Status${NC}"
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
  _assert_no_background_worker_profiles

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

cmd_smoke() {
  local app_url="${OPENSCIENCE_STAGING_APP_URL:-http://localhost:7192}"
  local backend_url="${OPENSCIENCE_STAGING_BACKEND_URL:-${AINRF_STAGING_URL:-http://localhost:17000}}"
  local build_info_payload
  local expected_commit="${OPENSCIENCE_EXPECTED_BUILD_COMMIT:-}"
  local health_payload
  local http_status
  local identity_payload
  local python_bin
  local -a curl_cmd=(curl --connect-timeout 3 --max-time 10 --silent --show-error)

  if ! command -v curl >/dev/null 2>&1; then
    _error "curl is required for staging smoke checks"
    exit 2
  fi
  python_bin="$(command -v python3 || command -v python || true)"
  if [[ -z "${python_bin}" ]]; then
    _error "python3 or python is required to validate staging JSON responses"
    exit 2
  fi

  _info "Running non-destructive staging smoke"
  _info "App: ${app_url}"
  _info "Backend: ${backend_url}"

  identity_payload="$("${curl_cmd[@]}" --fail "${app_url}/staging-identity.json")"
  "${python_bin}" -c '
import json
import sys

if json.loads(sys.argv[1]).get("environment") != "staging":
    raise SystemExit("target does not identify itself as staging")
' "${identity_payload}"

  health_payload="$("${curl_cmd[@]}" --fail "${backend_url}/health")"
  "${python_bin}" -c '
import json
import sys

payload = json.loads(sys.argv[1])
checks = payload.get("checks", {})
if payload.get("status") != "ok":
    raise SystemExit("health status is not ok")
for name in ("database", "filesystem"):
    if checks.get(name, {}).get("status") != "ok":
        raise SystemExit(f"health check {name} is not ok")
' "${health_payload}"

  "${curl_cmd[@]}" --fail "${app_url}/" >/dev/null
  health_payload="$("${curl_cmd[@]}" --fail "${app_url}/api/health")"
  "${python_bin}" -c '
import json
import sys

if json.loads(sys.argv[1]).get("status") != "ok":
    raise SystemExit("nginx-proxied health status is not ok")
' "${health_payload}"

  build_info_payload="$("${curl_cmd[@]}" --fail "${app_url}/build-info.json")"
  "${python_bin}" -c '
import json
import sys

payload = json.loads(sys.argv[1])
expected = sys.argv[2].strip()
for key in ("short_commit", "committed_at"):
    if not isinstance(payload.get(key), str) or not payload[key].strip():
        raise SystemExit(f"build-info field {key} is missing")
if expected and payload["short_commit"] != expected[:6]:
    raise SystemExit(
        f"frontend commit {payload['short_commit']} does not match expected {expected[:6]}"
    )
' "${build_info_payload}" "${expected_commit}"

  http_status="$("${curl_cmd[@]}" --output /dev/null --write-out '%{http_code}' "${backend_url}/v1/models")"
  if [[ "${http_status}" != "200" ]]; then
    _error "Expected compatibility probe /v1/models to return 200, got ${http_status}"
    exit 1
  fi

  for path in docs openapi.json; do
    http_status="$("${curl_cmd[@]}" --output /dev/null --write-out '%{http_code}' "${app_url}/${path}")"
    if [[ "${http_status}" != "404" ]]; then
      _error "Expected nginx /${path} to return 404, got ${http_status}"
      exit 1
    fi
  done

  _info "Staging smoke passed"
}

# ── Main ───────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: bash scripts/staging.sh <command>

Commands:
  up        Build and start the staging environment
  down      Stop containers and preserve isolated staging volumes
  purge     Remove isolated staging volumes (requires OPENSCIENCE_STAGING_ALLOW_VOLUME_REMOVAL=1)
  status    Show running state and access URLs
  logs      Tail ainrf-staging container logs
  rebuild   Rebuild backend image (keep data volumes)
  creds     Print the admin initial password
  smoke     Run non-destructive GET checks against the running staging environment
  test      Deprecated alias for smoke; does not start or destroy staging
EOF
}

case "${1:-}" in
  up)       shift || true; cmd_up "$@" ;;
  down)     shift || true; cmd_down "$@" ;;
  purge)    shift || true; cmd_purge "$@" ;;
  status)   shift || true; cmd_status "$@" ;;
  logs)     shift || true; cmd_logs "$@" ;;
  rebuild)  shift || true; cmd_rebuild "$@" ;;
  creds)    shift || true; cmd_creds "$@" ;;
  smoke)    shift || true; cmd_smoke "$@" ;;
  test)
    shift || true
    _warn "'test' is deprecated; running the non-destructive 'smoke' command"
    cmd_smoke "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    _error "Unknown command: ${1:-}"
    usage
    exit 1
    ;;
esac

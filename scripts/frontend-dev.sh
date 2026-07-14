#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STATE_ROOT="${OPENSCIENCE_FRONTEND_DEV_STATE_ROOT:-/tmp/openscience-frontend-dev}"
API_KEY="${OPENSCIENCE_FRONTEND_DEV_API_KEY:-openscience-frontend-dev}"
ARTIFACT_SHA="${OPENSCIENCE_FRONTEND_DEV_ARTIFACT_SHA:-100323fd9e36c715f2643fb86ea30cbe16a0f6c6ff707d5ee5c32d352e81b91f}"
API_PORT="${OPENSCIENCE_FRONTEND_DEV_API_PORT:-8000}"
FRONTEND_PORT="${OPENSCIENCE_FRONTEND_DEV_PORT:-5173}"
BACKEND_TARGET="http://127.0.0.1:${API_PORT}"
API_PID=""
WORKER_PID=""

_info() {
  printf '[frontend-dev] %s\n' "$*"
}

_error() {
  printf '[frontend-dev] %s\n' "$*" >&2
}

prepare_fixture() {
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" \
    uv run openscience frontend-dev prepare \
      --state-root "${STATE_ROOT}" \
      --api-key "${API_KEY}" \
      --artifact-sha "${ARTIFACT_SHA}"
}

print_env() {
  printf 'export OPENSCIENCE_STATE_ROOT=%q\n' "${STATE_ROOT}"
  printf 'export OPENSCIENCE_DOMAIN_MODEL_MODE=%q\n' "v2"
  printf 'export OPENSCIENCE_DOMAIN_ARTIFACT_SHA=%q\n' "${ARTIFACT_SHA}"
  printf 'export OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED=%q\n' "false"
  printf 'export OPENSCIENCE_JWT_SECRET=%q\n' "frontend-dev-jwt-secret-not-for-production"
  printf 'export OPENSCIENCE_WEBUI_API_KEY=%q\n' "${API_KEY}"
  printf 'export VITE_OPENSCIENCE_API_KEY=%q\n' "${API_KEY}"
  printf 'export OPENSCIENCE_WEBUI_BACKEND_TARGET=%q\n' "${BACKEND_TARGET}"
}

run_stack() {
  if [[ ! -x "${REPO_ROOT}/frontend/node_modules/.bin/vite" ]]; then
    _error "frontend dependencies are missing; run: npm --prefix frontend ci"
    return 2
  fi
  if ! command -v curl >/dev/null 2>&1; then
    _error "curl is required to wait for the isolated API"
    return 2
  fi

  prepare_fixture >/dev/null
  export OPENSCIENCE_STATE_ROOT="${STATE_ROOT}"
  export OPENSCIENCE_DOMAIN_MODEL_MODE="v2"
  export OPENSCIENCE_DOMAIN_ARTIFACT_SHA="${ARTIFACT_SHA}"
  export OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED="false"
  export OPENSCIENCE_JWT_SECRET="frontend-dev-jwt-secret-not-for-production"
  export OPENSCIENCE_WEBUI_API_KEY="${API_KEY}"
  export VITE_OPENSCIENCE_API_KEY="${API_KEY}"
  export OPENSCIENCE_WEBUI_BACKEND_TARGET="${BACKEND_TARGET}"

  cleanup() {
    if [[ -n "${WORKER_PID}" ]]; then
      kill "${WORKER_PID}" 2>/dev/null || true
    fi
    if [[ -n "${API_PID}" ]]; then
      kill "${API_PID}" 2>/dev/null || true
    fi
    if [[ -n "${WORKER_PID}" ]]; then
      wait "${WORKER_PID}" 2>/dev/null || true
    fi
    if [[ -n "${API_PID}" ]]; then
      wait "${API_PID}" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  _info "starting isolated v2 API on ${BACKEND_TARGET}"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" \
    uv run openscience serve \
      --host 127.0.0.1 \
      --port "${API_PORT}" \
      --state-root "${STATE_ROOT}" &
  API_PID="$!"

  local attempt
  for attempt in $(seq 1 240); do
    if curl --silent --fail --max-time 1 "${BACKEND_TARGET}/health" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "${API_PID}" 2>/dev/null; then
      _error "isolated API exited before becoming healthy"
      return 1
    fi
    sleep 0.25
  done
  if ! curl --silent --fail --max-time 2 "${BACKEND_TARGET}/health" >/dev/null; then
    _error "isolated API did not become healthy"
    return 1
  fi

  _info "starting idle domain worker for truthful capability readiness"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" \
    uv run openscience domain-worker --state-root "${STATE_ROOT}" &
  WORKER_PID="$!"
  sleep 1
  if ! kill -0 "${WORKER_PID}" 2>/dev/null; then
    _error "idle domain worker exited during startup"
    return 1
  fi

  _info "frontend: http://127.0.0.1:${FRONTEND_PORT}"
  _info "state: ${STATE_ROOT} (synthetic; no Docker, staging, L2, or production resources)"
  npm --prefix "${REPO_ROOT}/frontend" run dev -- \
    --host 127.0.0.1 \
    --port "${FRONTEND_PORT}"
}

usage() {
  cat <<'EOF'
Usage: bash scripts/frontend-dev.sh <command>

Commands:
  prepare  Create or reconcile the isolated synthetic committed-v2 state.
  env      Print the environment used by the API, worker, and Vite proxy.
  run      Start the API, idle domain worker, and Vite dev server.

Environment overrides:
  OPENSCIENCE_FRONTEND_DEV_STATE_ROOT
  OPENSCIENCE_FRONTEND_DEV_API_KEY
  OPENSCIENCE_FRONTEND_DEV_ARTIFACT_SHA
  OPENSCIENCE_FRONTEND_DEV_API_PORT
  OPENSCIENCE_FRONTEND_DEV_PORT

The fixture is intentionally not an L2 or browser E2E gate. Client-side
DevTools acceptance remains a later, separate validation step.
EOF
}

case "${1:-help}" in
  prepare)
    prepare_fixture
    ;;
  env)
    print_env
    ;;
  run)
    run_stack
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    _error "unknown command: ${1}"
    usage >&2
    exit 2
    ;;
esac

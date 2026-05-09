#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="dev"
BACKEND_HOST="127.0.0.1"

usage() {
  cat <<'EOF'
Usage: scripts/webui.sh [dev|preview] [--backend-public]

Start the AINRF backend and frontend together with a lightweight shell launcher.

Options:
  dev               Start the Vite dev server on 0.0.0.0:5173 (default)
  preview           Start the Vite preview server on 0.0.0.0:4173
  --backend-public  Bind the backend on 0.0.0.0:8000 instead of 127.0.0.1:8000
  -h, --help        Show this help text
EOF
}

while (($# > 0)); do
  case "$1" in
    dev|preview)
      MODE="$1"
      ;;
    --backend-public)
      BACKEND_HOST="0.0.0.0"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "webui.sh requires python3 or python on PATH" >&2
  exit 1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

if [[ -z "${AINRF_WEBUI_API_KEY:-}" ]]; then
  AINRF_WEBUI_API_KEY="$("${PYTHON_BIN}" - <<'PY'
import secrets

print(secrets.token_urlsafe(32))
PY
)"
fi

export AINRF_WEBUI_API_KEY
export AINRF_API_KEY_HASHES="$("${PYTHON_BIN}" - <<'PY'
import hashlib
import os

print(hashlib.sha256(os.environ["AINRF_WEBUI_API_KEY"].encode("utf-8")).hexdigest())
PY
)"

mkdir -p "${HOME}/.ainrf"

# Pre-launch cleanup: kill stale ainrf backend and vite frontend processes
echo "Checking for stale processes..."

# Kill any process still listening on the backend port
if command -v lsof &>/dev/null; then
  stale_pids=$(lsof -ti:8000 2>/dev/null || true)
  if [[ -n "${stale_pids}" ]]; then
    echo "Stopping stale backend on port 8000..."
    kill ${stale_pids} 2>/dev/null || true
    sleep 1
    stale_pids=$(lsof -ti:8000 2>/dev/null || true)
    if [[ -n "${stale_pids}" ]]; then
      kill -9 ${stale_pids} 2>/dev/null || true
      sleep 1
    fi
  fi
fi

# Kill vite dev-server processes that were started from this project's frontend directory
# Linux: inspect /proc/{pid}/cwd and cmdline
if [[ -d /proc ]]; then
  for pid in $(pgrep -x node 2>/dev/null || true); do
    if [[ -r "/proc/${pid}/cwd" ]]; then
      cwd=$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)
      if [[ "${cwd}" == "${REPO_ROOT}/frontend" ]]; then
        cmdline=$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)
        if [[ "${cmdline}" == *"vite"* ]]; then
          echo "Stopping stale frontend dev server (pid ${pid})..."
          kill "${pid}" 2>/dev/null || true
        fi
      fi
    fi
  done
fi

# macOS fallback: kill any vite process whose cwd matches our frontend dir via lsof +Apple
if [[ "$(uname -s)" == "Darwin" ]] && command -v lsof &>/dev/null; then
  for pid in $(pgrep -x node 2>/dev/null || true); do
    cwd=$(lsof -a -p "${pid}" -d cwd 2>/dev/null | awk 'NR==2{print $NF}' || true)
    if [[ "${cwd}" == "${REPO_ROOT}/frontend" ]]; then
      cmdline=$(ps -p "${pid}" -o command= 2>/dev/null || true)
      if [[ "${cmdline}" == *"vite"* ]]; then
        echo "Stopping stale frontend dev server (pid ${pid})..."
        kill "${pid}" 2>/dev/null || true
      fi
    fi
  done
fi

sleep 1

BACKEND_COMMAND=(
  uv
  run
  ainrf
  serve
  --host
  "${BACKEND_HOST}"
  --port
  "8000"
  --state-root
  "${HOME}/.ainrf"
)

if [[ "${MODE}" == "preview" ]]; then
  FRONTEND_COMMAND=(npm run preview -- --host 0.0.0.0 --port 4173)
else
  FRONTEND_COMMAND=(npm run dev -- --host 0.0.0.0 --port 5173)
fi

backend_pid=""
frontend_pid=""

cleanup() {
  local exit_code="$?"
  trap - EXIT INT TERM
  if [[ -n "${frontend_pid}" ]] && kill -0 "${frontend_pid}" 2>/dev/null; then
    kill "${frontend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid}" ]] && kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

echo "Starting AINRF backend on ${BACKEND_HOST}:8000"
echo "Starting AINRF frontend in ${MODE} mode"

(
  cd "${REPO_ROOT}"
  exec "${BACKEND_COMMAND[@]}"
) &
backend_pid="$!"

(
  cd "${REPO_ROOT}/frontend"
  exec "${FRONTEND_COMMAND[@]}"
) &
frontend_pid="$!"

wait -n "${backend_pid}" "${frontend_pid}"

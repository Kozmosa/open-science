#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="dev"
BACKEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"

usage() {
  cat <<'EOF'
Usage: scripts/webui.sh [dev|preview] [--backend-public]

Compatibility launcher for a personal ~/.ainrf state root. New isolated
frontend development should use scripts/dev.sh directly.

Options:
  dev               Start the Vite dev server on 0.0.0.0:5173 (default)
  preview           Start the Vite preview server on 0.0.0.0:4173
  --backend-public  Bind the backend on 0.0.0.0:8000 instead of 127.0.0.1:8000
  -h, --help        Show this help text
EOF
}

while (($# > 0)); do
  case "$1" in
    dev)
      MODE="dev"
      FRONTEND_PORT="5173"
      ;;
    preview)
      MODE="preview"
      FRONTEND_PORT="4173"
      ;;
    --backend-public)
      BACKEND_HOST="0.0.0.0"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

args=(
  up
  --mode "${MODE}"
  --personal-state-root "${HOME}/.ainrf"
  --bind-host "${BACKEND_HOST}"
  --frontend-host "0.0.0.0"
  --api-port "8000"
  --frontend-port "${FRONTEND_PORT}"
  --foreground
)
if [[ -n "${OPENSCIENCE_WEBUI_API_KEY:-${AINRF_WEBUI_API_KEY:-}}" ]]; then
  args+=(--api-key "${OPENSCIENCE_WEBUI_API_KEY:-${AINRF_WEBUI_API_KEY}}")
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
exec "${SCRIPT_DIR}/dev.sh" "${args[@]}"

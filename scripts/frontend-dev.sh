#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: bash scripts/frontend-dev.sh <command>

Compatibility commands:
  prepare  Prepare the selected isolated synthetic committed-v2 profile.
  env      Print the environment used by the API, worker, and Vite proxy.
  run      Start the isolated stack in the foreground.

Environment overrides:
  OPENSCIENCE_FRONTEND_DEV_STATE_ROOT
  OPENSCIENCE_FRONTEND_DEV_API_KEY
  OPENSCIENCE_FRONTEND_DEV_ARTIFACT_SHA
  OPENSCIENCE_FRONTEND_DEV_PROFILE
  OPENSCIENCE_FRONTEND_DEV_API_PORT
  OPENSCIENCE_FRONTEND_DEV_PORT

The canonical entrypoint is now scripts/dev.sh. The fixture remains outside
L2 and browser E2E gates; client DevTools acceptance is a separate step.
EOF
}

case "${1:-help}" in
  prepare)
    mapped_command="prepare"
    ;;
  env)
    mapped_command="env"
    ;;
  run)
    mapped_command="up"
    ;;
  help|-h|--help)
    usage
    exit 0
    ;;
  *)
    printf '[frontend-dev] unknown command: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac
shift || true

args=("${mapped_command}" --profile "${OPENSCIENCE_FRONTEND_DEV_PROFILE:-full}")
if [[ "${mapped_command}" == "up" ]]; then
  args+=(--foreground)
fi
if [[ -n "${OPENSCIENCE_FRONTEND_DEV_STATE_ROOT:-}" ]]; then
  args+=(--state-root "${OPENSCIENCE_FRONTEND_DEV_STATE_ROOT}")
fi
if [[ -n "${OPENSCIENCE_FRONTEND_DEV_API_KEY:-}" ]]; then
  args+=(--api-key "${OPENSCIENCE_FRONTEND_DEV_API_KEY}")
fi
if [[ -n "${OPENSCIENCE_FRONTEND_DEV_ARTIFACT_SHA:-}" ]]; then
  args+=(--artifact-sha "${OPENSCIENCE_FRONTEND_DEV_ARTIFACT_SHA}")
fi
if [[ -n "${OPENSCIENCE_FRONTEND_DEV_API_PORT:-}" ]]; then
  args+=(--api-port "${OPENSCIENCE_FRONTEND_DEV_API_PORT}")
fi
if [[ -n "${OPENSCIENCE_FRONTEND_DEV_PORT:-}" ]]; then
  args+=(--frontend-port "${OPENSCIENCE_FRONTEND_DEV_PORT}")
fi

exec "${SCRIPT_DIR}/dev.sh" "${args[@]}" "$@"

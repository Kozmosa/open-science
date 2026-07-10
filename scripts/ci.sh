#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export UV_LOCKED=1
export OPENSCIENCE_PYTEST_WORKERS="${OPENSCIENCE_PYTEST_WORKERS:-8}"
export OPENSCIENCE_VITEST_WORKERS="${OPENSCIENCE_VITEST_WORKERS:-4}"

_info() {
  printf '\n[osci-ci] %s\n' "$*"
}

_run() {
  printf '[osci-ci] +'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

run_python_quality() {
  _info "Python lint and format"
  _run uv run ruff check src tests scripts
  _run uv run ruff format --check src tests scripts
}

run_backend_fast() {
  _info "Backend fast tests (${OPENSCIENCE_PYTEST_WORKERS} workers)"
  _run "${REPO_ROOT}/scripts/test.sh" fast
}

run_backend_gate() {
  run_python_quality
  _info "Python type check"
  _run uv run ty check
  _info "Backend full deterministic test gate"
  _run "${REPO_ROOT}/scripts/test.sh" all
}

run_frontend_lint() {
  _info "Frontend lint"
  _run npm --prefix frontend run lint
}

run_frontend_tests() {
  if [[ ! "${OPENSCIENCE_VITEST_WORKERS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'OPENSCIENCE_VITEST_WORKERS must be a positive integer, got: %s\n' \
      "${OPENSCIENCE_VITEST_WORKERS}" >&2
    return 2
  fi
  _info "Frontend correctness tests"
  _run npm --prefix frontend run test:run
}

run_frontend_gate() {
  run_frontend_lint
  run_frontend_tests
  _info "Frontend production build"
  _run npm --prefix frontend run build
}

run_docs_gate() {
  _info "Documentation production build"
  _run npm --prefix docs-site run build
}

run_l0() {
  _info "L0 agent/developer inner loop"
  run_python_quality
  run_backend_fast
  run_frontend_lint
  run_frontend_tests
}

describe_layers() {
  cat <<'EOF'
OpenScience five-layer hybrid CI

  L0  Agent/developer inner loop       implemented: scripts/ci.sh l0
  L1  Deterministic quality gate       implemented: scripts/ci.sh l1
  L2  Isolated container integration   planned; must not use shared staging
  L3  Deep system verification         planned; trusted local serialized lane
  L4  Release acceptance               planned; immutable artifact + approval

L0/L1 never start Docker or contact production/staging services.
EOF
}

usage() {
  cat <<'EOF'
Usage: bash scripts/ci.sh <command>

Commands:
  l0             Run the bounded agent/developer inner loop
  l1             Run the complete deterministic backend, frontend, and docs gate
  l1-backend     Run Python lint, format, types, and backend tests
  l1-frontend    Run frontend lint, correctness tests, and production build
  l1-docs        Build the public documentation site
  describe       Describe all five CI layers and their implementation status
  help           Show this help

Environment:
  OPENSCIENCE_PYTEST_WORKERS  Positive integer worker limit (default: 8)
  OPENSCIENCE_VITEST_WORKERS  Positive integer worker limit (default: 4)
  UV_CACHE_DIR                uv cache location (default: /tmp/uv-cache)
EOF
}

case "${1:-help}" in
  l0)
    run_l0
    ;;
  l1)
    run_backend_gate
    run_frontend_gate
    run_docs_gate
    ;;
  l1-backend)
    run_backend_gate
    ;;
  l1-frontend)
    run_frontend_gate
    ;;
  l1-docs)
    run_docs_gate
    ;;
  describe)
    describe_layers
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    printf 'Unknown CI command: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac

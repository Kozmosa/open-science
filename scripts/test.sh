#!/usr/bin/env bash
# Unified local backend test runner for OpenScience.
#
# Usage:
#   bash scripts/test.sh fast        # quick pre-commit suite (default)
#   bash scripts/test.sh unit        # unit tests only
#   bash scripts/test.sh middleware  # middleware/security tests
#   bash scripts/test.sh api         # HTTP API integration tests
#   bash scripts/test.sh engine      # execution engine / terminal tests
#   bash scripts/test.sh concurrent  # race/contention tests (serial, -n0)
#   bash scripts/test.sh json_edge   # JSON persistence edge cases
#   bash scripts/test.sh db_race     # SQLite contention tests (serial, -n0)
#   bash scripts/test.sh production-contract # in-process production contract tests
#   bash scripts/test.sh all         # full suite
#   bash scripts/test.sh staging     # non-destructive smoke against an already-running staging
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
PYTEST_WORKERS="${OPENSCIENCE_PYTEST_WORKERS:-8}"

if [[ ! "${PYTEST_WORKERS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "OPENSCIENCE_PYTEST_WORKERS must be a positive integer, got: ${PYTEST_WORKERS}" >&2
  exit 2
fi

run_parallel() {
  uv run pytest "$@" -n "${PYTEST_WORKERS}"
}

run_serial() {
  uv run pytest "$@" -n 0
}

run_partitioned() {
  local marker="$1"
  local parallel_timeout="$2"
  local serial_timeout="$3"

  run_parallel -m "(${marker}) and not concurrent and not db_race" -q \
    --timeout="${parallel_timeout}"
  run_serial -m "(${marker}) and (concurrent or db_race)" -q \
    --timeout="${serial_timeout}"
}

case "${1:-fast}" in
  unit)        run_partitioned unit 30 120 ;;
  middleware)  run_parallel -m middleware -q --timeout=30 ;;
  api)         run_partitioned api 60 120 ;;
  engine)      run_partitioned engine 60 120 ;;
  concurrent)  run_serial -m concurrent -q --timeout=120 ;;
  json_edge)   run_parallel -m json_edge -q --timeout=30 ;;
  db_race)     run_serial -m db_race -q --timeout=120 ;;
  integration|production-contract)
    run_parallel -m integration -q --timeout=120
    ;;
  fast)
    run_parallel -m '(unit or middleware or json_edge) and not concurrent and not db_race' -q --timeout=30
    ;;
  all)
    run_parallel tests/ -m 'not concurrent and not db_race' -q --timeout=60
    run_serial tests/ -m 'concurrent or db_race' -q --timeout=120
    ;;
  staging)
    if [[ -z "${OPENSCIENCE_EXPECTED_BUILD_COMMIT:-}" ]]; then
      echo "OPENSCIENCE_EXPECTED_BUILD_COMMIT is required for the staging test lane" >&2
      exit 2
    fi
    "${REPO_ROOT}/scripts/staging.sh" smoke
    ;;
  *)
    echo "Unknown test suite: $1" >&2
    echo "Usage: bash scripts/test.sh {fast|unit|middleware|api|engine|concurrent|json_edge|db_race|production-contract|all|staging}" >&2
    exit 1
    ;;
esac

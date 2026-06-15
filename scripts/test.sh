#!/usr/bin/env bash
# Unified local test runner for Scholar-Agent.
#
# Usage:
#   bash scripts/test.sh fast        # quick pre-commit suite (default)
#   bash scripts/test.sh unit        # unit tests only
#   bash scripts/test.sh middleware  # middleware/security tests
#   bash scripts/test.sh api         # HTTP API integration tests
#   bash scripts/test.sh engine      # execution engine / terminal tests
#   bash scripts/test.sh concurrent  # race/contention tests (-n1)
#   bash scripts/test.sh json_edge   # JSON persistence edge cases
#   bash scripts/test.sh db_race     # SQLite contention tests (-n1)
#   bash scripts/test.sh integration # integration tests
#   bash scripts/test.sh all         # full suite
#   bash scripts/test.sh staging     # run integration tests against staging container
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

case "${1:-fast}" in
  unit)        uv run pytest -m unit -q --timeout=30 ;;
  middleware)  uv run pytest -m middleware -q --timeout=30 ;;
  api)         uv run pytest -m api -q --timeout=60 ;;
  engine)      uv run pytest -m engine -q --timeout=60 ;;
  concurrent)  uv run pytest -m concurrent -q --timeout=60 -n1 ;;
  json_edge)   uv run pytest -m json_edge -q --timeout=30 ;;
  db_race)     uv run pytest -m db_race -q --timeout=60 -n1 ;;
  integration) uv run pytest -m integration -q --timeout=120 ;;
  fast)        uv run pytest -m 'unit or middleware or json_edge' -q --timeout=30 ;;
  all)         uv run pytest -q --timeout=60 ;;
  staging)
    bash scripts/staging.sh up
    trap 'bash scripts/staging.sh down' EXIT
    AINRF_STAGING_URL="http://localhost:17000" uv run pytest -m integration -q --timeout=180
    ;;
  *)
    echo "Unknown test suite: $1" >&2
    echo "Usage: bash scripts/test.sh {fast|unit|middleware|api|engine|concurrent|json_edge|db_race|integration|all|staging}" >&2
    exit 1
    ;;
esac

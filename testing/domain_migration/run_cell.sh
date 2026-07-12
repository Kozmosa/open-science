#!/usr/bin/env bash
set -euo pipefail

# A disposable, non-Docker migration cell. It deliberately uses a unique
# state root and leaves no shared staging or production resources behind.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_FIXTURE="${1:-${ROOT}/testing/domain_migration/fixtures/empty}"
CELL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/openscience-migration-cell.XXXXXX")"
trap 'rm -rf "${CELL_ROOT}"' EXIT
cp -R "${SOURCE_FIXTURE}/." "${CELL_ROOT}/"
mkdir -p "${CELL_ROOT}/runtime"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv --directory "${ROOT}" run \
  openscience domain-migration dry-run --state-root "${CELL_ROOT}"

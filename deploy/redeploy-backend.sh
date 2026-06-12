#!/usr/bin/env bash
# ── Rebuild + redeploy the ainrf BACKEND image ───────────────────
#
# Stamps the host git commit into the image (baked as
# /opt/ainrf/backend-build-info.json) so /settings/deployment-version
# reports the commit the backend was actually built from.
#
# Usage:
#   bash deploy/redeploy-backend.sh
#
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

export AINRF_BUILD_COMMIT
export AINRF_BUILD_COMMITTED_AT
AINRF_BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short=6 HEAD)"
AINRF_BUILD_COMMITTED_AT="$(git -C "${REPO_ROOT}" show -s --format=%cd --date=format:%Y%m%d-%H%M HEAD)"

echo "=== Backend build provenance ==="
echo "  commit:      ${AINRF_BUILD_COMMIT}"
echo "  committed_at: ${AINRF_BUILD_COMMITTED_AT}"
echo

exec docker compose -f docker-compose.cpu.yml up -d --build ainrf "$@"

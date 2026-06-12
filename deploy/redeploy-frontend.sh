#!/usr/bin/env bash
# ── Rebuild + redeploy the FRONTEND (nginx static) ───────────────
#
# The frontend ships its own build-info (frontend/dist/build-info.json),
# captured at `npm run build` time. nginx bind-mounts the host
# frontend/dist, so a rebuild + nginx restart is enough — no image
# rebuild needed.
#
# Usage:
#   bash deploy/redeploy-frontend.sh
#
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

echo "=== Building frontend (host) ==="
cd "${REPO_ROOT}/frontend"
npm run build

echo
echo "=== Restarting nginx ==="
cd "${REPO_ROOT}/deploy"
exec docker compose -f docker-compose.cpu.yml restart nginx "$@"

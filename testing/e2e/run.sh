#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# AINRF E2E Test Environment Manager
# ═══════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.yml"
PROJECT_NAME="ainrf-e2e"
COMPOSE="docker compose -p $PROJECT_NAME -f $COMPOSE_FILE"

usage() {
    cat << 'EOF'
AINRF E2E Test Environment

Usage:
  ./run.sh up        Build + start, seed test data, print credentials
  ./run.sh down      Stop and remove all containers + volumes
  ./run.sh status    Show running containers and test URLs
  ./run.sh logs      Tail container logs
  ./run.sh creds     Print stored credentials (from inside container)
  ./run.sh rebuild   Rebuild image and restart (preserves nothing)

Environment:
  AITestPort   Host port for direct backend access  (default: 8199)
  AIWebPort    Host port for nginx/frontend access   (default: 8198)

EOF
}

cmd_up() {
    echo "==> Starting containers (using local ainrf:latest image)..."
    $COMPOSE up -d

    echo "==> Waiting for backend to become healthy..."
    local max_wait=120
    local elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        if $COMPOSE ps ainrf 2>/dev/null | grep -q "healthy"; then
            echo "    ✓ Backend is healthy"
            break
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [ $elapsed -ge $max_wait ]; then
        echo "    ✗ Backend did not become healthy in ${max_wait}s"
        echo "    Check logs: $COMPOSE logs ainrf"
        exit 1
    fi

    echo "==> Seeding test users..."
    docker cp config/seed.py ainrf-e2e:/tmp/e2e-seed.py
    $COMPOSE exec ainrf python3 /tmp/e2e-seed.py

    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  AINRF E2E Test Environment Ready"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "  Frontend:  http://localhost:${AIWebPort:-8198}"
    echo "  Backend:   http://localhost:${AITestPort:-8199}"
    echo "  Health:    http://localhost:${AITestPort:-8199}/health"
    echo ""
    cmd_creds
    echo ""
    echo "  To tear down: ./run.sh down"
    echo "════════════════════════════════════════════════════════════"
}

cmd_down() {
    echo "==> Tearing down E2E environment..."
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
    echo "    ✓ All containers and volumes removed"
}

cmd_status() {
    $COMPOSE ps
    echo ""
    echo "Frontend: http://localhost:${AIWebPort:-8198}"
    echo "Backend:  http://localhost:${AITestPort:-8199}"
}

cmd_logs() {
    $COMPOSE logs -f --tail=100
}

cmd_creds() {
    local creds
    creds=$($COMPOSE exec -T ainrf cat /opt/ainrf/state/e2e-credentials.json 2>/dev/null) || {
        echo "  (credentials not yet available — run ./run.sh up first)"
        return
    }
    echo "  Test Users:"
    echo "$creds" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for user, info in data.items():
    print(f'    {user:10s}  password={info[\"password\"]}  role={info[\"role\"]}')
" 2>/dev/null || echo "$creds"
}

cmd_rebuild() {
    cmd_down
    docker rmi ainrf:latest 2>/dev/null || true
    docker builder prune -f --filter "label=com.docker.compose.project=$PROJECT_NAME" 2>/dev/null || true
    cmd_up
}

case "${1:-help}" in
    up)      cmd_up ;;
    down)    cmd_down ;;
    status)  cmd_status ;;
    logs)    cmd_logs ;;
    creds)   cmd_creds ;;
    rebuild) cmd_rebuild ;;
    *)       usage ;;
esac

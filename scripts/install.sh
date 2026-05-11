#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Prerequisite checks ─────────────────────────────────────────────

check_command() {
  local name="$1"
  if ! command -v "$name" &>/dev/null; then
    error "'$name' is not installed or not on PATH."
    return 1
  fi
}

missing=0

if ! check_command uv; then
  echo "  Install uv: https://docs.astral.sh/uv/getting-started/installation/"
  missing=1
fi

if ! check_command npm; then
  echo "  Install Node.js (includes npm): https://nodejs.org/"
  missing=1
fi

if [[ "$missing" -ne 0 ]]; then
  error "Missing prerequisites. Install the tools above and re-run."
  exit 1
fi

# ── Backend (Python via uv) ──────────────────────────────────────────

info "Installing backend dependencies ..."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
(cd "${REPO_ROOT}" && uv sync)
info "Backend dependencies installed."

# ── Frontend (Node via npm) ──────────────────────────────────────────

info "Installing frontend dependencies ..."
(cd "${REPO_ROOT}/frontend" && npm ci)
info "Frontend dependencies installed."

# ── Pre-commit hooks ─────────────────────────────────────────────────

info "Setting up pre-commit hooks ..."
if (cd "${REPO_ROOT}" && uv run pre-commit install 2>/dev/null); then
  info "Pre-commit hooks installed."
else
  warn "pre-commit install skipped (hooks path may be managed externally)"
fi

# ── Done ─────────────────────────────────────────────────────────────

echo ""
info "Setup complete. You can now run: scripts/webui.sh"

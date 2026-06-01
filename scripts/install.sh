#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "${BLUE}[STEP]${NC}  $*"; }

# ── Defaults ─────────────────────────────────────────────────────────
AUTO_YES=false
NO_START=false

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [OPTIONS]

Install AINRF development environment automatically.
Detects and installs uv, fnm, and Node.js LTS if missing.

Options:
  -y, --yes        Non-interactive mode: auto-install all missing tools
  --no-start       Do not start AINRF services after installation
  -h, --help       Show this help message

Examples:
  scripts/install.sh              # Interactive installation
  scripts/install.sh -y           # Auto-install everything
  scripts/install.sh -y --no-start # Auto-install but don't start services
EOF
}

while (($# > 0)); do
  case "$1" in
    -y|--yes)
      AUTO_YES=true
      ;;
    --no-start)
      NO_START=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      usage >&2
      exit 1
      ;;
  esac
  shift
done

# ── Helpers ──────────────────────────────────────────────────────────

download_with_retry() {
  local url="$1"
  local output="${2:-/dev/stdout}"
  local max_retries=3
  local attempt=1

  while [[ $attempt -le $max_retries ]]; do
    if curl -fsSL "$url" -o "$output" 2>/dev/null; then
      return 0
    fi
    warn "Download failed (attempt $attempt/$max_retries), retrying in 2s..."
    sleep 2
    ((attempt++)) || true
  done

  error "Failed to download after $max_retries attempts: $url"
  return 1
}

check_command() {
  command -v "$1" &>/dev/null
}

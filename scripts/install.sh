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
      error "Unknown option: $1" >&2
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

# ── OS / Architecture Detection ──────────────────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)
    OS_TYPE="linux"
    ;;
  Darwin)
    OS_TYPE="macos"
    ;;
  *)
    error "Unsupported operating system: $OS"
    error "AINRF install script only supports Linux and macOS."
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64)
    ARCH_TYPE="x86_64"
    ;;
  aarch64|arm64)
    ARCH_TYPE="aarch64"
    ;;
  *)
    error "Unsupported architecture: $ARCH"
    error "Supported architectures: x86_64, aarch64/arm64"
    exit 1
    ;;
esac

info "Detected platform: $OS_TYPE ($ARCH_TYPE)"

# ── Python Detection ─────────────────────────────────────────────────

find_python() {
  local py_cmd
  for py_cmd in python3 python; do
    if check_command "$py_cmd"; then
      echo "$py_cmd"
      return 0
    fi
  done
  return 1
}

check_python_version() {
  local py_cmd="$1"
  local version
  version="$($py_cmd --version 2>&1 | awk '{print $2}')"
  local major minor
  major="$(echo "$version" | cut -d. -f1)"
  minor="$(echo "$version" | cut -d. -f2)"

  if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 13 ]]; }; then
    echo "$version"
    return 0
  fi
  return 1
}

step "Checking Python ..."
PYTHON_CMD=""
if ! PYTHON_CMD="$(find_python)"; then
  error "Python is not installed or not on PATH."
  error "AINRF requires Python 3.13 or later."
  error "Please install Python 3.13+ and re-run this script."
  exit 1
fi

PYTHON_VERSION=""
if ! PYTHON_VERSION="$(check_python_version "$PYTHON_CMD")"; then
  local current_version
  current_version="$($PYTHON_CMD --version 2>&1 | awk '{print $2}')"
  error "Python $current_version is too old."
  error "AINRF requires Python 3.13 or later."
  error "Please upgrade Python and re-run this script."
  exit 1
fi

info "Found Python $PYTHON_VERSION ($PYTHON_CMD)"

# ── Interactive Prompts ──────────────────────────────────────────────

prompt_choice() {
  local message="$1"
  local option1="$2"
  local option2="$3"
  local option3="$4"
  local choice

  if [[ "$AUTO_YES" == true ]]; then
    echo "3"
    return 0
  fi

  echo ""
  error "$message"
  echo ""
  echo "Options:"
  echo "  1) $option1"
  echo "  2) $option2"
  echo "  3) $option3"
  echo ""

  while true; do
    read -rp "Enter your choice [1/2/3]: " choice
    case "$choice" in
      1|2|3)
        echo "$choice"
        return 0
        ;;
      *)
        warn "Invalid choice. Please enter 1, 2, or 3."
        ;;
    esac
  done
}

# ── UV Installation ──────────────────────────────────────────────────

install_uv() {
  step "Installing uv ..."

  local install_script
  install_script="$(mktemp)"
  trap 'rm -f "$install_script"' RETURN

  if ! download_with_retry "https://astral.sh/uv/install.sh" "$install_script"; then
    error "Failed to download uv installer."
    return 1
  fi

  if ! bash "$install_script"; then
    error "uv installation failed."
    return 1
  fi

  # Refresh PATH to include uv
  export PATH="$HOME/.local/bin:$PATH"

  if ! check_command uv; then
    error "uv was installed but is not on PATH."
    error "Please restart your shell or run: export PATH=\"$HOME/.local/bin:\$PATH\""
    return 1
  fi

  info "uv installed successfully: $(uv --version)"
}

# ── UV Detection & Installation ──────────────────────────────────────

step "Checking uv ..."
UV_INSTALLED=false

while true; do
  if check_command uv; then
    UV_INSTALLED=true
    info "Found uv: $(uv --version)"
    break
  fi

  local choice
  choice="$(prompt_choice \
    "uv is not installed or not on PATH." \
    "Exit and install uv manually (https://docs.astral.sh/uv/getting-started/installation/)" \
    "Retry detection after manual installation" \
    "Let the script install uv automatically")"

  case "$choice" in
    1)
      error "Exiting. Please install uv manually and re-run."
      exit 1
      ;;
    2)
      # Retry loop will check again
      continue
      ;;
    3)
      if ! install_uv; then
        error "Failed to install uv automatically."
        error "Please install uv manually and re-run."
        exit 1
      fi
      break
      ;;
  esac
done

# ── Node.js Detection ────────────────────────────────────────────────

check_node_version() {
  local node_cmd="$1"
  local version
  version="$($node_cmd --version 2>/dev/null | sed 's/^v//')"
  local major
  major="$(echo "$version" | cut -d. -f1)"

  if [[ -n "$major" ]] && [[ "$major" -ge 22 ]]; then
    echo "$version"
    return 0
  fi
  return 1
}

# ── fnm + Node LTS Installation ──────────────────────────────────────

install_fnm_and_node() {
  step "Installing fnm (Fast Node Manager) ..."

  local install_script
  install_script="$(mktemp)"
  trap 'rm -f "$install_script"' RETURN

  if ! download_with_retry "https://fnm.vercel.app/install" "$install_script"; then
    error "Failed to download fnm installer."
    return 1
  fi

  # Install fnm to ~/.local/share/fnm
  if ! bash "$install_script" --skip-shell; then
    error "fnm installation failed."
    return 1
  fi

  # Set up fnm environment
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$(fnm env --shell bash)"

  if ! check_command fnm; then
    error "fnm was installed but is not on PATH."
    return 1
  fi

  info "fnm installed: $(fnm --version)"

  step "Installing Node.js LTS ..."

  if ! fnm install --lts; then
    error "Failed to install Node.js LTS."
    return 1
  fi

  if ! fnm use --lts; then
    error "Failed to activate Node.js LTS."
    return 1
  fi

  if ! check_command node; then
    error "Node.js was installed but is not on PATH."
    return 1
  fi

  local node_version
  node_version="$(node --version | sed 's/^v//')"
  info "Node.js LTS installed: v$node_version"

  if ! check_command npm; then
    error "npm is not available after Node.js installation."
    return 1
  fi

  info "npm installed: $(npm --version)"
}

# ── Node.js/npm Detection & Installation ─────────────────────────────

step "Checking Node.js and npm ..."
NODE_INSTALLED=false

while true; do
  if check_command node; then
    local node_version
    if node_version="$(check_node_version node)"; then
      if check_command npm; then
        NODE_INSTALLED=true
        info "Found Node.js v$node_version and npm $(npm --version)"
        break
      fi
    fi
  fi

  local choice
  choice="$(prompt_choice \
    "Node.js 22+ LTS and npm are required but not found." \
    "Exit and install Node.js manually (https://nodejs.org/)" \
    "Retry detection after manual installation" \
    "Let the script install fnm and Node.js LTS automatically")"

  case "$choice" in
    1)
      error "Exiting. Please install Node.js 22+ LTS manually and re-run."
      exit 1
      ;;
    2)
      continue
      ;;
    3)
      if ! install_fnm_and_node; then
        error "Failed to install Node.js automatically."
        error "Please install Node.js 22+ LTS manually and re-run."
        exit 1
      fi
      break
      ;;
  esac
done

# ── Project Dependencies ─────────────────────────────────────────────

step "Installing Python dependencies (uv sync) ..."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
(cd "$REPO_ROOT" && uv sync)
info "Python dependencies installed."

step "Installing frontend dependencies (npm ci) ..."
(cd "$REPO_ROOT/frontend" && npm ci)
info "Frontend dependencies installed."

# ── Service Startup ──────────────────────────────────────────────────

if [[ "$NO_START" == true ]]; then
  echo ""
  info "Installation complete!"
  info "To start AINRF services, run: scripts/webui.sh"
  exit 0
fi

if [[ "$AUTO_YES" == true ]]; then
  step "Starting AINRF services ..."
  exec "$REPO_ROOT/scripts/webui.sh"
fi

echo ""
info "Installation complete!"
echo ""

while true; do
  read -rp "Start AINRF services now? [Y/n]: " start_choice
  start_choice="${start_choice:-Y}"
  case "${start_choice,,}" in
    y|yes)
      step "Starting AINRF services ..."
      exec "$REPO_ROOT/scripts/webui.sh"
      ;;
    n|no)
      info "Skipped. To start services later, run: scripts/webui.sh"
      exit 0
      ;;
    *)
      warn "Please answer Y or n."
      ;;
  esac
done

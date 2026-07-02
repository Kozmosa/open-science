#!/usr/bin/env bash
# ── OpenScience Lab Deployment Script ──────────────────────────────────
#
# Prerequisites:
#   - Ubuntu 22.04+ / Debian 12+
#   - Root or sudo access
#   - Python 3.13+, Node.js 20+
#   - Nginx installed
#
# Usage:
#   sudo bash deploy/deploy.sh [--install-dir /opt/ainrf] [--state-dir /opt/ainrf/state]
#
set -euo pipefail

INSTALL_DIR="${AINRF_INSTALL_DIR:-/opt/ainrf}"
STATE_DIR="${AINRF_STATE_DIR:-${INSTALL_DIR}/state}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== OpenScience Lab Deployment ==="
echo "Install dir: ${INSTALL_DIR}"
echo "State dir:   ${STATE_DIR}"
echo "Repo root:   ${REPO_ROOT}"
echo ""

# ── 1. Create user ────────────────────────────────────────────
if ! id -u ainrf &>/dev/null; then
    echo "[1/7] Creating ainrf system user..."
    useradd --system --create-home --shell /bin/bash ainrf
else
    echo "[1/7] User 'ainrf' already exists."
fi

# ── 2. Install directory structure ─────────────────────────────
echo "[2/7] Setting up directories..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${STATE_DIR}"
mkdir -p "${STATE_DIR}/runtime"

# ── 3. Install Python package ──────────────────────────────────
echo "[3/7] Installing Python package..."
if command -v uv &>/dev/null; then
    uv venv "${INSTALL_DIR}/.venv" --python 3.13
    uv pip install --python "${INSTALL_DIR}/.venv/bin/python" "${REPO_ROOT}"
else
    python3 -m venv "${INSTALL_DIR}/.venv"
    "${INSTALL_DIR}/.venv/bin/pip" install "${REPO_ROOT}"
fi

# ── 4. Build and install frontend ──────────────────────────────
echo "[4/7] Building frontend..."
cd "${REPO_ROOT}/frontend"
npm ci
npm run build
rm -rf "${INSTALL_DIR}/frontend/dist"
mkdir -p "${INSTALL_DIR}/frontend"
cp -r dist "${INSTALL_DIR}/frontend/dist"

# ── 5. Generate secrets ────────────────────────────────────────
echo "[5/7] Generating secrets..."
JWT_SECRET="$("${INSTALL_DIR}/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")"
API_KEY="$("${INSTALL_DIR}/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))")"
API_KEY_HASH="$("${INSTALL_DIR}/.venv/bin/python" -c "from hashlib import sha256; print(sha256('${API_KEY}'.encode()).hexdigest())")"

echo ""
echo "    Generated API key (SAVE THIS — it won't be shown again):"
echo "    ${API_KEY}"
echo ""

# ── 6. Install Nginx config ────────────────────────────────────
echo "[6/7] Installing Nginx config..."
cp "${REPO_ROOT}/deploy/nginx.conf" /etc/nginx/sites-available/ainrf
if [ ! -L /etc/nginx/sites-enabled/ainrf ]; then
    ln -s /etc/nginx/sites-available/ainrf /etc/nginx/sites-enabled/ainrf
fi

# Generate self-signed TLS cert for lab use
if [ ! -f /etc/ssl/certs/ainrf-lab.pem ]; then
    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout /etc/ssl/private/ainrf-lab.key \
        -out /etc/ssl/certs/ainrf-lab.pem \
        -subj "/CN=ainrf-lab" 2>/dev/null
    echo "    Generated self-signed TLS certificate (10-year validity)."
fi

nginx -t

# ── 7. Install systemd service ─────────────────────────────────
echo "[7/7] Installing systemd service..."
sed -e "s|CHANGE_ME_GENERATE_A_SECRET|${JWT_SECRET}|" \
    -e "s|CHANGE_ME_COMPUTE_SHA256|${API_KEY_HASH}|" \
    "${REPO_ROOT}/deploy/ainrf.service" > /etc/systemd/system/ainrf.service
systemctl daemon-reload
systemctl enable ainrf

# ── Set ownership ──────────────────────────────────────────────
chown -R ainrf:ainrf "${INSTALL_DIR}"
chown -R ainrf:ainrf "${STATE_DIR}"

# ── Start ──────────────────────────────────────────────────────
echo ""
echo "=== Starting services ==="
systemctl restart ainrf
systemctl reload nginx

echo ""
echo "=== Deployment complete ==="
echo ""
echo "  API:   https://$(hostname -I | awk '{print $1}')/"
echo "  Logs:  journalctl -u ainrf -f"
echo ""
echo "  API key: ${API_KEY}"
echo "  Admin password: check ${STATE_DIR}/admin_initial_password.txt after first start"
echo ""
echo "  IMPORTANT: Edit /etc/nginx/sites-available/ainrf to restrict"
echo "  the 'geo' block to your specific lab subnet before exposing."

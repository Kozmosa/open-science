#!/usr/bin/env bash
# Generate a self-signed TLS certificate for lab/testing use.
# Output: ./tls/cert.pem, ./tls/key.pem
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TLS_DIR="${SCRIPT_DIR}/tls"
DAYS="${1:-3650}"
CN="${2:-ainrf-lab}"

mkdir -p "${TLS_DIR}"

if [[ -f "${TLS_DIR}/cert.pem" ]]; then
    echo "TLS certificate already exists at ${TLS_DIR}/cert.pem"
    echo "Remove it first if you want to regenerate."
    exit 0
fi

openssl req -x509 -nodes -days "${DAYS}" -newkey rsa:2048 \
    -keyout "${TLS_DIR}/key.pem" \
    -out "${TLS_DIR}/cert.pem" \
    -subj "/CN=${CN}" 2>/dev/null

chmod 644 "${TLS_DIR}/cert.pem"
chmod 600 "${TLS_DIR}/key.pem"

echo "Generated self-signed certificate:"
echo "  Cert: ${TLS_DIR}/cert.pem"
echo "  Key:  ${TLS_DIR}/key.pem"
echo "  CN:   ${CN}"
echo "  Days: ${DAYS}"

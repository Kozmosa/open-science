#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
# AINRF K8s one-shot deploy script
# ══════════════════════════════════════════════════════════════════
#
# Prerequisites:
#   - kubectl configured with target cluster context
#   - Docker image pushed to a registry accessible from the cluster
#   - TLS cert secret created (see tls-secret.yaml comments)
#
# Usage:
#   # First time — create secrets and deploy everything:
#   bash deploy/k8s/deploy.sh
#
#   # Update image only:
#   bash deploy/k8s/deploy.sh --image registry.example.com/ainrf:v1.2.3
#
#   # Tear down:
#   bash deploy/k8s/deploy.sh --destroy
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="ainrf"

usage() {
    echo "Usage: $0 [--image REGISTRY/IMAGE:TAG] [--destroy] [--dry-run]"
    echo ""
    echo "  --image   Set container image (default: ainrf:latest)"
    echo "  --destroy Delete all AINRF K8s resources"
    echo "  --dry-run Print kubectl commands without executing"
    exit 1
}

IMAGE="ainrf:latest"
DESTROY=false
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)  IMAGE="$2"; shift 2 ;;
        --destroy) DESTROY=true; shift ;;
        --dry-run) DRY_RUN="--dry-run=client"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

K="kubectl ${DRY_RUN}"

if [[ "${DESTROY}" == "true" ]]; then
    echo "=== Destroying AINRF K8s resources ==="
    $K delete --ignore-not-found=true -f "${SCRIPT_DIR}/networkpolicy.yaml"
    $K delete --ignore-not-found=true -f "${SCRIPT_DIR}/ingress.yaml"
    $K delete --ignore-not-found=true -f "${SCRIPT_DIR}/service.yaml"
    $K delete --ignore-not-found=true -f "${SCRIPT_DIR}/deployment.yaml"
    $K delete --ignore-not-found=true -f "${SCRIPT_DIR}/pvc.yaml"
    echo "Resources deleted. Secrets and TLS secret preserved."
    echo "To also remove secrets:"
    echo "  kubectl delete secret ainrf-secrets ainrf-tls -n ${NAMESPACE}"
    exit 0
fi

echo "=== Deploying AINRF to Kubernetes ==="
echo "Image: ${IMAGE}"
echo ""

# Apply in dependency order
echo "[1/6] Namespace..."
$K apply -f "${SCRIPT_DIR}/namespace.yaml"

echo "[2/6] Persistent volumes..."
$K apply -f "${SCRIPT_DIR}/pvc.yaml"

echo "[3/6] Secrets (skip if already created)..."
if ! $K get secret ainrf-secrets -n "${NAMESPACE}" &>/dev/null; then
    echo "  Secret ainrf-secrets not found. Creating with placeholder values."
    echo "  IMPORTANT: Replace with real secrets via:"
    echo "    kubectl create secret generic ainrf-secrets --namespace=${NAMESPACE} \\"
    echo "      --from-literal=JWT_SECRET=\$(python3 -c \"import secrets; print(secrets.token_urlsafe(48))\") \\"
    echo "      --from-literal=API_KEY_HASHES=\$(python3 -c \"from hashlib import sha256; print(sha256(b'YOUR_API_KEY').hexdigest())\") \\"
    echo "      --from-literal=ANTHROPIC_API_KEY=sk-ant-... \\"
    echo "      --from-literal=CODEX_API_KEY=sk-..."
    $K apply -f "${SCRIPT_DIR}/secrets.yaml"
else
    echo "  Secret ainrf-secrets already exists, skipping."
fi

echo "[4/6] Deployment..."
if [[ "${IMAGE}" != "ainrf:latest" ]]; then
    # Patch image if custom registry provided
    $K apply -f "${SCRIPT_DIR}/deployment.yaml"
    $K set image deployment/ainrf ainrf="${IMAGE}" -n "${NAMESPACE}"
else
    $K apply -f "${SCRIPT_DIR}/deployment.yaml"
fi

echo "[5/6] Service..."
$K apply -f "${SCRIPT_DIR}/service.yaml"

echo "[6/6] Ingress + NetworkPolicy..."
$K apply -f "${SCRIPT_DIR}/ingress.yaml"
$K apply -f "${SCRIPT_DIR}/networkpolicy.yaml"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "  Check rollout:  kubectl rollout status deployment/ainrf -n ${NAMESPACE}"
echo "  Get pods:        kubectl get pods -n ${NAMESPACE}"
echo "  Port-forward:    kubectl port-forward svc/ainrf 8000:8000 -n ${NAMESPACE}"
echo "  Logs:            kubectl logs -f deployment/ainrf -n ${NAMESPACE}"

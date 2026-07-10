#!/usr/bin/env bash
# ── Shared health polling helpers for deploy scripts ─────────────
#
# Source this file from redeploy-backend.sh, redeploy-frontend.sh,
# scripts/staging.sh, etc.
#
#   source "$(dirname "$0")/lib/health.sh"
#
# Provides:
#   wait_for_url <url> <retries> <delay>
#   wait_for_compose_service <compose_file> <service> <retries> <delay>
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

# Colors (safe to disable if non-TTY)
AINRF_GREEN='\033[0;32m'
AINRF_YELLOW='\033[1;33m'
AINRF_RED='\033[0;31m'
AINRF_BOLD='\033[1m'
AINRF_NC='\033[0m'

_ainrf_info()  { echo -e "${AINRF_GREEN}[deploy]${AINRF_NC} $*"; }
_ainrf_warn()  { echo -e "${AINRF_YELLOW}[deploy]${AINRF_NC} $*"; }
_ainrf_error() { echo -e "${AINRF_RED}[deploy]${AINRF_NC} $*" >&2; }

# Reuse non-empty runtime configuration from an existing container when the
# deploy shell does not already provide it. Values remain process-local and
# are never printed or written to disk.
load_runtime_env_from_container() {
    local container_name="$1"
    local entry key

    if ! docker inspect "${container_name}" >/dev/null 2>&1; then
        return 0
    fi

    while IFS= read -r entry; do
        case "${entry}" in
          AINRF_*=*|OPENSCIENCE_*=*|ANTHROPIC_*=*|CODEX_*=*)
            key="${entry%%=*}"
            if [[ -z "${!key:-}" ]]; then
                export "${entry}"
            fi
            ;;
        esac
    done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${container_name}")
}

# Return 0 if <url> responds with HTTP 2xx/3xx.
_url_is_healthy() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "${url}" >/dev/null 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget --spider -q "${url}" >/dev/null 2>&1
    else
        _ainrf_error "Neither curl nor wget is available for health checks"
        return 1
    fi
}

# Poll a URL until it responds or retries are exhausted.
# Args: url retries delay_seconds
wait_for_url() {
    local url="$1"
    local retries="${2:-30}"
    local delay="${3:-2}"

    _ainrf_info "Waiting for ${url} ..."
    while ((retries > 0)); do
        if _url_is_healthy "${url}"; then
            _ainrf_info "${url} is healthy"
            return 0
        fi
        retries=$((retries - 1))
        if ((retries > 0)); then
            sleep "${delay}"
        fi
    done

    _ainrf_error "Timed out waiting for ${url}"
    return 1
}

# Poll 'docker compose ps' until a service reaches healthy status.
# Args: compose_file service retries delay_seconds
wait_for_compose_service() {
    local compose_file="$1"
    local service="$2"
    local retries="${3:-30}"
    local delay="${4:-2}"

    _ainrf_info "Waiting for Docker service '${service}' to be healthy ..."
    while ((retries > 0)); do
        # docker compose ps --format json output varies by version; grep the
        # human-readable status column for 'healthy' to stay portable.
        if docker compose -f "${compose_file}" ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null \
            | awk -v svc="${service}" '$1 == svc && $0 ~ /\(healthy\)/ {found=1} END {exit !found}'; then
            _ainrf_info "Service '${service}' is healthy"
            return 0
        fi
        retries=$((retries - 1))
        if ((retries > 0)); then
            sleep "${delay}"
        fi
    done

    _ainrf_error "Timed out waiting for service '${service}' to become healthy"
    return 1
}
